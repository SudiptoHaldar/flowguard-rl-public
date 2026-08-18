"""Circuits component: nodes with penalty functions behind an ext_nodes() surface.

See ``model.py`` for the domain model and the seam where DAG topology (v1.03) and
split/merge semantics (v1.04) will attach.
"""

from .model import Circuit, Edge, Node, PenaltyBreakdown
from .polynomial import Polynomial

__all__ = ["Circuit", "Edge", "Node", "PenaltyBreakdown", "Polynomial"]
