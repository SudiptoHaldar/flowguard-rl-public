"""rl allocation mode

Revision ID: 55de3d7ccbe5
Revises: dd53c67e6a11
Create Date: 2026-08-17 00:41:03.118742

Adds ``rl_runs.allocation_mode`` (req_002 v2.02 D3): ``integer`` (whole-number loads, and an
integral ``total_load``) or ``continuous`` (fractions allowed, subject to a minimum positive
allocation floor).

Why a column rather than a key in ``config_snapshot``: ``continuous`` is a strict superset of
``integer``, so a continuous run can never do worse than its integer counterpart. Pooling the
two in a comparison would overstate, which means v2.06 has to group by it — and grouping keys
belong in columns with a CHECK, not in schemaless JSONB. Same reasoning as ``observation_mode``.

``text`` + named CHECK rather than a native PostgreSQL ``ENUM``, matching the v2.01 pattern:
vocabularies here still grow, and ``ALTER TYPE ... ADD VALUE`` is the one migration Alembic
will not autogenerate. Existing rows take the ``integer`` server default.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '55de3d7ccbe5'
down_revision: Union[str, Sequence[str], None] = 'dd53c67e6a11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add rl_runs.allocation_mode with its CHECK constraint."""
    op.add_column(
        "rl_runs",
        sa.Column(
            "allocation_mode",
            sa.Text(),
            server_default="integer",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_rl_runs_allocation_mode",
        "rl_runs",
        "allocation_mode IN ('integer', 'continuous')",
    )


def downgrade() -> None:
    """Drop the constraint, then the column."""
    op.drop_constraint("ck_rl_runs_allocation_mode", "rl_runs", type_="check")
    op.drop_column("rl_runs", "allocation_mode")
