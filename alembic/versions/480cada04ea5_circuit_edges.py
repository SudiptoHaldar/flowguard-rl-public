"""circuit edges

Revision ID: 480cada04ea5
Revises: 55de3d7ccbe5
Create Date: 2026-08-17 02:43:09.942699

Creates ``circuit_edges`` (req_001 v1.03) — the DAG topology attachment point left by
revision ``98cd3f35e14e``. An edge sends ``weight`` (fraction, (0, 1]) of its source
node's carried load to its target; per-source weights sum to 1 and graph-level rules
(acyclicity, externals-have-no-incoming) are enforced by the domain model, not the DB.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '480cada04ea5'
down_revision: Union[str, Sequence[str], None] = '55de3d7ccbe5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create circuit_edges."""
    op.create_table(
        "circuit_edges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "circuit_id",
            sa.Integer(),
            sa.ForeignKey("circuits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_node_id",
            sa.Integer(),
            sa.ForeignKey("circuit_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_node_id",
            sa.Integer(),
            sa.ForeignKey("circuit_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weight", sa.Double(), nullable=False),
        sa.UniqueConstraint(
            "circuit_id", "from_node_id", "to_node_id", name="uq_circuit_edges_edge"
        ),
        sa.CheckConstraint("weight > 0", name="ck_circuit_edges_weight_positive"),
        sa.CheckConstraint("weight <= 1", name="ck_circuit_edges_weight_max"),
    )


def downgrade() -> None:
    """Drop circuit_edges."""
    op.drop_table("circuit_edges")
