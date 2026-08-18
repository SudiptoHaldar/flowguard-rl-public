"""Tunables for the chart HTTP API, loaded from config — never hard-coded (req_003 v3.02).

Mirrors :mod:`flowguard.rl.config`: the values live in ``config/chart_defaults.yaml``, are read
lazily on first access and then cached, and :func:`reset` clears the cache so tests (or a config
edit) can force a re-read. **Importing this module reads nothing.**

That laziness is load-bearing here, not incidental. Route decorators in
:mod:`flowguard.data.routers` are evaluated at import time, so a ceiling pulled into a
``Query(le=...)`` default would make importing the router read this YAML — the same class of
import-time side effect the lazy-DB contract forbids. The routers call these accessors *inside*
their handlers instead.

Validation happens at load time: an incoherent pair (a ceiling below the default) should fail
when the config is read, not on the first request that happens to exercise it.
"""

from __future__ import annotations

from pathlib import Path

from flowguard.settings import load_config

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "chart_defaults.yaml"

_cache: dict | None = None


def _positive_int(raw, key: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError(f"{key} must be an integer >= 1, got {raw!r}")
    return raw


def _load() -> dict:
    global _cache
    if _cache is None:
        raw = load_config(_CONFIG_PATH)
        series = raw.get("series", {})
        runs = raw.get("runs", {})
        _cache = {
            "default_max_points": _positive_int(
                series.get("default_max_points"), "series.default_max_points"
            ),
            "max_points_ceiling": _positive_int(
                series.get("max_points_ceiling"), "series.max_points_ceiling"
            ),
            "default_run_limit": _positive_int(
                runs.get("default_limit"), "runs.default_limit"
            ),
            "max_run_limit": _positive_int(runs.get("max_limit"), "runs.max_limit"),
        }
        if _cache["max_points_ceiling"] < _cache["default_max_points"]:
            raise ValueError(
                "series.max_points_ceiling must be >= series.default_max_points — a ceiling "
                "below the default would reject the server's own default; got "
                f"{_cache['max_points_ceiling']} < {_cache['default_max_points']}"
            )
        if _cache["max_run_limit"] < _cache["default_run_limit"]:
            raise ValueError(
                "runs.max_limit must be >= runs.default_limit; got "
                f"{_cache['max_run_limit']} < {_cache['default_run_limit']}"
            )
    return _cache


def default_max_points() -> int:
    """Series points returned when the client asks for no particular number."""
    return _load()["default_max_points"]


def max_points_ceiling() -> int:
    """Largest ``max_points`` a client may request; there is no unlimited option."""
    return _load()["max_points_ceiling"]


def default_run_limit() -> int:
    """Page size for ``/runs`` when the client sends no ``limit``."""
    return _load()["default_run_limit"]


def max_run_limit() -> int:
    """Largest ``limit`` a client may request for ``/runs``."""
    return _load()["max_run_limit"]


def reset() -> None:
    """Clear the cached config; the next access re-reads the file."""
    global _cache
    _cache = None
