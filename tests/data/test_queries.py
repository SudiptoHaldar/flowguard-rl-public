"""Tests for flowguard.data.queries: the chart read layer and the rules it enforces.

The DB-free half covers the correctness rules that live in pure helpers — thinning that must
never drop an improvement, an envelope computed before thinning, and the ``summarise`` key
mapping. The db-marked half covers the SQL and the two contracts this layer inherits: only
completed runs are visible, and incomparable populations are never pooled.
"""

import importlib
import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from flowguard.data import database, queries
from flowguard.rl import store
from flowguard.rl.types import (
    ObservationMode,
    PenaltyAudit,
    RunStatus,
    TerminationReason,
)
from flowguard.settings import MissingEnvVarError

AUDIT = PenaltyAudit(3.0, 55.0, 34.0)

SUMMARY_ENTRY = {
    "circuit": "C2",
    "total_load": 1440.0,
    "strategy": "hill_climb",
    "strategy_version": "v1",
    "allocation_mode": "integer",
    "observation_mode": "opaque",
    "cold_start": True,
    "runs": 1,
    "best_cost_median": 91.0,
    "best_cost_min": 91.0,
    "best_cost_max": 91.0,
    "improvement_median": 0.5,
    "convergence_step_median": 12,
    "optimum": 91.0,
    "optimum_method": "enumerated",
    "regret_median": 0.0,
    "safety_fraction_median": 0.0,
    "excluded_from_aggregates": False,
}


# --- DB-free: pure helpers ---


def test_running_best_is_the_envelope():
    """Expected: non-increasing, and it is the running minimum, not the raw cost."""
    assert queries.running_best([100.0, 90.0, 95.0, 80.0]) == [100.0, 90.0, 90.0, 80.0]
    assert queries.running_best([]) == []


@pytest.mark.parametrize("max_points", [1, 2, 3, 5, 8, 13])
def test_thinning_never_drops_an_improvement(max_points):
    """The mandatory set survives every budget — a dropped improvement falsifies the curve."""
    flags = [i in (0, 7, 19, 40) for i in range(50)]
    kept = queries.keep_indices(flags, max_points)
    improvements = {i for i, flag in enumerate(flags) if flag}
    assert improvements <= set(kept)
    assert {0, 49} <= set(kept)  # first and last always survive
    assert kept == sorted(set(kept))


def test_mandatory_set_wins_over_max_points():
    """max_points=1 cannot drop improvements; a denser chart beats a wrong one."""
    flags = [True, False, True, False, True]
    kept = queries.keep_indices(flags, 1)
    assert kept == [0, 2, 4]


def test_envelope_is_computed_before_thinning():
    """The improvement sits where a stride would skip it; retained points keep the true best."""
    costs = [100.0, 99.0, 98.0, 10.0, 97.0, 96.0, 95.0, 94.0]
    flags = [i == 0 or costs[i] < min(costs[:i]) for i in range(len(costs))]
    envelope = queries.running_best(costs)
    kept = queries.keep_indices(flags, 4)
    assert all(envelope[i] == min(costs[: i + 1]) for i in kept)
    assert envelope[-1] == 10.0  # the drop is carried forward, not lost


def test_downsampled_is_false_when_every_point_is_mandatory():
    """Nothing was dropped, so nothing may claim it was — even under a small budget."""
    flags = [True, True, True]
    assert queries.keep_indices(flags, 1) == [0, 1, 2]


def test_full_series_returned_when_no_budget():
    assert queries.keep_indices([False] * 5, None) == [0, 1, 2, 3, 4]
    assert queries.keep_indices([], 10) == []


# --- DB-free: failure cases ---


@pytest.mark.parametrize("bad", [0, -1, True])
def test_invalid_max_points_rejected_at_call(bad):
    with pytest.raises(ValueError, match="max_points"):
        queries.keep_indices([False, False], bad)


def test_cell_from_summary_maps_every_key():
    """Pins the summarise contract, including circuit -> circuit_name."""
    cell = queries.cell_from_summary(SUMMARY_ENTRY)
    assert cell.circuit_name == "C2"
    assert cell.optimum_method == "enumerated"
    assert cell.excluded_from_aggregates is False
    assert cell.best_cost_median == 91.0
    assert cell.convergence_step_median == 12


def test_cell_from_summary_rejects_a_missing_key():
    """Failure: if summarise's shape changes, this layer fails loudly, not silently."""
    incomplete = {key: value for key, value in SUMMARY_ENTRY.items() if key != "optimum"}
    with pytest.raises(KeyError):
        queries.cell_from_summary(incomplete)


def test_improvement_matches_the_harness_formula():
    assert queries._improvement(100.0, 25.0) == 0.75
    assert queries._improvement(0.0, 0.0) == 0.0  # no division by zero
    assert queries._improvement(None, 5.0) == 0.0
    assert queries._improvement(10.0, None) == 0.0


# --- DB-free: module hygiene (spec D1) ---


def test_module_declares_no_models():
    """Read-only, structurally: nothing here contributes a table to the metadata."""
    for value in vars(queries).values():
        assert not (
            isinstance(value, type) and issubclass(value, database.Base)
        ), f"{value!r} is a model — queries.py must declare none"


def test_import_creates_no_engine():
    """The lazy-DB contract: importing the query layer must not connect."""
    database.reset_engine()
    importlib.reload(queries)
    assert database._engine is None


# --- db fixtures ---


@pytest.fixture(autouse=True)
def clean_engine_cache():
    database.reset_engine()
    yield
    database.reset_engine()


@pytest.fixture
def db_session():
    """Live session; skips when the DB is unreachable or the RL tables are missing."""
    try:
        engine = database.get_engine()
        inspector = inspect(engine)
        ready = inspector.has_table("rl_steps") and inspector.has_table(
            "rl_benchmark_results"
        )
    except (MissingEnvVarError, OperationalError) as exc:
        pytest.skip(f"database unreachable: {exc.__class__.__name__}")
    if not ready:
        pytest.skip("rl tables missing — run: alembic upgrade head")
    session = database.get_session_factory()()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def circuit_name():
    """A name unique to this test, so listings are not polluted by real dev-DB runs."""
    return f"test_chart_{uuid.uuid4().hex[:8]}"


def make_run(session, circuit_name, *, status=RunStatus.COMPLETED, **overrides):
    kwargs = dict(
        circuit_name=circuit_name,
        total_load=60.0,
        external_node_names=["N1", "N2"],
        strategy="hill_climb",
    )
    kwargs.update(overrides)
    run = store.create_run(session, **kwargs)
    session.flush()
    if status != RunStatus.RUNNING:
        store.close_run(
            session,
            run.id,
            str(status),
            str(TerminationReason.BUDGET_EXHAUSTED),
            best_cost=None,
            best_allocation=None,
        )
    session.commit()
    return run


def add_steps(session, run_id, costs, allocations=None):
    """Append trials, marking is_best exactly where the running minimum strictly improved."""
    best = float("inf")
    for index, cost in enumerate(costs):
        improved = cost < best
        best = min(best, cost)
        allocation = (
            allocations[index] if allocations else [10.0 + index, 20.0 + index]
        )
        store.append_step(session, run_id, index, allocation, cost, AUDIT, is_best=improved)
    run = store.load_run(session, run_id)
    run.best_cost = min(costs) if costs else None
    session.commit()


def cleanup_runs(session, circuit_name):
    for run in store.list_runs(session, circuit_name=circuit_name):
        store.delete_run(session, run.id)
    session.commit()


# --- expected (db) ---


@pytest.mark.db
def test_run_summary_and_series_round_trip(db_session, circuit_name):
    run = make_run(db_session, circuit_name)
    try:
        add_steps(db_session, run.id, [100.0, 90.0, 95.0, 80.0])

        summary = queries.get_run(db_session, run.id)
        assert summary.trials_used == 4
        assert summary.first_cost == 100.0
        assert summary.best_cost == 80.0
        assert summary.improvement == pytest.approx(0.2)
        assert summary.cold_start is True
        assert summary.external_node_names == ("N1", "N2")

        series = queries.get_run_series(db_session, run.id)
        assert [point.step_index for point in series.points] == [0, 1, 2, 3]
        assert [point.best_so_far for point in series.points] == [100.0, 90.0, 90.0, 80.0]
        assert series.total_points == 4
        assert series.downsampled is False

        scenarios = {(s.circuit_name, s.total_load): s for s in queries.list_scenarios(db_session)}
        assert scenarios[(circuit_name, 60.0)].run_count == 1
        assert scenarios[(circuit_name, 60.0)].best_cost == 80.0

        listed = queries.list_runs_for(db_session, circuit_name=circuit_name)
        assert [item.run_id for item in listed] == [run.id]
        assert listed[0].trials_used == 4
    finally:
        cleanup_runs(db_session, circuit_name)


@pytest.mark.db
def test_downsampling_keeps_improvements_against_real_rows(db_session, circuit_name):
    run = make_run(db_session, circuit_name)
    try:
        # Improvements at 0, 1, 5 and 17 — 5 and 17 sit where a uniform stride would skip them.
        costs = [100.0, 99.0, 99.0, 99.0, 99.0, 50.0] + [99.0] * 11 + [10.0, 99.0, 99.0]
        add_steps(db_session, run.id, costs)

        series = queries.get_run_series(db_session, run.id, max_points=6)
        kept = {point.step_index for point in series.points}
        assert {0, 1, 5, 17} <= kept  # every improving step survived
        assert series.total_points == 20
        assert series.downsampled is True
        # The envelope was computed over all 20 rows, not the retained ones.
        assert min(point.best_so_far for point in series.points) == 10.0
    finally:
        cleanup_runs(db_session, circuit_name)


@pytest.mark.db
def test_allocation_series_matches_the_view(db_session, circuit_name):
    """Pins the documented v_rl_step_loads contract: wide reads and the view agree.

    ``position`` in the view is 1-based (PostgreSQL arrays are); ``step_index`` is 0-based.
    """
    run = make_run(db_session, circuit_name)
    try:
        allocations = [[10.0, 20.0], [11.0, 19.0], [12.0, 18.0]]
        add_steps(db_session, run.id, [100.0, 90.0, 80.0], allocations)

        series = queries.get_allocation_series(db_session, run.id)
        assert series.node_names == ("N1", "N2")

        wide = {
            (point.step_index, index + 1): (series.node_names[index], load)
            for point in series.points
            for index, load in enumerate(point.loads)
        }
        rows = db_session.execute(
            text(
                "SELECT step_index, position, node_name, load "
                "FROM v_rl_step_loads WHERE run_id = :run_id"
            ),
            {"run_id": run.id},
        ).all()
        assert rows, "the view returned nothing for a run with steps"
        assert len(rows) == len(wide)
        for step_index, position, node_name, load in rows:
            assert wide[(step_index, position)] == (node_name, load)
    finally:
        cleanup_runs(db_session, circuit_name)


@pytest.mark.db
def test_stored_is_best_matches_the_computed_envelope(db_session, circuit_name):
    """The steps where the running minimum strictly decreased are exactly the is_best steps."""
    run = make_run(db_session, circuit_name)
    try:
        add_steps(db_session, run.id, [100.0, 90.0, 95.0, 90.0, 80.0])
        series = queries.get_run_series(db_session, run.id)
        costs = [point.total_cost for point in series.points]
        improved = {
            index
            for index, cost in enumerate(costs)
            if index == 0 or cost < min(costs[:index])
        }
        flagged = {index for index, point in enumerate(series.points) if point.is_best}
        assert improved == flagged
    finally:
        cleanup_runs(db_session, circuit_name)


# --- edge (db) ---


@pytest.mark.db
def test_completed_run_with_no_trials(db_session, circuit_name):
    """Edge: nothing recorded. Empty but valid, never an exception."""
    run = make_run(db_session, circuit_name)
    try:
        summary = queries.get_run(db_session, run.id)
        assert summary.trials_used == 0
        assert summary.first_cost is None
        assert summary.improvement == 0.0

        series = queries.get_run_series(db_session, run.id)
        assert series.points == ()
        assert series.total_points == 0
        assert series.downsampled is False

        allocations = queries.get_allocation_series(db_session, run.id)
        assert allocations.points == ()
    finally:
        cleanup_runs(db_session, circuit_name)


@pytest.mark.db
def test_comparison_never_pools_incomparable_populations(db_session, circuit_name):
    """Two observation modes and two strategy versions must yield four cells, not one."""
    header = store.create_benchmark(
        db_session,
        catalog_name=f"test_{uuid.uuid4().hex[:6]}",
        catalog_version=99,
        n_seeds=1,
        bound_factor=2.0,
        enumeration_cap=1000,
    )
    db_session.commit()
    try:
        common = dict(
            circuit_name=circuit_name,
            total_load=60.0,
            strategy="hill_climb",
            seed=0,
            allocation_mode="integer",
            cold_start=True,
            first_cost=100.0,
            best_cost=80.0,
            improvement=0.2,
            trials_used=4,
            convergence_step=3,
            optimum=80.0,
            optimum_method="enumerated",
            regret=0.0,
            safety_trials=0,
            safety_fraction=0.0,
        )
        for mode in (ObservationMode.OPAQUE, ObservationMode.ENHANCED):
            for version in ("v1", "v2"):
                store.add_benchmark_result(
                    db_session,
                    header.id,
                    observation_mode=str(mode),
                    strategy_version=version,
                    **common,
                )
        store.add_benchmark_result(
            db_session,
            header.id,
            **{**common, "strategy": "equal_split"},
            observation_mode=str(ObservationMode.OPAQUE),
            strategy_version="v1",
        )
        db_session.commit()

        grid = queries.get_comparison(db_session, header.id)
        assert grid.benchmark.catalog_version == 99
        assert len(grid.cells) == 5, "modes and strategy versions must not be pooled"
        assert {(cell.observation_mode, cell.strategy_version) for cell in grid.cells} >= {
            ("opaque", "v1"),
            ("opaque", "v2"),
            ("enhanced", "v1"),
            ("enhanced", "v2"),
        }
        degenerate = [c for c in grid.cells if c.strategy == "equal_split"]
        assert degenerate and degenerate[0].excluded_from_aggregates is True
        assert all(cell.circuit_name == circuit_name for cell in grid.cells)

        # The default selection is the newest invocation.
        latest = queries.get_comparison(db_session)
        assert latest.benchmark.benchmark_id == header.id
        assert queries.list_benchmarks(db_session)[0].benchmark_id == header.id
    finally:
        db_session.delete(header)  # cascades to its result rows
        db_session.commit()


# --- failure (db) ---


@pytest.mark.db
def test_partial_runs_are_invisible(db_session, circuit_name):
    """Spec D5: not completed means not listed, not aggregated, and not chartable."""
    run = make_run(db_session, circuit_name, status=RunStatus.FAILED)
    try:
        add_steps(db_session, run.id, [100.0, 90.0])

        assert queries.list_runs_for(db_session, circuit_name=circuit_name) == ()
        assert all(
            scenario.circuit_name != circuit_name
            for scenario in queries.list_scenarios(db_session)
        )
        with pytest.raises(ValueError, match="not chartable"):
            queries.get_run_series(db_session, run.id)
        with pytest.raises(ValueError, match="not chartable"):
            queries.get_allocation_series(db_session, run.id)
        with pytest.raises(ValueError, match="not chartable"):
            queries.get_run(db_session, run.id)
    finally:
        cleanup_runs(db_session, circuit_name)


# --- node capacities and ties (v3.06 D1/D4) ---


@pytest.mark.db
def test_capacities_come_from_the_circuit_and_match_the_run(db_session, circuit_name):
    """The first read of req_001's tables by this group."""
    from flowguard.circuits import store as circuits_store
    from flowguard.circuits.model import Circuit, Node

    circuits_store.save_circuit(
        db_session,
        Circuit(circuit_name, [Node("N1", 10, 16), Node("N2", 5, 8)], ["N1", "N2"]),
    )
    db_session.commit()
    run = make_run(db_session, circuit_name)
    try:
        add_steps(db_session, run.id, [100.0, 90.0])
        capacities = queries.get_allocation_series(db_session, run.id).capacities

        assert capacities.matches_run is True
        assert [n.name for n in capacities.nodes] == ["N1", "N2"]
        assert capacities.nodes[0].load_factor == 10
        assert capacities.nodes[0].load_safety_cap == 16
    finally:
        cleanup_runs(db_session, circuit_name)
        circuits_store.delete_circuit(db_session, circuit_name)
        db_session.commit()


@pytest.mark.db
def test_capacities_report_drift_without_hiding_what_changed(db_session, circuit_name):
    """A run whose circuit gained a node: marks unusable, but the change is still visible."""
    from flowguard.circuits import store as circuits_store
    from flowguard.circuits.model import Circuit, Node

    circuits_store.save_circuit(
        db_session,
        Circuit(
            circuit_name,
            [Node("N1", 10, 16), Node("N2", 5, 8), Node("N3", 7, 9)],
            ["N1", "N2", "N3"],
        ),
    )
    db_session.commit()
    # The run recorded only two external nodes — the circuit has since gained a third.
    run = make_run(db_session, circuit_name, external_node_names=["N1", "N2"])
    try:
        add_steps(db_session, run.id, [100.0, 90.0])
        capacities = queries.get_allocation_series(db_session, run.id).capacities

        assert capacities.matches_run is False
        # Still sent, so a caller can say what changed rather than only that something did.
        assert [n.name for n in capacities.nodes] == ["N1", "N2", "N3"]
    finally:
        cleanup_runs(db_session, circuit_name)
        circuits_store.delete_circuit(db_session, circuit_name)
        db_session.commit()


@pytest.mark.db
def test_capacities_are_none_when_the_circuit_is_gone(db_session, circuit_name):
    """Distinct from drift: there is nothing to compare against at all."""
    run = make_run(db_session, circuit_name)  # no circuit of this name was ever saved
    try:
        add_steps(db_session, run.id, [100.0, 90.0])
        assert queries.get_allocation_series(db_session, run.id).capacities is None
    finally:
        cleanup_runs(db_session, circuit_name)


@pytest.mark.db
def test_ties_are_counted_over_all_steps_not_the_thinned_series(db_session, circuit_name):
    """The test that would catch a client-side implementation.

    Four trials share the best cost with three distinct allocations, but only the first is
    flagged ``is_best`` — so a count taken from a thinned series would report 1.
    """
    run = make_run(db_session, circuit_name)
    try:
        allocations = [
            [10.0, 20.0],  # best, flagged
            [11.0, 19.0],  # ties, NOT flagged
            [12.0, 18.0],  # ties, NOT flagged
            [10.0, 20.0],  # ties and repeats the first allocation
        ]
        add_steps(db_session, run.id, [50.0, 50.0, 50.0, 50.0], allocations)

        # Thin hard: the series cannot possibly carry all the tied trials.
        series = queries.get_allocation_series(db_session, run.id, max_points=1)
        flagged = sum(1 for row in store._steps(db_session, run.id) if row.is_best)

        assert series.best.cost == 50.0
        assert len(series.best.allocations) == 3  # distinct, duplicates collapsed
        assert series.best.allocations[0] == (10.0, 20.0)
        assert flagged == 1
        assert len(series.best.allocations) > len(series.points)
    finally:
        cleanup_runs(db_session, circuit_name)


@pytest.mark.db
def test_best_is_none_for_a_run_with_no_trials(db_session, circuit_name):
    run = make_run(db_session, circuit_name)
    try:
        assert queries.get_allocation_series(db_session, run.id).best is None
    finally:
        cleanup_runs(db_session, circuit_name)


# --- scenario reference (v3.04 D1) ---


def seed_benchmark(session, circuit_name, *, budget, optimum=80.0, random_costs=(90.0, 95.0)):
    """A benchmark covering one scenario: a hill_climb row plus n random_simplex rows."""
    header = store.create_benchmark(
        session,
        catalog_name=f"ref_{uuid.uuid4().hex[:6]}",
        catalog_version=7,
        n_seeds=len(random_costs),
        bound_factor=2.0,
        enumeration_cap=1000,
    )
    session.flush()
    common = dict(
        circuit_name=circuit_name,
        total_load=60.0,
        allocation_mode="integer",
        observation_mode="opaque",
        cold_start=True,
        first_cost=100.0,
        improvement=0.2,
        trials_used=4,
        convergence_step=3,
        optimum=optimum,
        optimum_method="enumerated",
        safety_trials=0,
        safety_fraction=0.0,
    )
    run = make_run(session, circuit_name, budget=budget)
    store.add_benchmark_result(
        session, header.id, strategy="hill_climb", strategy_version="v1", seed=0,
        run_id=run.id, best_cost=optimum, regret=0.0, **common,
    )
    for index, cost in enumerate(random_costs):
        seeded = make_run(session, circuit_name, budget=budget, strategy="random_simplex")
        store.add_benchmark_result(
            session, header.id, strategy="random_simplex", strategy_version="2", seed=index,
            run_id=seeded.id, best_cost=cost, regret=cost - optimum, **common,
        )
    session.commit()
    return header


@pytest.mark.db
def test_reference_carries_the_optimum_and_best_of_random(db_session, circuit_name):
    header = seed_benchmark(db_session, circuit_name, budget=40, random_costs=(90.0, 95.0, 99.0))
    viewed = make_run(db_session, circuit_name, budget=40)
    try:
        add_steps(db_session, viewed.id, [100.0, 85.0])
        reference = queries.get_run_series(db_session, viewed.id).reference

        assert reference.optimum == 80.0
        assert reference.optimum_method == "enumerated"
        # Median of three random_simplex costs at the same budget.
        assert reference.best_of_random == 95.0
        assert reference.best_of_random_strategy_version == "2"
        assert reference.catalog_version == 7
        assert reference.benchmark_id == header.id
    finally:
        db_session.delete(db_session.get(store.BenchmarkRow, header.id))
        db_session.commit()
        cleanup_runs(db_session, circuit_name)


@pytest.mark.db
def test_reference_is_none_without_benchmark_coverage(db_session, circuit_name):
    """A scenario nobody has benchmarked draws no reference lines — not a zero."""
    run = make_run(db_session, circuit_name)
    try:
        add_steps(db_session, run.id, [100.0, 90.0])
        assert queries.get_run_series(db_session, run.id).reference is None
    finally:
        cleanup_runs(db_session, circuit_name)


@pytest.mark.db
def test_best_of_random_omitted_when_budgets_differ(db_session, circuit_name):
    """'At equal budget' is a claim about effort, so an unequal comparison is withheld."""
    header = seed_benchmark(db_session, circuit_name, budget=40)
    viewed = make_run(db_session, circuit_name, budget=999)  # a different budget entirely
    try:
        add_steps(db_session, viewed.id, [100.0, 85.0])
        reference = queries.get_run_series(db_session, viewed.id).reference

        # The optimum is a property of the scenario and still stands...
        assert reference.optimum == 80.0
        # ...but the equal-budget comparison does not.
        assert reference.best_of_random is None
        assert reference.best_of_random_strategy_version is None
    finally:
        db_session.delete(db_session.get(store.BenchmarkRow, header.id))
        db_session.commit()
        cleanup_runs(db_session, circuit_name)


@pytest.mark.db
def test_unknown_run_and_benchmark_raise_distinct_errors(db_session):
    with pytest.raises(ValueError, match="does not exist"):
        queries.get_run(db_session, -1)
    with pytest.raises(ValueError, match="benchmark -1 does not exist"):
        queries.get_comparison(db_session, -1)


# --- typed failures (v3.02 D5): the classes the HTTP layer dispatches on ---


@pytest.mark.db
def test_failures_are_typed_and_still_value_errors(db_session, circuit_name):
    """The API maps by class; every existing caller matching on ValueError still works."""
    run = make_run(db_session, circuit_name, status=RunStatus.FAILED)
    try:
        with pytest.raises(queries.RunNotChartable) as not_chartable:
            queries.get_run(db_session, run.id)
        assert not_chartable.value.run_id == run.id
        assert not_chartable.value.status == "failed"
        assert isinstance(not_chartable.value, ValueError)

        with pytest.raises(queries.UnknownRun) as unknown:
            queries.get_run(db_session, -1)
        assert unknown.value.run_id == -1
        assert isinstance(unknown.value, ValueError)

        with pytest.raises(queries.UnknownBenchmark) as benchmark:
            queries.get_comparison(db_session, -1)
        assert benchmark.value.benchmark_id == -1
        assert isinstance(benchmark.value, ValueError)
    finally:
        cleanup_runs(db_session, circuit_name)


# --- pagination (v3.02 D9) ---


@pytest.mark.db
def test_pagination_slices_and_counts_consistently(db_session, circuit_name):
    ids = [make_run(db_session, circuit_name).id for _ in range(3)]
    try:
        assert queries.count_runs_for(db_session, circuit_name=circuit_name) == 3

        first = queries.list_runs_for(db_session, circuit_name=circuit_name, limit=2)
        assert [item.run_id for item in first] == sorted(ids, reverse=True)[:2]

        second = queries.list_runs_for(
            db_session, circuit_name=circuit_name, limit=2, offset=2
        )
        assert [item.run_id for item in second] == sorted(ids, reverse=True)[2:]

        # limit=None keeps the pre-v3.02 behaviour: every match.
        assert len(queries.list_runs_for(db_session, circuit_name=circuit_name)) == 3
    finally:
        cleanup_runs(db_session, circuit_name)


@pytest.mark.db
def test_count_excludes_partial_runs_like_the_listing(db_session, circuit_name):
    """A `total` that counted partial runs would describe a page it does not match."""
    make_run(db_session, circuit_name)
    make_run(db_session, circuit_name, status=RunStatus.FAILED)
    try:
        assert queries.count_runs_for(db_session, circuit_name=circuit_name) == 1
        assert len(queries.list_runs_for(db_session, circuit_name=circuit_name)) == 1
    finally:
        cleanup_runs(db_session, circuit_name)


@pytest.mark.parametrize("bad", [0, -1, True])
def test_invalid_limit_rejected(bad):
    with pytest.raises(ValueError, match="limit"):
        queries.list_runs_for(None, limit=bad)


def test_invalid_offset_rejected():
    with pytest.raises(ValueError, match="offset"):
        queries.list_runs_for(None, offset=-1)


# --- topology (v3.07) ---


def save_dag(session, circuit_name):
    """C4's shape under a test name: 3 externals -> 4 internals, with two merges."""
    from flowguard.circuits import store as circuits_store
    from flowguard.circuits.model import Circuit, Edge, Node

    nodes = [
        Node("N1", 13, 18), Node("N2", 7, 10), Node("N3", 17, 20),
        Node("N4", 4, 7), Node("N5", 10, 12), Node("N6", 15, 20), Node("N7", 2, 3),
    ]
    edges = [
        Edge("N1", "N4", 0.4), Edge("N1", "N5", 0.6),
        Edge("N2", "N5", 0.7), Edge("N2", "N6", 0.3),
        Edge("N3", "N6", 0.8), Edge("N3", "N7", 0.2),
    ]
    circuits_store.save_circuit(
        session, Circuit(circuit_name, nodes, ["N1", "N2", "N3"], edges=edges)
    )
    session.commit()


def drop_circuit(session, circuit_name):
    from flowguard.circuits import store as circuits_store

    try:
        circuits_store.delete_circuit(session, circuit_name)
        session.commit()
    except ValueError:
        session.rollback()


@pytest.mark.db
def test_topology_carries_the_engine_propagation(db_session, circuit_name):
    """The loads come from the engine, and land where the measured C4 figures say."""
    save_dag(db_session, circuit_name)
    run = make_run(db_session, circuit_name, external_node_names=["N1", "N2", "N3"])
    try:
        add_steps(db_session, run.id, [100.0], [[13.0, 6.0, 17.0]])
        topology = queries.get_run_topology(db_session, run.id)

        assert topology.matches_run is True
        assert topology.is_flat is False
        assert len(topology.nodes) == 7
        assert len(topology.edges) == 6
        assert [n.kind for n in topology.nodes[:3]] == ["external"] * 3
        assert [n.kind for n in topology.nodes[3:]] == ["internal"] * 4

        loads = dict(zip([n.name for n in topology.nodes], topology.carried[0].loads))
        assert loads["N4"] == pytest.approx(5.2)
        # The binding constraint: N5 merges N1 and N2 and lands exactly on its cap of 12.
        assert loads["N5"] == pytest.approx(12.0)
        assert loads["N6"] == pytest.approx(15.4)
        # And the optimum knowingly sits above N7's cap of 3.
        assert loads["N7"] == pytest.approx(3.4)
    finally:
        cleanup_runs(db_session, circuit_name)
        drop_circuit(db_session, circuit_name)


@pytest.mark.db
def test_topology_carries_the_requested_load_which_trials_need_not_match(
    db_session, circuit_name
):
    """The scenario's requested load travels with the topology, and is not the assigned total.

    Only ``equal_split`` allocates exactly ``total_load``; every other strategy treats it as a
    target it may undershoot. Run 1091 in the live database declares 10000 and its best trial
    assigns 35 — so a diagram showing an assigned total without the requested one alongside
    would invite the reader to assume they are the same number.
    """
    save_dag(db_session, circuit_name)
    run = make_run(
        db_session,
        circuit_name,
        total_load=10000.0,
        external_node_names=["N1", "N2", "N3"],
    )
    try:
        add_steps(db_session, run.id, [100.0], [[13.0, 6.0, 17.0]])
        topology = queries.get_run_topology(db_session, run.id)

        assert topology.total_load == pytest.approx(10000.0)
        loads = dict(zip([n.name for n in topology.nodes], topology.carried[0].loads))
        assigned = sum(loads[n.name] for n in topology.nodes if n.kind == "external")
        assert assigned == pytest.approx(36.0)
        # The gap is the point: it is real, and it is enormous.
        assert assigned < topology.total_load
    finally:
        cleanup_runs(db_session, circuit_name)
        drop_circuit(db_session, circuit_name)


@pytest.mark.db
def test_topology_reports_a_flat_circuit_rather_than_failing(db_session, circuit_name):
    """Three of the four shipped circuits are flat — the common case, not an edge case."""
    from flowguard.circuits import store as circuits_store
    from flowguard.circuits.model import Circuit, Node

    circuits_store.save_circuit(
        db_session,
        Circuit(circuit_name, [Node("N1", 10, 16), Node("N2", 5, 8)], ["N1", "N2"]),
    )
    db_session.commit()
    run = make_run(db_session, circuit_name)
    try:
        add_steps(db_session, run.id, [100.0], [[10.0, 10.0]])
        topology = queries.get_run_topology(db_session, run.id)

        assert topology.is_flat is True
        assert topology.edges == ()
        assert len(topology.nodes) == 2
        # A flat circuit still carries loads: every external node is terminal.
        assert topology.carried[0].loads == (10.0, 10.0)
    finally:
        cleanup_runs(db_session, circuit_name)
        drop_circuit(db_session, circuit_name)


@pytest.mark.db
def test_topology_withholds_loads_on_drift_but_keeps_the_structure(db_session, circuit_name):
    save_dag(db_session, circuit_name)
    # The run recorded only two externals; the circuit has three.
    run = make_run(db_session, circuit_name, external_node_names=["N1", "N2"])
    try:
        add_steps(db_session, run.id, [100.0], [[13.0, 6.0]])
        topology = queries.get_run_topology(db_session, run.id)

        assert topology.matches_run is False
        # Structure survives — it is honestly the circuit's current shape...
        assert len(topology.nodes) == 7
        assert len(topology.edges) == 6
        # ...but the loads do not, because they would flow through a graph the run never saw.
        assert topology.carried == ()
    finally:
        cleanup_runs(db_session, circuit_name)
        drop_circuit(db_session, circuit_name)


@pytest.mark.db
def test_topology_is_none_when_the_circuit_is_gone(db_session, circuit_name):
    run = make_run(db_session, circuit_name)
    try:
        add_steps(db_session, run.id, [100.0])
        assert queries.get_run_topology(db_session, run.id) is None
    finally:
        cleanup_runs(db_session, circuit_name)


@pytest.mark.db
def test_topology_uses_the_same_keep_set_as_the_allocation_series(db_session, circuit_name):
    """One scrubber drives both views, so the retained steps must line up exactly."""
    save_dag(db_session, circuit_name)
    run = make_run(db_session, circuit_name, external_node_names=["N1", "N2", "N3"])
    try:
        costs = [100.0, 90.0, 95.0, 80.0, 85.0, 70.0]
        allocations = [[13.0, 6.0, 17.0 - i] for i in range(len(costs))]
        add_steps(db_session, run.id, costs, allocations)

        topology = queries.get_run_topology(db_session, run.id, max_points=3)
        series = queries.get_allocation_series(db_session, run.id, max_points=3)

        assert [c.step_index for c in topology.carried] == [
            p.step_index for p in series.points
        ]
    finally:
        cleanup_runs(db_session, circuit_name)
        drop_circuit(db_session, circuit_name)
