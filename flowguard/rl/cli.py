"""Command-line interface for RL algo-runs (req_002 v2.07).

Usage (from the repo root, venv active)::

    python -m flowguard.rl optimize C4 10000 --strategy hill_climb --seed 1
    python -m flowguard.rl runs --circuit C4 --limit 20
    python -m flowguard.rl show 422 --trace

Every command accepts ``--json`` for machine-readable output.

``runs`` also sweeps runs abandoned by a crashed process. That sweep is v2.01 D6.3's lazy
reconciliation, which until now had no trigger at all — ``store.reconcile_stale_runs`` was
called by nothing but tests, so a run killed mid-flight stayed ``running`` forever.
``optimize`` deliberately does **not** sweep, keeping that write off the path used
programmatically.

Structure mirrors ``flowguard/circuits/cli.py``: ``cmd_*`` functions take an open ``Session``
and **return** a string, while ``main`` owns argparse, the session lifecycle, printing,
commits and exit codes. That is what makes the commands directly testable.
"""

from __future__ import annotations

import argparse
import json
import math
import sys

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from flowguard.data.database import get_session_factory
from flowguard.settings import MissingEnvVarError

from . import benchmark, config, store
from .driver import run_algo
from .proposers import BASELINES
from .types import AllocationMode, ObservationMode

ENHANCED_WARNING = (
    "warning: enhanced runs expose the cost breakdown to the strategy and are NOT "
    "comparable with opaque runs — never pool them in a comparison"
)


def _strategy(name: str):
    """Instantiate a baseline by name, listing the valid ones when it is unknown."""
    factory = BASELINES.get(name)
    if factory is None:
        raise ValueError(
            f"unknown strategy '{name}'; available: {', '.join(sorted(BASELINES))}"
        )
    return factory()


def _fmt_cost(value) -> str:
    if value is None:
        return "-"
    return f"{value:.4g}" if abs(value) >= 1e6 else f"{value:.4f}"


def _fmt_allocation(names, allocation) -> str:
    """Label each load with its node name — a bare positional array is anonymous."""
    if not allocation:
        return "-"
    return "  ".join(f"{name}={value:g}" for name, value in zip(names, allocation))


def _trial_counts(session, run_ids) -> dict[int, int]:
    """Trial count per run in ONE query.

    Deliberately not ``len(run.steps)``: that relationship is lazy, so counting per row
    would issue a query per run (N+1).
    """
    if not run_ids:
        return {}
    stmt = (
        select(store.StepRow.run_id, func.count())
        .where(store.StepRow.run_id.in_(list(run_ids)))
        .group_by(store.StepRow.run_id)
    )
    return {run_id: count for run_id, count in session.execute(stmt).all()}


def cmd_optimize(
    session,
    circuit_name: str,
    total_load: float,
    *,
    strategy: str = "hill_climb",
    budget: int | None = None,
    seed: int | None = None,
    continuous: bool = False,
    enhanced: bool = False,
    as_json: bool = False,
) -> str:
    """Run one algo-run to completion and report its result."""
    proposer = _strategy(strategy)  # raises before any database use
    result = run_algo(
        circuit_name,
        total_load,
        proposer,
        budget=budget,
        seed=seed,
        allocation_mode=(
            AllocationMode.CONTINUOUS if continuous else AllocationMode.INTEGER
        ),
        observation_mode=(
            ObservationMode.ENHANCED if enhanced else ObservationMode.OPAQUE
        ),
        session=session,
    )
    run = store.load_run(session, result.run_id)
    names = list(run.external_node_names)
    payload = {
        "run_id": run.id,
        "circuit": run.circuit_name,
        "external_node_names": names,
        "total_load": run.total_load,
        "strategy": run.strategy,
        "strategy_version": run.strategy_version,
        "allocation_mode": str(run.allocation_mode),
        "observation_mode": str(run.observation_mode),
        "seed": run.seed,
        "budget": run.budget,
        "trials_used": result.trials_used,
        "best_cost": result.best_cost,
        "best_allocation": (
            list(result.best_allocation) if result.best_allocation else None
        ),
        "termination_reason": str(result.termination_reason),
    }
    if as_json:
        return json.dumps(payload, indent=2)

    version = f" v{run.strategy_version}" if run.strategy_version else ""
    return "\n".join(
        [
            f"run_id           : {run.id}",
            f"circuit          : {run.circuit_name}  ({', '.join(names)})",
            f"total_load       : {run.total_load:g}",
            f"strategy         : {run.strategy}{version}",
            f"modes            : {run.allocation_mode} / {run.observation_mode}",
            f"budget           : {run.budget}",
            f"trials_used      : {result.trials_used}",
            f"best_cost        : {_fmt_cost(result.best_cost)}",
            f"best_allocation  : {_fmt_allocation(names, result.best_allocation)}",
            f"termination      : {result.termination_reason}",
        ]
    )


def cmd_runs(
    session,
    *,
    circuit: str | None = None,
    status: str | None = None,
    limit: int = 20,
    as_json: bool = False,
) -> str:
    """List algo-runs, newest first, after sweeping any that were abandoned.

    The sweep and the listing share one transaction — the pending UPDATE is visible to the
    SELECT that follows it, so no intermediate commit is needed. ``main`` commits.
    """
    swept = store.reconcile_stale_runs(session, config.stale_run_threshold_seconds())
    rows = store.list_runs(session, circuit_name=circuit, status=status)[:limit]
    counts = _trial_counts(session, [row.id for row in rows])

    if as_json:
        return json.dumps(
            {
                "swept": swept,
                "runs": [
                    {
                        "run_id": row.id,
                        "circuit": row.circuit_name,
                        "total_load": row.total_load,
                        "strategy": row.strategy,
                        "strategy_version": row.strategy_version,
                        "allocation_mode": str(row.allocation_mode),
                        "observation_mode": str(row.observation_mode),
                        "trials": counts.get(row.id, 0),
                        "best_cost": row.best_cost,
                        "status": str(row.status),
                        "termination_reason": (
                            str(row.termination_reason) if row.termination_reason else None
                        ),
                    }
                    for row in rows
                ],
            },
            indent=2,
        )

    lines = []
    if swept:
        lines.append(f"swept {swept} stale run(s) to abandoned")
    if not rows:
        lines.append("no runs")
        return "\n".join(lines)
    lines.append(
        f"{'id':>6}  {'circuit':<12} {'total_load':>11}  {'strategy':<18} "
        f"{'modes':<20} {'trials':>7}  {'best_cost':>13}  status"
    )
    for row in rows:
        version = f" v{row.strategy_version}" if row.strategy_version else ""
        modes = f"{row.allocation_mode}/{row.observation_mode}"
        lines.append(
            f"{row.id:>6}  {row.circuit_name:<12} {row.total_load:>11g}  "
            f"{row.strategy + version:<18} {modes:<20} {counts.get(row.id, 0):>7}  "
            f"{_fmt_cost(row.best_cost):>13}  {row.status}"
        )
    return "\n".join(lines)


def cmd_show(session, run_id: int, *, trace: bool = False, as_json: bool = False) -> str:
    """Show one run's header and, with ``trace``, its stored trial-by-trial trajectory.

    There is no re-execution: strict determinism was withdrawn (v2.02 D5), so replaying the
    allocations could not be described as reproducing the run. This prints what was recorded.
    """
    run = store.load_run(session, run_id)
    names = list(run.external_node_names)

    steps = []
    if trace:
        best = None
        for trial in store.load_history(session, run_id):
            released = sum(trial.allocation)
            # `Trial` carries no is_best flag, so recompute it as a running minimum — which
            # is exactly what the is_best column records.
            is_best = best is None or trial.total_cost < best
            if is_best:
                best = trial.total_cost
            steps.append(
                {
                    "step_index": trial.step_index,
                    "allocation": list(trial.allocation),
                    "release_sum": released,
                    "cycles": (
                        math.ceil(run.total_load / released) if released > 0 else None
                    ),
                    "total_cost": trial.total_cost,
                    "is_best": is_best,
                }
            )

    if as_json:
        payload = {
            "run_id": run.id,
            "circuit": run.circuit_name,
            "external_node_names": names,
            "total_load": run.total_load,
            "strategy": run.strategy,
            "strategy_version": run.strategy_version,
            "allocation_mode": str(run.allocation_mode),
            "observation_mode": str(run.observation_mode),
            "seed": run.seed,
            "budget": run.budget,
            "status": str(run.status),
            "termination_reason": (
                str(run.termination_reason) if run.termination_reason else None
            ),
            "best_cost": run.best_cost,
            "best_allocation": (
                list(run.best_allocation) if run.best_allocation else None
            ),
        }
        if trace:
            payload["trace"] = steps
        return json.dumps(payload, indent=2)

    version = f" v{run.strategy_version}" if run.strategy_version else ""
    lines = [
        f"run_id           : {run.id}",
        f"circuit          : {run.circuit_name}  ({', '.join(names)})",
        f"total_load       : {run.total_load:g}",
        f"strategy         : {run.strategy}{version}",
        f"modes            : {run.allocation_mode} / {run.observation_mode}",
        f"seed             : {run.seed}",
        f"budget           : {run.budget}",
        f"status           : {run.status}"
        + (f" / {run.termination_reason}" if run.termination_reason else ""),
        f"best_cost        : {_fmt_cost(run.best_cost)}",
        f"best_allocation  : {_fmt_allocation(names, run.best_allocation)}",
    ]
    if trace:
        lines.append("")
        lines.append(
            f"{'step':>5}  {'allocation':<26} {'sum':>9} {'z':>6}  {'cost':>14}"
        )
        for step in steps:
            allocation = "[" + ", ".join(f"{v:g}" for v in step["allocation"]) + "]"
            cycles = step["cycles"] if step["cycles"] is not None else "-"
            marker = "  *best" if step["is_best"] else ""
            lines.append(
                f"{step['step_index']:>5}  {allocation:<26} "
                f"{step['release_sum']:>9g} {cycles:>6}  "
                f"{_fmt_cost(step['total_cost']):>14}{marker}"
            )
    return "\n".join(lines)


def cmd_benchmark(
    session,
    *,
    catalog: str | None = None,
    n_seeds: int | None = None,
    notes: str | None = None,
    as_json: bool = False,
) -> str:
    """Run the scenario catalog and report the comparison.

    Deliberately absent from v2.07 (which excluded `compare`) because v2.06 owns tabulation
    and its pooling rules; this is that command arriving in its proper home.
    """
    benchmark_id = benchmark.run_benchmark(
        session, catalog_path=catalog, n_seeds=n_seeds, notes=notes
    )
    rows = store.load_benchmark_results(session, benchmark_id)
    summary = benchmark.summarise(rows)

    if as_json:
        return json.dumps({"benchmark_id": benchmark_id, "summary": summary}, indent=2)

    lines = [f"benchmark {benchmark_id}  ({len(rows)} runs)"]
    lines.append(
        f"{'circuit':<8} {'load':>8}  {'strategy':<18} {'runs':>5} {'best(med)':>14} "
        f"{'regret':>12} {'conv':>6} {'safety':>7}  optimum (method)"
    )
    for entry in summary:
        marker = "  *" if entry["excluded_from_aggregates"] else ""
        regret = (
            _fmt_cost(entry["regret_median"])
            if entry["regret_median"] is not None
            else "-"
        )
        optimum = (
            f"{_fmt_cost(entry['optimum'])} ({entry['optimum_method']})"
            if entry["optimum"] is not None
            else f"- ({entry['optimum_method']})"
        )
        lines.append(
            f"{entry['circuit']:<8} {entry['total_load']:>8g}  {entry['strategy']:<18} "
            f"{entry['runs']:>5} {_fmt_cost(entry['best_cost_median']):>14} "
            f"{regret:>12} {entry['convergence_step_median']:>6.0f} "
            f"{entry['safety_fraction_median']:>7.2f}  {optimum}{marker}"
        )
    lines.append("")
    lines.append("* excluded from cross-strategy aggregates (degenerate reference)")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m flowguard.rl",
        description="Run and inspect RL algo-runs over persisted circuits.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    optimize = sub.add_parser(
        "optimize", help="run an optimisation, persisting every trial"
    )
    optimize.add_argument("circuit")
    optimize.add_argument("total_load", type=float)
    optimize.add_argument(
        "--strategy",
        default="hill_climb",
        help=f"one of: {', '.join(sorted(BASELINES))} (default: hill_climb)",
    )
    optimize.add_argument("--budget", type=int, help="trials; default is computed")
    optimize.add_argument("--seed", type=int)
    optimize.add_argument(
        "--continuous", action="store_true", help="allow fractional loads"
    )
    optimize.add_argument(
        "--enhanced",
        action="store_true",
        help="expose the cost breakdown (NOT comparable with opaque runs)",
    )
    optimize.add_argument("--json", action="store_true")

    runs = sub.add_parser("runs", help="list algo-runs; also sweeps abandoned ones")
    runs.add_argument("--circuit")
    runs.add_argument("--status", help="running | completed | failed | abandoned")
    runs.add_argument("--limit", type=int, default=20)
    runs.add_argument("--json", action="store_true")

    show = sub.add_parser("show", help="show one run, optionally with its trace")
    show.add_argument("run_id", type=int)
    show.add_argument("--trace", action="store_true", help="print every trial")
    show.add_argument("--json", action="store_true")

    bench = sub.add_parser(
        "benchmark", help="run the scenario catalog and compare the strategies"
    )
    bench.add_argument("--catalog", help="path to a scenario catalog YAML")
    bench.add_argument("--n-seeds", type=int, dest="n_seeds")
    bench.add_argument("--notes", help="free text recorded with the benchmark")
    bench.add_argument("--json", action="store_true")
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)  # argparse errors need no DB
    if getattr(args, "enhanced", False):
        print(ENHANCED_WARNING, file=sys.stderr)
    try:
        session = get_session_factory()()
    except (MissingEnvVarError, OperationalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        if args.command == "optimize":
            # RunRecorder owns its own commits, so main must not commit again here.
            output = cmd_optimize(
                session,
                args.circuit,
                args.total_load,
                strategy=args.strategy,
                budget=args.budget,
                seed=args.seed,
                continuous=args.continuous,
                enhanced=args.enhanced,
                as_json=args.json,
            )
        elif args.command == "runs":
            output = cmd_runs(
                session,
                circuit=args.circuit,
                status=args.status,
                limit=args.limit,
                as_json=args.json,
            )
            session.commit()  # persist the stale-run sweep
        elif args.command == "benchmark":
            output = cmd_benchmark(
                session,
                catalog=args.catalog,
                n_seeds=args.n_seeds,
                notes=args.notes,
                as_json=args.json,
            )
            session.commit()  # persist the benchmark header and result rows
        else:
            output = cmd_show(
                session, args.run_id, trace=args.trace, as_json=args.json
            )
        print(output)
        return 0
    except (ValueError, MissingEnvVarError, OperationalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()
