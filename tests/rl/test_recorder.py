"""Tests for flowguard.rl.recorder: every call persisted, batching, lifecycle, opacity."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import OperationalError

from flowguard.circuits import Circuit, interface
from flowguard.circuits import store as circuits_store
from flowguard.data import database
from flowguard.rl import store
from flowguard.rl.recorder import RunRecorder
from flowguard.rl.types import ObservationMode, RunStatus, TerminationReason
from flowguard.settings import MissingEnvVarError

REPO_ROOT = Path(__file__).resolve().parents[2]
C1_TOTAL = 92.0


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
        has_tables = (
            inspector.has_table("rl_runs")
            and inspector.has_table("rl_steps")
            and inspector.has_table("circuits")
        )
    except (MissingEnvVarError, OperationalError) as exc:
        pytest.skip(f"database unreachable: {exc.__class__.__name__}")
    if not has_tables:
        pytest.skip("rl/circuit tables missing — run: alembic upgrade head")
    session = database.get_session_factory()()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def circuit_name(db_session):
    """A throw-away C1 copy; the recorder needs a real circuit behind the interface."""
    name = f"test_rl_circuit_{uuid.uuid4().hex[:8]}"
    c1 = Circuit.from_config(REPO_ROOT / "config" / "example_circuit.yaml")
    circuits_store.save_circuit(
        db_session,
        Circuit(
            name,
            c1.nodes(),
            [n.name for n in c1.ext_nodes()],
            delay_override=c1.delay_override,
        ),
    )
    db_session.commit()
    interface.clear_cache()
    yield name
    for run in store.list_runs(db_session, circuit_name=name):
        store.delete_run(db_session, run.id)
    circuits_store.delete_circuit(db_session, name)
    db_session.commit()
    interface.clear_cache()


# --- expected (db) ---

@pytest.mark.db
def test_run_records_every_call_and_returns_bare_total(db_session, circuit_name):
    with RunRecorder(
        circuit_name, 60, strategy="equal_split", session=db_session
    ) as run:
        cost = run.evaluate([10, 10])
        run_id = run.run_id
    assert isinstance(cost, float) and cost == C1_TOTAL

    row = store.load_run(db_session, run_id)
    assert row.status == RunStatus.COMPLETED
    assert row.termination_reason == TerminationReason.BUDGET_EXHAUSTED
    assert row.best_cost == C1_TOTAL
    assert row.best_allocation == [10.0, 10.0]
    assert row.external_node_names == ["N1", "N2"]
    assert len(store.load_history(db_session, run_id)) == 1


@pytest.mark.db
def test_history_is_stripped_in_opaque_and_populated_in_enhanced(
    db_session, circuit_name
):
    with RunRecorder(circuit_name, 60, session=db_session) as opaque:
        opaque.evaluate([10, 10])
        assert opaque.history()[0].audit is None

    with RunRecorder(
        circuit_name,
        60,
        observation_mode=ObservationMode.ENHANCED,
        session=db_session,
    ) as enhanced:
        enhanced.evaluate([10, 10])
        audit = enhanced.history()[0].audit
    assert (audit.delay, audit.overload, audit.safety) == (3.0, 55.0, 34.0)


# --- batching (db) ---

@pytest.mark.db
def test_tail_batch_is_committed_when_length_not_divisible_by_n(
    db_session, circuit_name
):
    with RunRecorder(
        circuit_name, 60, session=db_session, commit_every_n_steps=3
    ) as run:
        for i in range(7):  # 7 = 2 full batches + a tail of 1
            run.evaluate([10 + i, 10])
        run_id = run.run_id
    assert len(store.load_history(db_session, run_id)) == 7


@pytest.mark.db
def test_n_of_one_commits_every_step_visible_to_another_session(
    db_session, circuit_name
):
    other = database.get_session_factory()()
    try:
        with RunRecorder(
            circuit_name, 60, session=db_session, commit_every_n_steps=1
        ) as run:
            run.evaluate([10, 10])
            # A separate session sees it immediately — the commit already happened.
            visible = other.scalars(
                select(store.StepRow).where(store.StepRow.run_id == run.run_id)
            ).all()
            assert len(visible) == 1
    finally:
        other.close()


@pytest.mark.db
def test_abort_mid_batch_keeps_committed_trials_and_consistent_best(
    db_session, circuit_name
):
    run_id = None
    with pytest.raises(RuntimeError, match="strategy blew up"):
        with RunRecorder(
            circuit_name, 60, session=db_session, commit_every_n_steps=2
        ) as run:
            run_id = run.run_id
            run.evaluate([10, 10])  # 92.0 — best
            run.evaluate([12, 12])  # flush here (batch of 2)
            run.evaluate([30, 30])  # uncommitted; lost on rollback
            raise RuntimeError("strategy blew up")

    row = store.load_run(db_session, run_id)
    assert row.status == RunStatus.FAILED
    assert row.termination_reason == TerminationReason.ERROR
    history = store.load_history(db_session, run_id)
    assert len(history) == 2  # the accepted <= N loss
    assert row.best_cost == min(t.total_cost for t in history) == C1_TOTAL


@pytest.mark.db
def test_termination_reason_can_be_overridden_by_the_driver(db_session, circuit_name):
    with RunRecorder(circuit_name, 60, session=db_session) as run:
        run.evaluate([10, 10])
        run.termination_reason = TerminationReason.CONVERGED
        run_id = run.run_id
    assert store.load_run(db_session, run_id).termination_reason == (
        TerminationReason.CONVERGED
    )


# --- failure ---

@pytest.mark.db
def test_wrong_load_count_raises(db_session, circuit_name):
    with pytest.raises(ValueError, match="2 external nodes, got 1 loads"):
        with RunRecorder(circuit_name, 60, session=db_session) as run:
            run.evaluate([10])


@pytest.mark.db
def test_unknown_circuit_raises_before_a_run_row_is_written(db_session):
    ghost = f"test_ghost_{uuid.uuid4().hex[:8]}"
    with pytest.raises(ValueError):
        with RunRecorder(ghost, 60, session=db_session):
            pass
    assert store.list_runs(db_session, circuit_name=ghost) == []


def test_invalid_batch_size_rejected_at_construction():
    with pytest.raises(ValueError, match="commit_every_n_steps must be an integer"):
        RunRecorder("C2", 60, commit_every_n_steps=0)


def test_unknown_observation_mode_rejected():
    with pytest.raises(ValueError, match="unknown observation_mode"):
        RunRecorder("C2", 60, observation_mode="peeking")


def test_evaluate_outside_context_manager_raises():
    with pytest.raises(RuntimeError, match="context manager"):
        RunRecorder("C2", 60).evaluate([10, 10])


def test_import_touches_no_engine():
    assert database._engine is None
