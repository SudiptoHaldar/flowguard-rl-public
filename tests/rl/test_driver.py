"""Tests for flowguard.rl.driver: the propose -> validate -> record loop under a budget."""

import math
import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from flowguard.circuits import Circuit, Node, interface
from flowguard.circuits import store as circuits_store
from flowguard.data import database
from flowguard.rl import store
from flowguard.rl.driver import default_budget, run_algo, validate_allocation
from flowguard.rl.proposers import (
    EqualSplit,
    HillClimb,
    ProposerExhausted,
    RandomSimplex,
    ReleaseSweep,
)
from flowguard.rl.types import (
    AllocationMode,
    ObservationMode,
    RunStatus,
    TerminationReason,
)
from flowguard.settings import MissingEnvVarError

from .test_proposers import make_context

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def clean_caches():
    database.reset_engine()
    interface.clear_cache()
    yield
    database.reset_engine()
    interface.clear_cache()


@pytest.fixture
def db_session():
    try:
        engine = database.get_engine()
        inspector = inspect(engine)
        ready = inspector.has_table("rl_runs") and inspector.has_table("circuits")
        if ready:
            columns = {c["name"] for c in inspector.get_columns("rl_runs")}
            ready = "allocation_mode" in columns
    except (MissingEnvVarError, OperationalError) as exc:
        pytest.skip(f"database unreachable: {exc.__class__.__name__}")
    if not ready:
        pytest.skip("rl/circuit tables missing or stale — run: alembic upgrade head")
    session = database.get_session_factory()()
    yield session
    session.rollback()
    session.close()


def _seed_circuit(session, nodes):
    name = f"test_rl_{uuid.uuid4().hex[:8]}"
    circuits_store.save_circuit(
        session, Circuit(name, nodes, [node.name for node in nodes])
    )
    session.commit()
    interface.clear_cache()
    return name


def _cleanup(session, name):
    for run in store.list_runs(session, circuit_name=name):
        store.delete_run(session, run.id)
    circuits_store.delete_circuit(session, name)
    session.commit()
    interface.clear_cache()


@pytest.fixture
def c2_like(db_session):
    """C1/C2's shape, but defaults-only so it never touches the frozen fixtures."""
    name = _seed_circuit(db_session, [Node("N1", 10, 16), Node("N2", 5, 8)])
    yield name
    _cleanup(db_session, name)


@pytest.fixture
def c3_like(db_session):
    """C3's four-node shape: heterogeneous capacities an equal split cannot represent."""
    name = _seed_circuit(
        db_session,
        [Node("N1", 10, 16), Node("N2", 5, 8), Node("N3", 20, 24), Node("N4", 2, 3)],
    )
    yield name
    _cleanup(db_session, name)


# --- expected (db) ---

@pytest.mark.db
def test_all_baselines_complete_and_persist(db_session, c2_like):
    for factory in (EqualSplit, RandomSimplex, ReleaseSweep, HillClimb):
        result = run_algo(c2_like, 60, factory(), seed=1, session=db_session)
        assert result.trials_used >= 1
        assert result.best_cost is not None
        run = store.load_run(db_session, result.run_id)
        assert run.status == RunStatus.COMPLETED
        assert len(store.load_history(db_session, result.run_id)) == result.trials_used


@pytest.mark.db
def test_hill_climb_reaches_the_optimum_and_beats_the_sweep(db_session, c3_like):
    # True integer optimum for this shape at L=60 is 2.0, at (3, 5, 20, 2).
    climbed = run_algo(c3_like, 60, HillClimb(), seed=1, session=db_session)
    swept = run_algo(c3_like, 60, ReleaseSweep(), seed=1, session=db_session)
    assert climbed.best_cost == 2.0
    assert climbed.best_cost < swept.best_cost


@pytest.mark.db
def test_exhausting_proposers_stop_early_with_converged(db_session, c2_like):
    result = run_algo(c2_like, 60, EqualSplit(), seed=1, session=db_session)
    assert result.trials_used == 1
    assert result.termination_reason == TerminationReason.CONVERGED
    assert result.trials_used < default_budget(2, 60)


@pytest.mark.db
def test_budget_is_honoured_exactly(db_session, c2_like):
    result = run_algo(c2_like, 60, HillClimb(), seed=1, budget=17, session=db_session)
    assert result.trials_used == 17
    assert result.termination_reason == TerminationReason.BUDGET_EXHAUSTED


@pytest.mark.db
def test_allocation_mode_and_params_are_persisted(db_session, c2_like):
    proposer = RandomSimplex()
    result = run_algo(
        c2_like,
        60,
        proposer,
        seed=5,
        allocation_mode=AllocationMode.CONTINUOUS,
        session=db_session,
    )
    run = store.load_run(db_session, result.run_id)
    assert run.allocation_mode == AllocationMode.CONTINUOUS
    assert run.strategy == "random_simplex"
    # Assert the wiring, not a literal: the run must record whatever version the proposer
    # declares, so bumping a proposer's version (as RandomSimplex did at v2) cannot silently
    # break the grouping key v2.06 relies on.
    assert run.strategy_version == proposer.version
    assert run.config_snapshot["proposer"] == proposer.params()


@pytest.mark.db
def test_continuous_mode_allows_fractional_loads(db_session, c2_like):
    result = run_algo(
        c2_like,
        60,
        HillClimb(),
        seed=1,
        allocation_mode=AllocationMode.CONTINUOUS,
        session=db_session,
    )
    history = store.load_history(db_session, result.run_id)
    assert any(
        any(not float(v).is_integer() for v in trial.allocation) for trial in history
    )


# --- failure (db) ---

@pytest.mark.db
def test_integer_mode_rejects_a_fractional_total_load_with_no_run_created(
    db_session, c2_like
):
    before = len(store.list_runs(db_session, circuit_name=c2_like))
    with pytest.raises(ValueError, match="integral total_load"):
        run_algo(c2_like, 60.5, HillClimb(), session=db_session)
    assert len(store.list_runs(db_session, circuit_name=c2_like)) == before


@pytest.mark.db
def test_enhanced_only_proposer_fails_before_a_run_row_exists(db_session, c2_like):
    class EnhancedOnly(HillClimb):
        name = "enhanced_only"
        requires_mode = ObservationMode.ENHANCED

    before = len(store.list_runs(db_session, circuit_name=c2_like))
    with pytest.raises(ValueError, match="requires enhanced"):
        run_algo(c2_like, 60, EnhancedOnly(), session=db_session)
    assert len(store.list_runs(db_session, circuit_name=c2_like)) == before


@pytest.mark.db
def test_a_bad_proposal_raises_and_is_never_repaired(db_session, c2_like):
    class Rogue(EqualSplit):
        name = "rogue"

        def propose(self, context):
            return [-5.0, 100.0]

    with pytest.raises(ValueError, match="must be >= 0"):
        run_algo(c2_like, 60, Rogue(), session=db_session)


# --- DB-free ---

def test_default_budget_scales_linearly_in_nodes_and_log_in_load():
    assert default_budget(2, 20000) == math.ceil(4 * 2 * math.log2(20000))
    assert default_budget(10, 20000) == math.ceil(4 * 10 * math.log2(20000))
    # Linear in n, to within the rounding of a single ceil over the whole product.
    assert abs(default_budget(10, 20000) - 5 * default_budget(2, 20000)) <= 5
    # Logarithmic in L: a 333x load increase costs far less than 333x the budget.
    assert default_budget(10, 20000) < 3 * default_budget(10, 60)
    assert default_budget(2, 2) == 50  # the floor for population methods


def test_validate_allocation_accepts_a_legal_proposal():
    context = make_context()
    assert validate_allocation([10, 5], context) == (10.0, 5.0)
    assert validate_allocation([10, 0], context) == (10.0, 0.0)  # zeros stay legal


@pytest.mark.parametrize(
    "loads, match",
    [
        ([-1, 5], "must be >= 0"),
        ([0, 0], "positive total"),
        ([40, 40], "exceeds total_load"),
        ([1.5, 5], "whole loads"),
        ([float("nan"), 5], "not finite"),
    ],
)
def test_validate_allocation_rejects_illegal_proposals(loads, match):
    with pytest.raises(ValueError, match=match):
        validate_allocation(loads, make_context())


def test_continuous_mode_rejects_sub_floor_positive_loads():
    context = make_context(mode=AllocationMode.CONTINUOUS, min_allocation=0.1)
    with pytest.raises(ValueError, match="below the minimum positive allocation"):
        validate_allocation([0.05, 5], context)
    assert validate_allocation([0.1, 5], context) == (0.1, 5.0)  # the floor itself is fine


def test_unknown_modes_are_rejected():
    with pytest.raises(ValueError, match="unknown allocation_mode"):
        run_algo("C2", 60, HillClimb(), allocation_mode="fractional")
    with pytest.raises(ValueError, match="unknown observation_mode"):
        run_algo("C2", 60, HillClimb(), observation_mode="peeking")


def test_import_touches_no_engine():
    assert database._engine is None
    assert ProposerExhausted  # keep the import meaningful
