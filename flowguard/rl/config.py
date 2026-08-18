"""Tunables for the RL element, loaded from config — never hard-coded (req_002 v2.01).

Mirrors :mod:`flowguard.circuits.defaults`: the values live in ``config/rl_defaults.yaml``,
are read lazily on first access and then cached, and :func:`reset` clears the cache so tests
(or a config edit) can force a re-read. Importing this module reads nothing.

Validation happens **at load time**, not at first use (spec D3): a bad
``commit_every_n_steps`` should fail when the config is read, not thousands of trials into a
run.
"""

from __future__ import annotations

from pathlib import Path

from flowguard.settings import load_config

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "rl_defaults.yaml"

_cache: dict | None = None


def _positive_int(raw, key: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError(f"{key} must be an integer >= 1, got {raw!r}")
    return raw


def _positive_number(raw, key: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        raise ValueError(f"{key} must be a number > 0, got {raw!r}")
    return float(raw)


def _load() -> dict:
    global _cache
    if _cache is None:
        raw = load_config(_CONFIG_PATH)
        recorder = raw.get("recorder", {})
        run = raw.get("run", {})
        proposers = raw.get("proposers", {})
        benchmark = raw.get("benchmark", {})
        _cache = {
            "commit_every_n_steps": _positive_int(
                recorder.get("commit_every_n_steps"), "commit_every_n_steps"
            ),
            "stale_run_threshold_seconds": _positive_int(
                recorder.get("stale_run_threshold_seconds"),
                "stale_run_threshold_seconds",
            ),
            "budget_k": _positive_number(run.get("budget_k"), "budget_k"),
            "budget_floor": _positive_int(run.get("budget_floor"), "budget_floor"),
            "min_allocation": _positive_number(
                run.get("min_allocation"), "min_allocation"
            ),
            "random_simplex_concentration": _positive_number(
                proposers.get("random_simplex", {}).get("concentration"),
                "random_simplex.concentration",
            ),
            "hill_climb_initial_step_fraction": _positive_number(
                proposers.get("hill_climb", {}).get("initial_step_fraction"),
                "hill_climb.initial_step_fraction",
            ),
            "release_sweep_spacing": proposers.get("release_sweep", {}).get("spacing"),
            "benchmark_n_seeds": _positive_int(
                benchmark.get("n_seeds"), "benchmark.n_seeds"
            ),
            "benchmark_bound_factor": _positive_number(
                benchmark.get("bound_factor"), "benchmark.bound_factor"
            ),
            "benchmark_enumeration_cap": _positive_int(
                benchmark.get("enumeration_cap"), "benchmark.enumeration_cap"
            ),
            "benchmark_scenario_catalog": benchmark.get("scenario_catalog"),
        }
        if _cache["benchmark_bound_factor"] < 1.7:
            raise ValueError(
                "benchmark.bound_factor must be >= 1.7 — C2's optimum at L=20000 has a "
                "sum/factor-sum ratio of 1.67, so a tighter bound would miss true optima; "
                f"got {_cache['benchmark_bound_factor']}"
            )
        if not _cache["benchmark_scenario_catalog"]:
            raise ValueError("benchmark.scenario_catalog must be set")
        if _cache["release_sweep_spacing"] != "log":
            raise ValueError(
                "release_sweep.spacing must be 'log' — z = ceil(L/S) varies as 1/S, so "
                f"linear spacing wastes the budget; got {_cache['release_sweep_spacing']!r}"
            )
    return _cache


def commit_every_n_steps() -> int:
    """Trials buffered before the recorder commits; 1 means per-step commit."""
    return _load()["commit_every_n_steps"]


def stale_run_threshold_seconds() -> int:
    """Idle time after which a still-``running`` run is presumed dead."""
    return _load()["stale_run_threshold_seconds"]


def budget_k() -> float:
    """Coefficient in ``budget = max(floor, ceil(k * n * log2(total_load)))``."""
    return _load()["budget_k"]


def budget_floor() -> int:
    """Minimum trial budget, so population methods get several generations."""
    return _load()["budget_floor"]


def min_allocation() -> float:
    """Smallest permitted positive load in ``continuous`` mode (a floor, not a grid)."""
    return _load()["min_allocation"]


def random_simplex_concentration() -> float:
    """Dirichlet alpha for the random-simplex baseline (1.0 = uniform)."""
    return _load()["random_simplex_concentration"]


def hill_climb_initial_step_fraction() -> float:
    """First hill-climb step as a fraction of the total load, before halving."""
    return _load()["hill_climb_initial_step_fraction"]


def benchmark_n_seeds() -> int:
    """Seeds per *stochastic* strategy; deterministic ones always run once."""
    return _load()["benchmark_n_seeds"]


def benchmark_bound_factor() -> float:
    """Optimum search enumerates ``sum <= factor * sum(external load_factors)``."""
    return _load()["benchmark_bound_factor"]


def benchmark_enumeration_cap() -> int:
    """Skip enumeration when ``C(bound + n, n)`` exceeds this; fall back to best-observed."""
    return _load()["benchmark_enumeration_cap"]


def benchmark_scenario_catalog() -> Path:
    """Path to the versioned scenario catalog, relative to the repo root."""
    return _CONFIG_PATH.parents[1] / _load()["benchmark_scenario_catalog"]


def reset() -> None:
    """Clear the cached config; the next access re-reads the file."""
    global _cache
    _cache = None
