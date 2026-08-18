"""Response models for the chart HTTP API (req_003 v3.02).

These mirror the frozen records in :mod:`flowguard.data.queries` **1:1, with identical field
names**, so there is one vocabulary from the SQL column through the dataclass and the JSON to
the Dart model. Renaming at the wire is where record/response drift starts.

Conversion is mechanical: every model sets ``from_attributes=True``, and FastAPI converts a
returned dataclass (recursing into nested records and turning tuples into JSON arrays) before
validating it against the declared ``response_model``. **No hand-written dict building.**

Shape decision (spec D4): **array of objects**, not columnar arrays. Columnar is ~60% smaller
and closer to what chart libraries eat, but the OpenAPI schema would stop describing a point
and mismatched column lengths would become a new bug class — in exchange for kilobytes over
localhost, which the server-side series cap (D6) already bounds.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Record(BaseModel):
    """Base for every response model: built straight from a queries dataclass."""

    model_config = ConfigDict(from_attributes=True)


class ScenarioRefOut(_Record):
    """One Circuit(Load) problem with at least one completed run."""

    circuit_name: str
    total_load: float
    run_count: int
    best_cost: float | None


class RunSummaryOut(_Record):
    """Header for one completed run. No ``status``: everything here is ``completed``."""

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
    external_node_names: list[str]
    trials_used: int
    first_cost: float | None
    best_cost: float | None
    improvement: float
    created_at: datetime
    completed_at: datetime | None


class SeriesPointOut(_Record):
    """One trial on the cost-vs-trial curve.

    ``best_so_far`` is the envelope over the **full** series, computed before downsampling,
    so it stays exact at any resolution.
    """

    step_index: int
    total_cost: float
    best_so_far: float
    is_best: bool


class TopologyNodeOut(_Record):
    """One node of the circuit's current definition."""

    name: str
    kind: str
    load_factor: float
    load_safety_cap: float


class TopologyEdgeOut(_Record):
    """A directed line carrying `weight` of the source's load."""

    source: str
    target: str
    weight: float


class CarriedStepOut(_Record):
    """Carried load per node at one trial, positional against `nodes`."""

    step_index: int
    loads: list[float]


class CircuitTopologyOut(_Record):
    """The circuit's shape plus per-step carried loads (req_003 v3.07).

    `edges` empty means a flat circuit — a state to render, not a failure. `matches_run` false
    means the circuit has changed since the run: the structure still stands, but `carried` is
    empty because those loads would be propagated through a graph the run never saw.
    """

    circuit_name: str
    #: The scenario's requested load — not what any trial necessarily assigned. Only
    #: ``equal_split`` allocates exactly this; other strategies routinely undershoot it.
    total_load: float
    nodes: list[TopologyNodeOut]
    edges: list[TopologyEdgeOut]
    matches_run: bool
    carried: list[CarriedStepOut]


class ScenarioReferenceOut(_Record):
    """Benchmark-derived reference figures for the run's scenario (req_003 v3.04 D1).

    ``optimum_method`` and the catalog version travel with the numbers because a regret against
    a ``best_observed`` optimum is a weaker claim than one against an ``enumerated`` optimum.
    ``best_of_random`` is null when the equal-budget comparison could not be verified.
    """

    optimum: float | None
    optimum_method: str
    best_of_random: float | None
    best_of_random_strategy_version: str | None
    catalog_name: str
    catalog_version: int
    benchmark_id: int


class RunSeriesOut(_Record):
    """The v3.04 replay feed. ``total_points`` is the untinned count."""

    run: RunSummaryOut
    points: list[SeriesPointOut]
    total_points: int
    downsampled: bool
    #: Null when no benchmark covers this scenario — the chart draws no reference lines.
    reference: ScenarioReferenceOut | None


class AllocationPointOut(_Record):
    """Loads at one step, positional against ``AllocationSeriesOut.node_names``."""

    step_index: int
    loads: list[float]


class ExternalNodeOut(_Record):
    """One external node's capacities, from the circuit's current definition."""

    name: str
    load_factor: float
    load_safety_cap: float


class NodeCapacitiesOut(_Record):
    """Capacity marks and whether they may be drawn (req_003 v3.06 D1).

    ``matches_run`` is false when the circuit's external nodes no longer match the run's own
    list. The nodes are still sent so a client can show what changed, but the marks must not be
    drawn against a definition the run never saw.
    """

    nodes: list[ExternalNodeOut]
    matches_run: bool


class BestAllocationsOut(_Record):
    """Distinct allocations that reached the run's best cost.

    Computed server-side over every step: `is_best` marks only a strict improvement, so a trial
    that merely matches the best is not flagged and would be thinned away. A client counting
    from `points` would undercount badly.
    """

    cost: float
    allocations: list[list[float]]


class AllocationSeriesOut(_Record):
    """The v3.06 feed. Thinned with the same keep set as the cost series, so they align."""

    run_id: int
    node_names: list[str]
    points: list[AllocationPointOut]
    total_points: int
    downsampled: bool
    #: Null when the circuit no longer exists — distinct from "exists but drifted".
    capacities: NodeCapacitiesOut | None
    best: BestAllocationsOut | None


class BenchmarkHeaderOut(_Record):
    """Provenance for one harness invocation — what makes a plotted number re-checkable."""

    benchmark_id: int
    catalog_name: str
    catalog_version: int
    n_seeds: int
    bound_factor: float
    enumeration_cap: int
    notes: str | None
    created_at: datetime


class ComparisonCellOut(_Record):
    """One comparable population, aggregated across its seeds.

    The seven leading fields are the grouping keys. Pooling across any of them is the error
    the query layer exists to prevent, so they travel with every cell.
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


class RunPage(_Record):
    """A page of runs plus the unpaginated ``total`` describing it."""

    items: list[RunSummaryOut]
    total: int
    limit: int
    offset: int


class ComparisonResponse(_Record):
    """The v3.05 feed.

    ``available`` is false when no benchmark has ever run (spec D10) — an empty corpus is a
    state to render, so it is a 200 with a flag rather than a 404 or a bare ``null`` body that
    every client would have to special-case.
    """

    available: bool
    benchmark: BenchmarkHeaderOut | None
    cells: list[ComparisonCellOut]
