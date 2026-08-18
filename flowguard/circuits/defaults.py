"""System-default penalty polynomials (f1/f2/f3), loaded from config, never hard-coded.

The defaults live in ``config/circuit_defaults.yaml`` and are read lazily on first
access, then cached; :func:`reset` clears the cache so tests (or a config edit) can
force a re-read. Importing this module reads nothing.
"""

from __future__ import annotations

from pathlib import Path

from flowguard.settings import load_config

from .polynomial import Polynomial

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "circuit_defaults.yaml"

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        raw = load_config(_CONFIG_PATH)
        _cache = {
            "overload": Polynomial.from_list(raw["overload_penalty_coefficients"]),
            "safety": Polynomial.from_list(raw["safety_penalty_coefficients"]),
            "delay": Polynomial.from_list(raw["delay_penalty_coefficients"]),
        }
    return _cache


def default_overload() -> Polynomial:
    return _load()["overload"]


def default_safety() -> Polynomial:
    return _load()["safety"]


def default_delay() -> Polynomial:
    return _load()["delay"]


def reset() -> None:
    """Clear the cached defaults; the next access re-reads the config file."""
    global _cache
    _cache = None
