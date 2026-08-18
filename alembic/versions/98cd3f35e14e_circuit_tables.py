"""circuit tables

Revision ID: 98cd3f35e14e
Revises: ba285a465674
Create Date: 2026-08-16 05:27:55.524478

Creates ``circuits`` and ``circuit_nodes`` (req_001 v1.02). NULL coefficient columns
mean "use the system default from config/circuit_defaults.yaml" — defaults are never
stored in rows. Attachment points for later revisions: the edges table (DAG topology,
req_001 v1.03) and split/merge parameters (v1.04) build on these tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '98cd3f35e14e'
down_revision: Union[str, Sequence[str], None] = 'ba285a465674'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create circuits and circuit_nodes."""
    op.create_table(
        "circuits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("delay_coefficients", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_circuits_name"),
        sa.CheckConstraint("name <> ''", name="ck_circuits_name_not_empty"),
    )
    op.create_table(
        "circuit_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "circuit_id",
            sa.Integer(),
            sa.ForeignKey("circuits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("load_factor", sa.Double(), nullable=False),
        sa.Column("load_safety_cap", sa.Double(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("external_position", sa.Integer(), nullable=True),
        sa.Column("overload_coefficients", postgresql.JSONB(), nullable=True),
        sa.Column("safety_coefficients", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("circuit_id", "name", name="uq_circuit_nodes_circuit_name"),
        sa.UniqueConstraint(
            "circuit_id", "position", name="uq_circuit_nodes_circuit_position"
        ),
        sa.UniqueConstraint(
            "circuit_id",
            "external_position",
            name="uq_circuit_nodes_circuit_external_position",
        ),
        sa.CheckConstraint(
            "load_factor > 0", name="ck_circuit_nodes_load_factor_positive"
        ),
        sa.CheckConstraint(
            "load_safety_cap >= load_factor", name="ck_circuit_nodes_cap_gte_factor"
        ),
    )


def downgrade() -> None:
    """Drop circuit_nodes, then circuits."""
    op.drop_table("circuit_nodes")
    op.drop_table("circuits")
