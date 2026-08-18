"""Read-only query layer for the charting component (req_003 v3.01).

The single data source for the chart API (v3.02) and everything above it: ordered run-replay
series, per-node allocation series, the circuit × load × strategy comparison grid, and the
pickers that reach them.

**Read-only, structurally.** This module declares no SQLAlchemy models, subclasses no
``Base``, and performs no INSERT/UPDATE/DELETE and no commit — it reuses
:mod:`flowguard.rl.store`'s models for reading only. That is the concrete form of the v2.06 D0
obligation: nothing the charting side computes may reach a proposer.

**The inherited rules are enforced here**, below the API, so no endpoint and no widget can
bypass them:

- only ``status = 'completed'`` runs are visible anywhere (v2.01 D6.5, spec D5) — a partial run
  is an audit record, reachable through ``python -m flowguard.rl runs``, never through a chart;
- populations that are not comparable are never pooled — observation mode, allocation mode,
  strategy version and cold/warm start all partition the comparison grid, and ``equal_split``
  is flagged out of aggregates.

That last rule is not re-implemented here. :func:`flowguard.rl.benchmark.summarise` already
expresses it, and this module calls it (spec D3): one implementation of the pooling discipline,
so a chart can never drift from the harness that produced the numbers. **A new comparison
metric belongs in ``summarise``, not here.**

**Not** :func:`flowguard.rl.benchmark.evaluate_run`: that function reads
:func:`flowguard.rl.store.load_audit`, the named human/audit path (v2.01 D5). Nothing in this
module touches audit data — the per-category cost breakdown reaches charts only as
``rl_benchmark_results.safety_fraction``. The ``improvement`` expression below is deliberately
identical to the harness's so the two layers cannot disagree.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from flowguard.circuits import store as circuits_store
from flowguard.rl import benchmark, store
from flowguard.rl.types import RunStatus

#: The one filter every function in this module applies (spec D5). ``Text`` column against a
#: ``StrEnum`` member — mirrors ``store.best_observed_cost``.
_COMPLETED = str(RunStatus.COMPLETED)


# --------------------------------------------------------------------------------------
# Typed failures (v3.02 D5). All subclass ``ValueError`` and keep the messages they had as
# plain ValueErrors, so every existing caller — and every test matching on the message —
# behaves identically. The types exist so the HTTP layer can map an error to a status code
# by **class** rather than by matching message strings, which would break the first time a
# message is reworded.
# --------------------------------------------------------------------------------------


class UnknownRun(ValueError):
    """No run with this id exists."""

    def __init__(self, run_id: int):
        super().__init__(f"run {run_id} does not exist")
        self.run_id = run_id


class RunNotChartable(ValueError):
    """The run exists but did not complete, so it is not chart evidence (spec D5).

    Deliberately distinct from :class:`UnknownRun`: hiding partial runs means not
    *presenting* them, not lying about one the caller named.
    """

    def __init__(self, run_id: int, status: str):
        super().__init__(f"run {run_id} is not chartable (status={status})")
        self.run_id = run_id
        self.status = status


class UnknownBenchmark(ValueError):
    """No benchmark invocation with this id exists."""

    def __init__(self, benchmark_id: int):
        super().__init__(f"benchmark {benchmark_id} does not exist")
        self.benchmark_id = benchmark_id


# --------------------------------------------------------------------------------------
# Records (spec D2): frozen, SQLAlchemy-free, FastAPI-free. Tuples rather than lists, so a
# returned record cannot be mutated by a caller. The wire format (columnar vs objects) is
# v3.02's decision, deliberately not baked in here.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioRef:
    """One Circuit(Load) problem that has been run at least once."""

    circuit_name: str
    total_load: float
    run_count: int
    best_cost: float | None


@dataclass(frozen=True)
class RunSummary:
    """Header for one completed run.

    No ``status`` field: everything this module returns is ``completed``, so carrying the
    column would imply a variation that cannot occur.
    """

    run_id: int
    circuit_name: str
    total_load: float
    strategy: str
    strategy_version: str | None
    seed: int | None
    budget: int | None
    observation_mode: str
    allocation_mode: str
    cold_start: bool
    termination_reason: str | None
    external_node_names: tuple[str, ...]
    trials_used: int
    first_cost: float | None
    best_cost: float | None
    improvement: float
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class SeriesPoint:
    """One trial on the cost-vs-trial curve.

    ``best_so_far`` is the envelope value at this step, computed over the **full** series
    before any downsampling — so it stays exact at any resolution.
    """

    step_index: int
    total_cost: float
    best_so_far: float
    is_best: bool


@dataclass(frozen=True)
class TopologyNode:
    """One node of the circuit as it is defined **now** (req_003 v3.07)."""

    name: str
    #: ``external`` (a node the optimizer may load) or ``internal`` (fed only by edges).
    kind: str
    load_factor: float
    load_safety_cap: float


@dataclass(frozen=True)
class TopologyEdge:
    """A directed line; ``weight`` is the fraction of the source's load sent along it."""

    source: str
    target: str
    weight: float


@dataclass(frozen=True)
class CarriedStep:
    """Carried load per node at one trial, positional against :attr:`CircuitTopology.nodes`."""

    step_index: int
    loads: tuple[float, ...]


@dataclass(frozen=True)
class CircuitTopology:
    """The circuit's shape, and what each node carried during a run.

    The loads come from the **engine's own propagation** (:meth:`Circuit.carried_loads`) — this
    layer never re-derives the rule, it asks for the result.

    Node identity here belongs to the **circuit**, not the run. That is the inverse of the
    per-node allocation panels, where the run's stored array is the authority, and it is
    deliberate: the diagram *is* the circuit's current structure. The run only supplies loads,
    and only when :attr:`matches_run` says they may be trusted.
    """

    circuit_name: str
    #: The scenario's requested load. Carried here because only ``equal_split`` allocates
    #: exactly this much: every other strategy treats it as a target it may undershoot, so an
    #: assigned total shown without it invites the reader to assume they are the same number.
    total_load: float
    nodes: tuple[TopologyNode, ...]
    edges: tuple[TopologyEdge, ...]
    #: False when the circuit's external nodes no longer match the run's own list. The
    #: structure is still returned — it is honestly the circuit's shape — but the loads are
    #: withheld, because they would be propagated through a graph the run never saw.
    matches_run: bool
    #: Empty when :attr:`matches_run` is false. Otherwise one entry per **retained** step,
    #: using the same keep set as the allocation series, so a scrubber never refetches.
    carried: tuple[CarriedStep, ...]

    @property
    def is_flat(self) -> bool:
        """No edges: every external node is terminal and nothing propagates.

        The common case — three of the four shipped circuits are flat — so callers must treat
        it as a state to render, not as a failure to load a graph.
        """
        return not self.edges


@dataclass(frozen=True)
class ScenarioReference:
    """Benchmark-derived reference figures for one ``(circuit_name, total_load)``.

    Scenario-scoped **provenance**, not a run-level fact — which is why ``optimum_method`` and
    the catalog version travel with it. A regret against a ``best_observed`` optimum is not the
    same claim as one against an ``enumerated`` optimum, so the method is never separated from
    the number.

    ``best_of_random`` is the bar v2.02 D2 set for a learner: the median best cost of the
    ``random_simplex`` runs **at equal budget**. That is a claim about effort, so it is verified
    rather than asserted — see :func:`_scenario_reference`.
    """

    optimum: float | None
    optimum_method: str
    best_of_random: float | None
    best_of_random_strategy_version: str | None
    catalog_name: str
    catalog_version: int
    benchmark_id: int


@dataclass(frozen=True)
class RunSeries:
    run: RunSummary
    points: tuple[SeriesPoint, ...]
    total_points: int
    downsampled: bool
    #: ``None`` when no benchmark covers this scenario — the chart then draws no reference
    #: lines, which is honest rather than absent-as-zero.
    reference: ScenarioReference | None = None


@dataclass(frozen=True)
class AllocationPoint:
    """The allocation vector at one step, positional against ``AllocationSeries.node_names``."""

    step_index: int
    loads: tuple[float, ...]


@dataclass(frozen=True)
class ExternalNode:
    """One external node's capacities, from the circuit's **current** definition."""

    name: str
    load_factor: float
    load_safety_cap: float


@dataclass(frozen=True)
class NodeCapacities:
    """Capacity marks for an allocation view, and whether they may be trusted.

    ``matches_run`` is false when the circuit's external nodes no longer match the ones the run
    recorded. The nodes are still carried so a caller can show *what changed*, but the marks
    must not be drawn: a capacity line from a definition the run never saw is worse than no
    line, and req_002 made runs self-describing precisely so this is detectable.
    """

    nodes: tuple[ExternalNode, ...]
    matches_run: bool


@dataclass(frozen=True)
class BestAllocations:
    """The distinct allocations that reached a run's best cost.

    **Computed over every step, never over the thinned series.** ``rl_steps.is_best`` marks a
    *strict* improvement, so a trial that merely matches the best is not flagged — and the
    thinning keep set (spec D4) retains only flagged steps. Measured on the shipped corpus:
    C3 at L=60 under ``hill_climb`` reaches its best cost with **14 distinct allocations**, of
    which exactly **one** is flagged. Counting from the series would report 1.

    A flat optimum is a real property of the cost surface — it means the optimizer had genuine
    freedom in where to put the load — so it is reported rather than collapsed to "the best".
    """

    cost: float
    allocations: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class AllocationSeries:
    run_id: int
    node_names: tuple[str, ...]
    points: tuple[AllocationPoint, ...]
    total_points: int
    downsampled: bool
    #: ``None`` when the circuit no longer exists — a different state from drift.
    capacities: NodeCapacities | None = None
    #: ``None`` when the run recorded no trials.
    best: BestAllocations | None = None


@dataclass(frozen=True)
class BenchmarkHeader:
    """Provenance for one harness invocation — what makes a plotted number re-checkable."""

    benchmark_id: int
    catalog_name: str
    catalog_version: int
    n_seeds: int
    bound_factor: float
    enumeration_cap: int
    notes: str | None
    created_at: datetime


@dataclass(frozen=True)
class ComparisonCell:
    """One comparable population, aggregated across its seeds.

    The seven leading fields are the grouping keys; pooling across any of them is the error
    this whole layer exists to prevent.
    """

    circuit_name: str
    total_load: float
    strategy: str
    strategy_version: str | None
    allocation_mode: str
    observation_mode: str
    cold_start: bool
    runs: int
    best_cost_median: float
    best_cost_min: float
    best_cost_max: float
    improvement_median: float
    convergence_step_median: float
    optimum: float | None
    optimum_method: str
    regret_median: float | None
    safety_fraction_median: float
    excluded_from_aggregates: bool


@dataclass(frozen=True)
class ComparisonGrid:
    benchmark: BenchmarkHeader
    cells: tuple[ComparisonCell, ...]


# --------------------------------------------------------------------------------------
# Pure helpers — no ``Session``, no ORM. The correctness rules live here so they are
# testable with no database (the reason D2 chose plain records).
# --------------------------------------------------------------------------------------


def running_best(costs) -> list[float]:
    """Running minimum over the whole series.

    Computed **before** any thinning: if it were computed over retained points only, every
    point after a dropped improvement would carry a wrong envelope value.
    """
    best = float("inf")
    envelope = []
    for cost in costs:
        best = min(best, cost)
        envelope.append(best)
    return envelope


def keep_indices(is_best_flags, max_points: int | None) -> list[int]:
    """Indices to retain when thinning a series to roughly ``max_points``.

    The **mandatory set** — every improving step plus the first and the last — always
    survives, even when it alone exceeds ``max_points``. A chart denser than requested is a
    cosmetic problem; a chart missing an improvement is a wrong result, which makes thinning a
    correctness concern rather than a performance one.

    The remaining budget is filled by a uniform stride, so the result may come in slightly
    under ``max_points``. Output is ordered by index; density is not preserved and nothing
    downstream may assume it.

    Shared by the cost series and the allocation series so the two stay aligned step for step.
    """
    if max_points is not None and (isinstance(max_points, bool) or max_points < 1):
        raise ValueError(f"max_points must be None or >= 1, got {max_points!r}")
    count = len(is_best_flags)
    if count == 0:
        return []
    if max_points is None or count <= max_points:
        return list(range(count))

    keep = {0, count - 1}
    keep.update(index for index, flag in enumerate(is_best_flags) if flag)
    budget = max_points - len(keep)  # may be <= 0: the mandatory set wins
    if budget > 0:
        stride = max(1, count // budget)
        for index in range(0, count, stride):
            if len(keep) >= max_points:
                break
            keep.add(index)
    return sorted(keep)


def _improvement(first_cost: float | None, best_cost: float | None) -> float:
    """Cost reduction from the run's own first trial — the headline metric (v2.06 D1).

    Deliberately the same expression as ``benchmark.evaluate_run`` so the charting layer and
    the harness can never report different improvements for the same run.
    """
    if not first_cost or best_cost is None:
        return 0.0
    return (first_cost - best_cost) / first_cost


def cell_from_summary(entry: dict) -> ComparisonCell:
    """Convert one ``benchmark.summarise`` entry into a pinned record.

    The only place ``summarise``'s dict keys are read — note ``circuit`` becomes
    ``circuit_name`` here, so no consumer above indexes raw keys.
    """
    return ComparisonCell(
        circuit_name=entry["circuit"],
        total_load=entry["total_load"],
        strategy=entry["strategy"],
        strategy_version=entry["strategy_version"],
        allocation_mode=entry["allocation_mode"],
        observation_mode=entry["observation_mode"],
        cold_start=entry["cold_start"],
        runs=entry["runs"],
        best_cost_median=entry["best_cost_median"],
        best_cost_min=entry["best_cost_min"],
        best_cost_max=entry["best_cost_max"],
        improvement_median=entry["improvement_median"],
        convergence_step_median=entry["convergence_step_median"],
        optimum=entry["optimum"],
        optimum_method=entry["optimum_method"],
        regret_median=entry["regret_median"],
        safety_fraction_median=entry["safety_fraction_median"],
        excluded_from_aggregates=entry["excluded_from_aggregates"],
    )


# --------------------------------------------------------------------------------------
# Reads. Every function takes an open ``Session`` and never commits (the repository contract
# inherited from ``circuits/store.py`` and ``rl/store.py``).
# --------------------------------------------------------------------------------------


def _first_cost_subquery():
    """Correlated: the cost of step 0. Step indices are dense, so 0 is exactly the first."""
    return (
        select(store.StepRow.total_cost)
        .where(
            store.StepRow.run_id == store.RunRow.id,
            store.StepRow.step_index == 0,
        )
        .scalar_subquery()
    )


def _trials_subquery():
    """Correlated trial count — keeps listings to one query instead of one per run."""
    return (
        select(func.count(store.StepRow.id))
        .where(store.StepRow.run_id == store.RunRow.id)
        .scalar_subquery()
    )


def _summary(row, first_cost: float | None, trials_used: int) -> RunSummary:
    return RunSummary(
        run_id=row.id,
        circuit_name=row.circuit_name,
        total_load=row.total_load,
        strategy=row.strategy,
        strategy_version=row.strategy_version,
        seed=row.seed,
        budget=row.budget,
        observation_mode=row.observation_mode,
        allocation_mode=row.allocation_mode,
        # Resolved here so no consumer re-derives it (v2.01 D6.6: NULL parent IS cold-started).
        cold_start=row.parent_run_id is None,
        termination_reason=row.termination_reason,
        external_node_names=tuple(row.external_node_names),
        trials_used=trials_used or 0,
        first_cost=first_cost,
        best_cost=row.best_cost,
        improvement=_improvement(first_cost, row.best_cost),
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _require_chartable(session, run_id: int):
    """Load a run, refusing anything not ``completed``.

    Unknown and not-chartable are different errors on purpose. Hiding partial runs (spec D5)
    means not *presenting* them; it does not mean lying about a run the caller named. Returning
    an empty series instead would be indistinguishable from a completed run with no trials.
    """
    try:
        run = store.load_run(session, run_id)
    except ValueError as exc:
        # store raises a *plain* ValueError; re-raise as the typed one so callers (and the
        # v3.02 HTTP handlers) can dispatch on the class.
        raise UnknownRun(run_id) from exc
    if run.status != _COMPLETED:
        raise RunNotChartable(run_id, run.status)
    return run


def _step_rows(session, run_id: int) -> list:
    """Trials in replay order — the ``(run_id, step_index)`` unique index serves this."""
    return list(
        session.scalars(
            select(store.StepRow)
            .where(store.StepRow.run_id == run_id)
            .order_by(store.StepRow.step_index)
        ).all()
    )


def list_scenarios(session) -> tuple[ScenarioRef, ...]:
    """Every Circuit(Load) problem with at least one completed run — the picker feed.

    Derived from runs, not from the circuits table: a circuit nobody has run has nothing to
    chart, and the picker should not offer dead ends.
    """
    stmt = (
        select(
            store.RunRow.circuit_name,
            store.RunRow.total_load,
            func.count(store.RunRow.id),
            func.min(store.RunRow.best_cost),
        )
        .where(store.RunRow.status == _COMPLETED)
        .group_by(store.RunRow.circuit_name, store.RunRow.total_load)
        .order_by(store.RunRow.circuit_name, store.RunRow.total_load)
    )
    return tuple(
        ScenarioRef(circuit_name=name, total_load=load, run_count=count, best_cost=best)
        for name, load, count, best in session.execute(stmt)
    )


def _apply_run_filters(stmt, circuit_name, total_load, strategy):
    """The filter chain shared by the listing and its count.

    One function, so a page and the ``total`` describing it can never disagree — including
    the completed-only rule, which is applied by both callers below.
    """
    if circuit_name is not None:
        stmt = stmt.where(store.RunRow.circuit_name == circuit_name)
    if total_load is not None:
        stmt = stmt.where(store.RunRow.total_load == float(total_load))
    if strategy is not None:
        stmt = stmt.where(store.RunRow.strategy == strategy)
    return stmt


def list_runs_for(
    session,
    *,
    circuit_name: str | None = None,
    total_load: float | None = None,
    strategy: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[RunSummary, ...]:
    """Completed runs, newest first, optionally narrowed and paginated.

    ``limit=None`` returns every match — the default, so existing callers are unaffected.
    Pagination lives here rather than in the HTTP layer because slicing above would mean
    fetching every completed run to show fifty.
    """
    if limit is not None and (isinstance(limit, bool) or limit < 1):
        raise ValueError(f"limit must be None or >= 1, got {limit!r}")
    if isinstance(offset, bool) or offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset!r}")
    stmt = (
        select(store.RunRow, _first_cost_subquery(), _trials_subquery())
        .where(store.RunRow.status == _COMPLETED)
        .order_by(store.RunRow.id.desc())
    )
    stmt = _apply_run_filters(stmt, circuit_name, total_load, strategy)
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return tuple(
        _summary(row, first_cost, trials)
        for row, first_cost, trials in session.execute(stmt)
    )


def count_runs_for(
    session,
    *,
    circuit_name: str | None = None,
    total_load: float | None = None,
    strategy: str | None = None,
) -> int:
    """How many completed runs match — the unpaginated total for :func:`list_runs_for`."""
    stmt = select(func.count(store.RunRow.id)).where(
        store.RunRow.status == _COMPLETED
    )
    stmt = _apply_run_filters(stmt, circuit_name, total_load, strategy)
    return session.scalar(stmt) or 0


def get_run(session, run_id: int) -> RunSummary:
    """Header for one completed run; raises for unknown or non-completed runs."""
    _require_chartable(session, run_id)
    row, first_cost, trials = session.execute(
        select(store.RunRow, _first_cost_subquery(), _trials_subquery()).where(
            store.RunRow.id == run_id
        )
    ).one()
    return _summary(row, first_cost, trials)


def get_run_series(
    session, run_id: int, max_points: int | None = None
) -> RunSeries:
    """The cost-vs-trial replay feed: every trial, with the best-so-far envelope.

    Ordered by ``step_index`` — the replay contract v2.01 was built to support.
    """
    summary = get_run(session, run_id)
    rows = _step_rows(session, run_id)
    envelope = running_best([row.total_cost for row in rows])
    kept = keep_indices([row.is_best for row in rows], max_points)
    points = tuple(
        SeriesPoint(
            step_index=rows[index].step_index,
            total_cost=rows[index].total_cost,
            best_so_far=envelope[index],
            is_best=rows[index].is_best,
        )
        for index in kept
    )
    return RunSeries(
        run=summary,
        points=points,
        total_points=len(rows),
        # What was actually dropped — not merely "was a limit requested".
        downsampled=len(points) < len(rows),
        reference=_scenario_reference(
            session, summary.circuit_name, summary.total_load, summary.budget
        ),
    )


def get_allocation_series(
    session, run_id: int, max_points: int | None = None
) -> AllocationSeries:
    """Per-node loads over the run, **wide**: the allocation as a vector (spec D6).

    Read from ``rl_steps.allocation`` rather than the ``v_rl_step_loads`` view, on the same
    ground v2.01 D2 gave for the proposer's read-back — a chart wants the vector as a vector,
    and the view multiplies rows by node count (40,000 against 5,000 for a 5,000-trial run on
    8 nodes). Node names come from the run's own ``external_node_names``, which is the ordering
    authority for a historical run, exactly as it is inside the view. The view remains the
    normalised surface for ad-hoc per-node querying, and a db-marked test pins the two together.

    Thinned with the same keep set as :func:`get_run_series`, so cost and allocation stay
    aligned step for step.
    """
    run = _require_chartable(session, run_id)
    rows = _step_rows(session, run_id)
    kept = keep_indices([row.is_best for row in rows], max_points)
    points = tuple(
        AllocationPoint(
            step_index=rows[index].step_index,
            loads=tuple(rows[index].allocation),
        )
        for index in kept
    )
    return AllocationSeries(
        run_id=run_id,
        node_names=tuple(run.external_node_names),
        points=points,
        total_points=len(rows),
        downsampled=len(points) < len(rows),
        capacities=_capacities_for(session, run),
        # From `rows` — every step — not from `points`, which may be thinned.
        best=_best_allocations(rows),
    )


#: The random baseline v2.02 D2 names as the bar a learner must clear. Spelled once here
#: rather than inferred from "stochastic", which is a different property.
_RANDOM_BASELINE = "random_simplex"


def _scenario_reference(
    session, circuit_name: str, total_load: float, run_budget: int | None
) -> ScenarioReference | None:
    """Reference figures for a scenario, from the newest benchmark that **covers it**.

    Not the newest invocation overall: a later benchmark may have run a different catalog that
    omits this scenario, and its numbers would say nothing about this run.
    """
    benchmark_id = session.scalar(
        select(func.max(store.BenchmarkResultRow.benchmark_id)).where(
            store.BenchmarkResultRow.circuit_name == circuit_name,
            store.BenchmarkResultRow.total_load == float(total_load),
        )
    )
    if benchmark_id is None:
        return None
    header = session.get(store.BenchmarkRow, benchmark_id)
    if header is None:  # results outlived their header — nothing to attribute them to
        return None

    rows = session.execute(
        # LEFT JOIN: rl_benchmark_results.run_id is ON DELETE SET NULL, so a deleted run
        # leaves a result row with no budget to compare against.
        select(store.BenchmarkResultRow, store.RunRow.budget)
        .outerjoin(store.RunRow, store.RunRow.id == store.BenchmarkResultRow.run_id)
        .where(
            store.BenchmarkResultRow.benchmark_id == benchmark_id,
            store.BenchmarkResultRow.circuit_name == circuit_name,
            store.BenchmarkResultRow.total_load == float(total_load),
        )
    ).all()
    if not rows:
        return None

    random_rows = [(row, budget) for row, budget in rows if row.strategy == _RANDOM_BASELINE]
    # "At equal budget" is a claim about effort, so verify it. An unknown budget (deleted run)
    # counts as unverifiable, and one mismatching seed disqualifies the whole median rather
    # than quietly comparing a subset.
    comparable = [row for row, budget in random_rows if budget is not None and budget == run_budget]
    best_of_random = None
    best_of_random_version = None
    if random_rows and len(comparable) == len(random_rows):
        best_of_random = statistics.median([row.best_cost for row in comparable])
        best_of_random_version = comparable[0].strategy_version

    return ScenarioReference(
        # optimum is a property of the scenario, identical across the invocation's rows.
        optimum=rows[0][0].optimum,
        optimum_method=rows[0][0].optimum_method,
        best_of_random=best_of_random,
        best_of_random_strategy_version=best_of_random_version,
        catalog_name=header.catalog_name,
        catalog_version=header.catalog_version,
        benchmark_id=benchmark_id,
    )


def get_external_nodes(session, circuit_name: str) -> tuple[ExternalNode, ...] | None:
    """External nodes and their capacities, in the circuit's own external order.

    ``None`` when the circuit does not exist — deliberately distinct from "the circuit exists
    but has changed", because the two mean different things to a reader.

    This is the **one place this group reads req_001's tables**. It is permitted by the same
    reasoning as v2.06 D0 — the charting side measures, it does not compete — and it mirrors
    ``flowguard.rl.benchmark``'s own capacity read. It stays read-only.
    """
    try:
        circuit = circuits_store.load_circuit(session, circuit_name)
    except ValueError:
        return None
    return tuple(
        ExternalNode(
            name=node.name,
            load_factor=node.load_factor,
            load_safety_cap=node.load_safety_cap,
        )
        for node in circuit.ext_nodes()
    )


def _capacities_for(session, run) -> NodeCapacities | None:
    nodes = get_external_nodes(session, run.circuit_name)
    if nodes is None:
        return None
    # Compared by NAME in order, never by position alone: a node inserted into the circuit
    # would otherwise shift every capacity onto the wrong node while the lengths still agreed.
    matches = [node.name for node in nodes] == list(run.external_node_names)
    return NodeCapacities(nodes=nodes, matches_run=matches)


def _best_allocations(rows) -> BestAllocations | None:
    """Distinct allocations reaching the best cost, over **all** step rows (see the record)."""
    if not rows:
        return None
    best = min(row.total_cost for row in rows)
    seen: set[tuple[float, ...]] = set()
    distinct: list[tuple[float, ...]] = []
    for row in rows:
        if row.total_cost != best:
            continue
        allocation = tuple(row.allocation)
        if allocation not in seen:
            seen.add(allocation)
            distinct.append(allocation)
    return BestAllocations(cost=best, allocations=tuple(distinct))


def get_run_topology(
    session, run_id: int, max_points: int | None = None
) -> CircuitTopology | None:
    """The run's circuit as a graph, with the load each node carried at each retained step.

    ``None`` when the circuit no longer exists. Propagation is delegated to
    :meth:`flowguard.circuits.model.Circuit.carried_loads`; nothing here re-implements it.
    """
    run = _require_chartable(session, run_id)
    try:
        circuit = circuits_store.load_circuit(session, run.circuit_name)
    except ValueError:
        return None

    external_names = [node.name for node in circuit.ext_nodes()]
    external_set = set(external_names)
    nodes = tuple(
        TopologyNode(
            name=node.name,
            kind="external" if node.name in external_set else "internal",
            load_factor=node.load_factor,
            load_safety_cap=node.load_safety_cap,
        )
        for node in circuit.nodes()
    )
    edges = tuple(
        TopologyEdge(source=edge.source, target=edge.target, weight=edge.weight)
        for edge in circuit.edges()
    )
    matches = external_names == list(run.external_node_names)
    total_load = float(run.total_load)

    carried: tuple[CarriedStep, ...] = ()
    if matches:
        rows = _step_rows(session, run_id)
        # The same keep set as the allocation series, so the two scrub in step.
        kept = keep_indices([row.is_best for row in rows], max_points)
        steps = []
        for index in kept:
            row = rows[index]
            loads = circuit.carried_loads(dict(zip(external_names, row.allocation)))
            steps.append(
                CarriedStep(
                    step_index=row.step_index,
                    loads=tuple(loads[node.name] for node in nodes),
                )
            )
        carried = tuple(steps)

    return CircuitTopology(
        circuit_name=run.circuit_name,
        total_load=total_load,
        nodes=nodes,
        edges=edges,
        matches_run=matches,
        carried=carried,
    )


def _header(row) -> BenchmarkHeader:
    return BenchmarkHeader(
        benchmark_id=row.id,
        catalog_name=row.catalog_name,
        catalog_version=row.catalog_version,
        n_seeds=row.n_seeds,
        bound_factor=row.bound_factor,
        enumeration_cap=row.enumeration_cap,
        notes=row.notes,
        created_at=row.created_at,
    )


def list_benchmarks(session) -> tuple[BenchmarkHeader, ...]:
    """Harness invocations, newest first."""
    return tuple(
        _header(row)
        for row in session.scalars(
            select(store.BenchmarkRow).order_by(store.BenchmarkRow.id.desc())
        ).all()
    )


def get_comparison(session, benchmark_id: int | None = None) -> ComparisonGrid | None:
    """The circuit × load × strategy grid for one harness invocation (spec D3).

    ``benchmark_id=None`` selects the most recent invocation and returns ``None`` when none
    exists — an empty corpus is a state to render, not an error. An explicitly named benchmark
    that does not exist **raises**: the caller asked for something specific.

    The grouping and the median/min/max come from :func:`flowguard.rl.benchmark.summarise`,
    unchanged. Reimplementing them here would create a second expression of the pooling rules,
    free to drift, with the drift visible only as a wrong chart.
    """
    if benchmark_id is None:
        row = session.scalars(
            select(store.BenchmarkRow).order_by(store.BenchmarkRow.id.desc()).limit(1)
        ).first()
        if row is None:
            return None
    else:
        row = session.get(store.BenchmarkRow, benchmark_id)
        if row is None:
            raise UnknownBenchmark(benchmark_id)

    results = store.load_benchmark_results(session, row.id)
    cells = tuple(cell_from_summary(entry) for entry in benchmark.summarise(results))
    return ComparisonGrid(benchmark=_header(row), cells=cells)
