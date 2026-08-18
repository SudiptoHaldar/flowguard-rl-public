"""Opaque circuit interface for RL entities (req_001 v1.06).

The information-hiding boundary from the high-level plan §2: an optimizer sees only the
external-node names, hands over a total load plus one per-cycle load per external node
(positionally, in the stable definition order), and receives a single scalar cost back.
Circuit structure, factors, caps, and coefficients stay hidden; pass ``breakdown=True``
only when the per-category penalties are explicitly wanted.

Usage::

    from flowguard.circuits import interface
    names = interface.ext_nodes("C2")              # ['N1', 'N2']
    cost = interface.evaluate("C2", 60, [10, 10])  # 92.0

Circuits load from the database once per process and are cached (safe: the repository
is create-only, so stored circuits are immutable). If a circuit is deleted or re-seeded
while a process is running, call :func:`clear_cache` to force a re-read. Sessions are
managed internally and are read-only; errors propagate (``ValueError`` for unknown
circuits or wrong load counts, database errors as-is).
"""

from __future__ import annotations

from flowguard.data.database import get_session_factory

from . import store
from .model import Circuit, PenaltyBreakdown

_cache: dict[str, Circuit] = {}


def _get_circuit(name: str) -> Circuit:
    if name not in _cache:
        session = get_session_factory()()
        try:
            _cache[name] = store.load_circuit(session, name)
        finally:
            session.close()
    return _cache[name]


def clear_cache() -> None:
    """Forget all cached circuits; the next call re-reads from the database."""
    _cache.clear()


def ext_nodes(circuit_name: str) -> list[str]:
    """External-node names in the stable (definition) order — names only."""
    return [node.name for node in _get_circuit(circuit_name).ext_nodes()]


def evaluate(
    circuit_name: str, total_load, loads, breakdown: bool = False
) -> "float | PenaltyBreakdown":
    """Cost of assigning ``loads`` (positional, one per external node).

    Returns the bare total as a float; with ``breakdown=True``, the full
    :class:`PenaltyBreakdown`.
    """
    circuit = _get_circuit(circuit_name)
    externals = circuit.ext_nodes()
    if len(loads) != len(externals):
        raise ValueError(
            f"circuit '{circuit_name}' has {len(externals)} external nodes, "
            f"got {len(loads)} loads"
        )
    result = circuit.evaluate(
        total_load, {node.name: load for node, load in zip(externals, loads)}
    )
    return result if breakdown else float(result.total)
