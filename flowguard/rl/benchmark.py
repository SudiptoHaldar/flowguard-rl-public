"""Benchmark harness: reproducible strategy comparison with recorded provenance (v2.06).

**D0 exemption.** This module imports ``flowguard.circuits.store`` and reads load factors —
which every other module under ``flowguard/rl/`` is forbidden to do. The harness *measures*;
it does not compete. It must see the circuit in order to bound the search for a true optimum.
The obligation that comes with the exemption is that **nothing computed here reaches a
proposer**: strategies run through :func:`~flowguard.rl.driver.run_algo` exactly as they do
anywhere else, and the optimum is attached to results afterwards.

Why this module exists at all is epistemic rather than functional. It adds no capability. It
makes reported numbers re-checkable — the property whose absence produced three wrong figures
during v2.02/v2.07 development, each from measuring against whatever circuit object happened
to be convenient.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from flowguard.circuits import interface
from flowguard.circuits import store as circuits_store  # D0 — see the module docstring
from flowguard.settings import load_config

from . import config, store
from .driver import run_algo
from .proposers import BASELINES

#: Strategies whose output depends on the seed. Everything else is deterministic and is run
#: once per scenario — five identical runs would waste four and fabricate a dispersion of
#: zero that reads like a measurement.
STOCHASTIC_STRATEGIES = frozenset({"random_simplex"})

#: Reported separately and excluded from aggregates: its one-cycle disposal costs ~1e20 at
#: L=20000 and would swamp any median.
DEGENERATE_STRATEGIES = frozenset({"equal_split"})


@dataclass(frozen=True)
class Scenario:
    circuit: str
    total_load: float


@dataclass(frozen=True)
class Catalog:
    name: str
    version: int
    strategies: tuple[str, ...]
    scenarios: tuple[Scenario, ...]


@dataclass
class Optimum:
    """A best-known cost and, crucially, *how it was established*."""

    value: float | None
    method: str  # 'enumerated' | 'best_observed' | 'unknown'
    allocation: tuple[float, ...] | None = None


@dataclass
class ScenarioMetrics:
    strategy: str
    strategy_version: str | None
    seed: int | None
    run_id: int
    allocation_mode: str
    observation_mode: str
    cold_start: bool
    first_cost: float
    best_cost: float
    improvement: float
    trials_used: int
    convergence_step: int
    safety_trials: int
    safety_fraction: float
    extra: dict = field(default_factory=dict)


def load_catalog(path=None) -> Catalog:
    """Read the versioned scenario catalog."""
    raw = load_config(path or config.benchmark_scenario_catalog())
    scenarios = tuple(
        Scenario(entry["circuit"], float(load))
        for entry in raw["scenarios"]
        for load in entry["total_loads"]
    )
    strategies = tuple(raw["strategies"])
    unknown = [name for name in strategies if name not in BASELINES]
    if unknown:
        raise ValueError(
            f"catalog names unknown strategies {unknown}; "
            f"available: {', '.join(sorted(BASELINES))}"
        )
    return Catalog(raw["name"], int(raw["version"]), strategies, scenarios)


def enumeration_size(node_count: int, bound: int) -> int:
    """Number of integer allocations with ``sum <= bound``.

    ``C(bound + n, n)`` — the count of *valid* combinations, which is what the gate must use.
    Iterating ``range(bound+1)`` n times instead would visit ``(bound+1)**n``: 31.6M at n=4
    where only 1.4M are valid.
    """
    return math.comb(bound + node_count, node_count)


def find_optimum(session, circuit_name: str, total_load: float) -> Optimum:
    """Exact optimum by bounded enumeration, falling back to best-ever-observed.

    The bound is ``bound_factor * sum(external load_factors)``. Reading those factors is the
    D0 exemption in action — a *strategy* may never do this.
    """
    circuit = circuits_store.load_circuit(session, circuit_name)  # D0
    factors = [node.load_factor for node in circuit.ext_nodes()]
    node_count = len(factors)
    bound = int(min(float(total_load), config.benchmark_bound_factor() * sum(factors)))
    bound = max(bound, 1)

    if enumeration_size(node_count, bound) > config.benchmark_enumeration_cap():
        observed = store.best_observed_cost(session, circuit_name, total_load)
        if observed is None:
            return Optimum(None, "unknown")
        return Optimum(float(observed), "best_observed")

    best: tuple[float, tuple[float, ...]] | None = None

    def walk(index: int, remaining: int, current: list[int]) -> None:
        nonlocal best
        if index == node_count - 1:
            for value in range(remaining + 1):
                allocation = current + [value]
                if sum(allocation) == 0:
                    continue
                cost = interface.evaluate(circuit_name, total_load, allocation)
                if best is None or cost < best[0]:
                    best = (float(cost), tuple(float(v) for v in allocation))
            return
        for value in range(remaining + 1):
            walk(index + 1, remaining - value, current + [value])

    walk(0, bound, [])
    if best is None:  # only possible for a degenerate bound
        return Optimum(None, "unknown")
    return Optimum(best[0], "enumerated", best[1])


def evaluate_run(session, run_id: int) -> ScenarioMetrics:
    """Improvement-shaped metrics for one completed run.

    Safety incidence comes from :func:`store.load_audit`, not ``load_history`` — the latter
    strips the components outside ``enhanced`` mode, which is exactly what v2.01 D5 intends.
    The harness is permitted the audit path by D0; a proposer is not.
    """
    run = store.load_run(session, run_id)
    history = store.load_history(session, run_id)
    if not history:
        raise ValueError(f"run {run_id} recorded no trials")
    audited = store.load_audit(session, run_id)

    first = history[0].total_cost
    best = min(trial.total_cost for trial in history)
    # The FIRST trial reaching the best cost: with structural ties, later trials may match it.
    convergence = next(t.step_index for t in history if t.total_cost == best)
    unsafe = sum(1 for t in audited if t.audit is not None and t.audit.safety > 0)

    return ScenarioMetrics(
        strategy=run.strategy,
        strategy_version=run.strategy_version,
        seed=run.seed,
        run_id=run_id,
        allocation_mode=str(run.allocation_mode),
        observation_mode=str(run.observation_mode),
        cold_start=run.parent_run_id is None,
        first_cost=first,
        best_cost=best,
        improvement=(first - best) / first if first else 0.0,
        trials_used=len(history),
        convergence_step=convergence,
        safety_trials=unsafe,
        safety_fraction=unsafe / len(audited) if audited else 0.0,
    )


def seeds_for(strategy: str, n_seeds: int) -> list[int]:
    """Seeds to run: ``n_seeds`` for stochastic strategies, a single one otherwise."""
    return list(range(n_seeds)) if strategy in STOCHASTIC_STRATEGIES else [0]


def run_benchmark(
    session, *, catalog_path=None, n_seeds: int | None = None, notes: str | None = None
) -> int:
    """Execute the catalog and persist a header plus one row per (scenario, strategy, seed).

    Returns the benchmark id. The caller commits.
    """
    catalog = load_catalog(catalog_path)
    n_seeds = n_seeds or config.benchmark_n_seeds()

    missing = [
        scenario.circuit
        for scenario in catalog.scenarios
        if not _circuit_exists(session, scenario.circuit)
    ]
    if missing:
        raise ValueError(
            f"catalog names circuits that are not persisted: {sorted(set(missing))} — "
            "seed them with `python -m flowguard.circuits save <yaml>`"
        )

    header = store.create_benchmark(
        session,
        catalog_name=catalog.name,
        catalog_version=catalog.version,
        n_seeds=n_seeds,
        bound_factor=config.benchmark_bound_factor(),
        enumeration_cap=config.benchmark_enumeration_cap(),
        notes=notes,
    )

    for scenario in catalog.scenarios:
        # Computed ONCE per scenario and reused across every strategy and seed — the
        # enumeration is the expensive part (~1.4M evaluations at n=4).
        optimum = find_optimum(session, scenario.circuit, scenario.total_load)

        measured: list[ScenarioMetrics] = []
        for strategy in catalog.strategies:
            factory = BASELINES[strategy]
            for seed in seeds_for(strategy, n_seeds):
                result = run_algo(
                    scenario.circuit,
                    scenario.total_load,
                    factory(),
                    seed=seed,
                    session=session,
                )
                measured.append(evaluate_run(session, result.run_id))

        # When enumeration was skipped, the runs just made are themselves evidence.
        if optimum.value is None:
            observed = min((m.best_cost for m in measured), default=None)
            if observed is not None:
                optimum = Optimum(observed, "best_observed")

        for metrics in measured:
            store.add_benchmark_result(
                session,
                header.id,
                run_id=metrics.run_id,
                circuit_name=scenario.circuit,
                total_load=scenario.total_load,
                strategy=metrics.strategy,
                strategy_version=metrics.strategy_version,
                seed=metrics.seed,
                allocation_mode=metrics.allocation_mode,
                observation_mode=metrics.observation_mode,
                cold_start=metrics.cold_start,
                first_cost=metrics.first_cost,
                best_cost=metrics.best_cost,
                improvement=metrics.improvement,
                trials_used=metrics.trials_used,
                convergence_step=metrics.convergence_step,
                optimum=optimum.value,
                optimum_method=optimum.method,
                regret=(
                    metrics.best_cost - optimum.value
                    if optimum.value is not None
                    else None
                ),
                safety_trials=metrics.safety_trials,
                safety_fraction=metrics.safety_fraction,
            )

    return header.id


def summarise(results) -> list[dict]:
    """Aggregate result rows into one entry per (scenario, strategy, version, modes).

    Grouping is the whole discipline of this version: populations that are not comparable are
    never pooled — observation mode, allocation mode, strategy version and cold/warm start all
    partition the results (v2.01 D5/D6.6, v2.02 D3, D2.6.5). ``equal_split`` is kept as its
    own labelled row and flagged so callers can exclude it from any cross-strategy statistic.
    """
    grouped: dict[tuple, list] = {}
    for row in results:
        key = (
            row.circuit_name,
            row.total_load,
            row.strategy,
            row.strategy_version,
            row.allocation_mode,
            row.observation_mode,
            row.cold_start,
        )
        grouped.setdefault(key, []).append(row)

    summary = []
    for key, rows in grouped.items():
        costs = [row.best_cost for row in rows]
        summary.append(
            {
                "circuit": key[0],
                "total_load": key[1],
                "strategy": key[2],
                "strategy_version": key[3],
                "allocation_mode": key[4],
                "observation_mode": key[5],
                "cold_start": key[6],
                "runs": len(rows),
                "best_cost_median": statistics.median(costs),
                "best_cost_min": min(costs),
                "best_cost_max": max(costs),
                "improvement_median": statistics.median(
                    [row.improvement for row in rows]
                ),
                "convergence_step_median": statistics.median(
                    [row.convergence_step for row in rows]
                ),
                "optimum": rows[0].optimum,
                "optimum_method": rows[0].optimum_method,
                "regret_median": (
                    statistics.median([row.regret for row in rows])
                    if rows[0].regret is not None
                    else None
                ),
                "safety_fraction_median": statistics.median(
                    [row.safety_fraction for row in rows]
                ),
                "excluded_from_aggregates": key[2] in DEGENERATE_STRATEGIES,
            }
        )
    summary.sort(key=lambda entry: (entry["circuit"], entry["total_load"], entry["strategy"]))
    return summary


def _circuit_exists(session, circuit_name: str) -> bool:
    try:
        circuits_store.load_circuit(session, circuit_name)  # D0
        return True
    except ValueError:
        return False
