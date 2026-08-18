"""Tests for flowguard.rl.benchmark: optimum finding, metrics, seed policy, persistence."""

import json
import math
import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from flowguard.circuits import Circuit, Node, interface
from flowguard.circuits import store as circuits_store
from flowguard.data import database
from flowguard.rl import benchmark, cli, config, store
from flowguard.rl.driver import run_algo
from flowguard.rl.proposers import HillClimb
from flowguard.settings import MissingEnvVarError


@pytest.fixture(autouse=True)
def clean_caches():
    database.reset_engine()
    interface.clear_cache()
    config.reset()
    yield
    database.reset_engine()
    interface.clear_cache()
    config.reset()


@pytest.fixture
def db_session():
    try:
        engine = database.get_engine()
        inspector = inspect(engine)
        ready = inspector.has_table("rl_benchmark_results") and inspector.has_table(
            "circuits"
        )
    except (MissingEnvVarError, OperationalError) as exc:
        pytest.skip(f"database unreachable: {exc.__class__.__name__}")
    if not ready:
        pytest.skip("benchmark tables missing — run: alembic upgrade head")
    session = database.get_session_factory()()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def circuit_name(db_session):
    """A small 2-node circuit; its optimum space is tiny enough to enumerate instantly."""
    name = f"test_bench_{uuid.uuid4().hex[:8]}"
    circuits_store.save_circuit(
        db_session, Circuit(name, [Node("N1", 10, 16), Node("N2", 5, 8)], ["N1", "N2"])
    )
    db_session.commit()
    interface.clear_cache()
    yield name
    # Delete the *headers*, not just the result rows: results carry a FK to their header and
    # cascade from it, whereas deleting results alone orphans one empty `rl_benchmarks` row per
    # test run. Those orphans accumulate and become the newest invocation in the dev DB, which
    # is what a "latest benchmark" reader picks up (surfaced by req_003 v3.01). Every header a
    # test creates is single-circuit, so cascading from it removes nothing else.
    benchmark_ids = {
        row.benchmark_id
        for row in db_session.query(store.BenchmarkResultRow).filter_by(circuit_name=name)
    }
    for benchmark_id in benchmark_ids:
        header = db_session.get(store.BenchmarkRow, benchmark_id)
        if header is not None:
            db_session.delete(header)
    db_session.commit()
    for run in store.list_runs(db_session, circuit_name=name):
        store.delete_run(db_session, run.id)
    circuits_store.delete_circuit(db_session, name)
    db_session.commit()
    interface.clear_cache()


def write_catalog(tmp_path, circuit, loads=(60,), strategies=("hill_climb",), version=99):
    path = tmp_path / "catalog.yaml"
    strategy_lines = "\n".join(f"  - {s}" for s in strategies)
    load_list = ", ".join(str(int(v)) for v in loads)
    path.write_text(
        f"version: {version}\nname: test\nstrategies:\n{strategy_lines}\n"
        f"scenarios:\n  - {{circuit: {circuit}, total_loads: [{load_list}]}}\n",
        encoding="utf-8",
    )
    return path


# --- DB-free ---

def test_enumeration_size_counts_valid_combinations_not_visits():
    # C(B+n, n), the number of allocations with sum <= B — NOT (B+1)**n, which is what a
    # naive itertools.product would visit (31.6M vs 1.4M at n=4, B=74).
    assert benchmark.enumeration_size(2, 30) == math.comb(32, 2) == 496
    assert benchmark.enumeration_size(3, 74) == 73_150
    assert benchmark.enumeration_size(4, 74) == 1_426_425
    assert benchmark.enumeration_size(4, 74) < 75**4  # the naive alternative


def test_seed_policy_runs_deterministic_strategies_once():
    # Five identical hill_climb runs would waste four and fabricate a zero dispersion.
    assert benchmark.seeds_for("hill_climb", 5) == [0]
    assert benchmark.seeds_for("release_sweep", 5) == [0]
    assert benchmark.seeds_for("equal_split", 5) == [0]
    assert benchmark.seeds_for("random_simplex", 5) == [0, 1, 2, 3, 4]


def test_bound_factor_below_the_safe_threshold_is_rejected(monkeypatch):
    # C2's optimum at L=20000 has sum/factor-sum = 1.67, so 1.5 would miss true optima.
    monkeypatch.setattr(
        config,
        "load_config",
        lambda path: {
            "recorder": {"commit_every_n_steps": 50, "stale_run_threshold_seconds": 900},
            "run": {"budget_k": 4, "budget_floor": 50, "min_allocation": 0.1},
            "proposers": {
                "random_simplex": {"concentration": 1.0},
                "hill_climb": {"initial_step_fraction": 0.25},
                "release_sweep": {"spacing": "log"},
            },
            "benchmark": {
                "n_seeds": 5,
                "bound_factor": 1.5,
                "enumeration_cap": 100,
                "scenario_catalog": "config/rl_scenarios.yaml",
            },
        },
    )
    config.reset()
    with pytest.raises(ValueError, match="bound_factor must be >= 1.7"):
        config.benchmark_bound_factor()


def test_summarise_flags_the_degenerate_strategy_and_groups_by_mode():
    class Row:
        def __init__(self, strategy, mode, cost):
            self.circuit_name, self.total_load = "C", 60.0
            self.strategy, self.strategy_version = strategy, "1"
            self.allocation_mode, self.observation_mode = mode, "opaque"
            self.cold_start = True
            self.best_cost, self.improvement, self.convergence_step = cost, 0.5, 3
            self.optimum, self.optimum_method, self.regret = 4.0, "enumerated", cost - 4
            self.safety_fraction = 0.0

    summary = benchmark.summarise(
        [
            Row("hill_climb", "integer", 4.0),
            Row("hill_climb", "continuous", 3.5),   # different mode -> its own group
            Row("equal_split", "integer", 1e9),
        ]
    )
    assert len(summary) == 3  # never pooled across allocation_mode
    flagged = [e for e in summary if e["excluded_from_aggregates"]]
    assert [e["strategy"] for e in flagged] == ["equal_split"]


# --- expected (db) ---

@pytest.mark.db
def test_evaluate_run_reports_improvement_and_first_best_step(db_session, circuit_name):
    result = run_algo(circuit_name, 60, HillClimb(), seed=1, session=db_session)
    metrics = benchmark.evaluate_run(db_session, result.run_id)
    history = store.load_history(db_session, result.run_id)

    assert metrics.best_cost == result.best_cost
    assert metrics.first_cost == history[0].total_cost
    assert 0 <= metrics.improvement <= 1
    # the FIRST trial reaching the best cost, since ties are structural
    first_best = next(t.step_index for t in history if t.total_cost == metrics.best_cost)
    assert metrics.convergence_step == first_best
    assert metrics.cold_start is True


@pytest.mark.db
def test_find_optimum_enumerates_and_hill_climb_matches_it(db_session, circuit_name):
    optimum = benchmark.find_optimum(db_session, circuit_name, 60)
    assert optimum.method == "enumerated"
    assert optimum.value == 4.0  # this shape's known optimum at L=60, at (10, 5)
    result = run_algo(circuit_name, 60, HillClimb(), seed=1, session=db_session)
    assert result.best_cost == optimum.value


@pytest.mark.db
def test_find_optimum_falls_back_when_the_space_is_too_large(
    db_session, circuit_name, monkeypatch
):
    monkeypatch.setattr(config, "benchmark_enumeration_cap", lambda: 1)
    run_algo(circuit_name, 60, HillClimb(), seed=1, session=db_session)
    optimum = benchmark.find_optimum(db_session, circuit_name, 60)
    assert optimum.method == "best_observed"
    assert optimum.value is not None


@pytest.mark.db
def test_run_benchmark_persists_header_and_results(db_session, circuit_name, tmp_path):
    catalog = write_catalog(
        tmp_path, circuit_name, loads=(60,), strategies=("hill_climb", "random_simplex")
    )
    benchmark_id = benchmark.run_benchmark(db_session, catalog_path=catalog, n_seeds=3)
    db_session.commit()

    rows = store.load_benchmark_results(db_session, benchmark_id)
    by_strategy = {}
    for row in rows:
        by_strategy.setdefault(row.strategy, []).append(row)
    # deterministic once, stochastic n_seeds — the D4 policy
    assert len(by_strategy["hill_climb"]) == 1
    assert len(by_strategy["random_simplex"]) == 3

    climbed = by_strategy["hill_climb"][0]
    assert climbed.optimum_method == "enumerated"
    assert climbed.regret == 0.0  # hill_climb is optimal on this shape
    assert climbed.run_id is not None


@pytest.mark.db
def test_benchmark_cli_json_parses(db_session, circuit_name, tmp_path):
    catalog = write_catalog(tmp_path, circuit_name, loads=(60,))
    payload = json.loads(
        cli.cmd_benchmark(db_session, catalog=str(catalog), n_seeds=1, as_json=True)
    )
    db_session.commit()
    assert "benchmark_id" in payload
    assert payload["summary"][0]["optimum_method"] == "enumerated"


# --- failure ---

@pytest.mark.db
def test_catalog_naming_an_unseeded_circuit_says_which(db_session, tmp_path):
    catalog = write_catalog(tmp_path, "no_such_circuit_xyz")
    with pytest.raises(ValueError, match="no_such_circuit_xyz"):
        benchmark.run_benchmark(db_session, catalog_path=catalog)


def test_catalog_with_an_unknown_strategy_is_rejected(tmp_path):
    catalog = write_catalog(tmp_path, "C2", strategies=("nope",))
    with pytest.raises(ValueError, match="unknown strategies"):
        benchmark.load_catalog(catalog)


def test_shipped_catalog_is_loadable_and_names_known_strategies():
    catalog = benchmark.load_catalog()
    assert catalog.version >= 1
    assert {s.circuit for s in catalog.scenarios} >= {"C2", "C3", "C4", "C5"}


def test_import_touches_no_engine():
    assert database._engine is None
