"""Persistence for circuit definitions (req_001 v1.02).

Repository contract: every function takes an open SQLAlchemy ``Session`` and never
commits — the caller owns the transaction. ``save_circuit`` is create-only (update and
upsert are deferred with the mutation-semantics question). A NULL coefficients column
means "use the system default from ``config/circuit_defaults.yaml``" — the exact DB
analogue of the v1.01 ``None``-override semantics; defaults are never copied into rows.

Topology seam: the edges table (req_001 v1.03) and split/merge parameters (v1.04)
attach here and in the corresponding Alembic revisions.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowguard.data.database import Base

from .model import Circuit, Edge, Node
from .polynomial import Polynomial


class CircuitRow(Base):
    __tablename__ = "circuits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    delay_coefficients: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    nodes: Mapped[list["CircuitNodeRow"]] = relationship(
        cascade="all, delete-orphan",
        order_by="CircuitNodeRow.position",
        back_populates="circuit",
    )
    edges: Mapped[list["CircuitEdgeRow"]] = relationship(
        cascade="all, delete-orphan",
        order_by="CircuitEdgeRow.id",
        back_populates="circuit",
    )

    __table_args__ = (CheckConstraint("name <> ''", name="ck_circuits_name_not_empty"),)


class CircuitNodeRow(Base):
    __tablename__ = "circuit_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    circuit_id: Mapped[int] = mapped_column(
        ForeignKey("circuits.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    load_factor: Mapped[float] = mapped_column(Double)
    load_safety_cap: Mapped[float] = mapped_column(Double)
    position: Mapped[int] = mapped_column(Integer)
    external_position: Mapped[int | None] = mapped_column(Integer)
    overload_coefficients: Mapped[list | None] = mapped_column(JSONB)
    safety_coefficients: Mapped[list | None] = mapped_column(JSONB)

    circuit: Mapped[CircuitRow] = relationship(back_populates="nodes")

    __table_args__ = (
        UniqueConstraint("circuit_id", "name", name="uq_circuit_nodes_circuit_name"),
        UniqueConstraint(
            "circuit_id", "position", name="uq_circuit_nodes_circuit_position"
        ),
        UniqueConstraint(
            "circuit_id",
            "external_position",
            name="uq_circuit_nodes_circuit_external_position",
        ),
        CheckConstraint("load_factor > 0", name="ck_circuit_nodes_load_factor_positive"),
        CheckConstraint(
            "load_safety_cap >= load_factor", name="ck_circuit_nodes_cap_gte_factor"
        ),
    )


class CircuitEdgeRow(Base):
    __tablename__ = "circuit_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    circuit_id: Mapped[int] = mapped_column(
        ForeignKey("circuits.id", ondelete="CASCADE")
    )
    from_node_id: Mapped[int] = mapped_column(
        ForeignKey("circuit_nodes.id", ondelete="CASCADE")
    )
    to_node_id: Mapped[int] = mapped_column(
        ForeignKey("circuit_nodes.id", ondelete="CASCADE")
    )
    weight: Mapped[float] = mapped_column(Double)

    circuit: Mapped[CircuitRow] = relationship(back_populates="edges")
    from_node: Mapped[CircuitNodeRow] = relationship(foreign_keys=[from_node_id])
    to_node: Mapped[CircuitNodeRow] = relationship(foreign_keys=[to_node_id])

    __table_args__ = (
        UniqueConstraint(
            "circuit_id", "from_node_id", "to_node_id", name="uq_circuit_edges_edge"
        ),
        CheckConstraint("weight > 0", name="ck_circuit_edges_weight_positive"),
        CheckConstraint("weight <= 1", name="ck_circuit_edges_weight_max"),
    )


def _as_coefficients(polynomial: Polynomial | None) -> list | None:
    return polynomial.as_list() if polynomial is not None else None


def _as_override(coefficients: list | None) -> Polynomial | None:
    return Polynomial.from_list(coefficients) if coefficients is not None else None


def save_circuit(session, circuit: Circuit) -> int:
    """Persist a new circuit; returns its id. Create-only; the caller commits."""
    if not isinstance(circuit, Circuit):
        raise ValueError(f"save_circuit expects a Circuit, got {type(circuit).__name__}")
    existing = session.scalar(
        select(CircuitRow.id).where(CircuitRow.name == circuit.name)
    )
    if existing is not None:
        raise ValueError(f"circuit '{circuit.name}' already exists")
    external_positions = {
        node.name: index for index, node in enumerate(circuit.ext_nodes())
    }
    node_rows = {}
    for position, node in enumerate(circuit.nodes()):
        node_rows[node.name] = CircuitNodeRow(
            name=node.name,
            load_factor=node.load_factor,
            load_safety_cap=node.load_safety_cap,
            position=position,
            external_position=external_positions.get(node.name),
            overload_coefficients=_as_coefficients(node.overload_override),
            safety_coefficients=_as_coefficients(node.safety_override),
        )
    row = CircuitRow(
        name=circuit.name,
        delay_coefficients=_as_coefficients(circuit.delay_override),
        nodes=list(node_rows.values()),
        edges=[
            CircuitEdgeRow(
                from_node=node_rows[edge.source],
                to_node=node_rows[edge.target],
                weight=edge.weight,
            )
            for edge in circuit.edges()
        ],
    )
    session.add(row)
    session.flush()
    return row.id


def _get_row(session, name: str) -> CircuitRow:
    row = session.scalar(select(CircuitRow).where(CircuitRow.name == name))
    if row is None:
        raise ValueError(f"circuit '{name}' does not exist")
    return row


def load_circuit(session, name: str) -> Circuit:
    """Rebuild the domain Circuit stored under ``name``.

    Ordering contract: ``external_nodes`` is rebuilt in ``external_position`` order —
    the definition order at save time — so ``ext_nodes()`` is stable across sessions
    and processes by construction.
    """
    row = _get_row(session, name)
    nodes = [
        Node(
            name=node_row.name,
            load_factor=node_row.load_factor,
            load_safety_cap=node_row.load_safety_cap,
            overload_override=_as_override(node_row.overload_coefficients),
            safety_override=_as_override(node_row.safety_coefficients),
        )
        for node_row in row.nodes  # relationship orders by position
    ]
    external_nodes = [
        node_row.name
        for node_row in sorted(
            (nr for nr in row.nodes if nr.external_position is not None),
            key=lambda nr: nr.external_position,
        )
    ]
    node_names = {node_row.id: node_row.name for node_row in row.nodes}
    edges = [
        Edge(
            source=node_names[edge_row.from_node_id],
            target=node_names[edge_row.to_node_id],
            weight=edge_row.weight,
        )
        for edge_row in row.edges  # relationship orders by id (insert order)
    ]
    return Circuit(
        name=row.name,
        nodes=nodes,
        external_nodes=external_nodes,
        delay_override=_as_override(row.delay_coefficients),
        edges=edges,
    )


def list_circuit_names(session) -> list[str]:
    return list(session.scalars(select(CircuitRow.name).order_by(CircuitRow.name)))


def delete_circuit(session, name: str) -> None:
    """Delete the named circuit (nodes cascade). The caller commits."""
    session.delete(_get_row(session, name))
    session.flush()
