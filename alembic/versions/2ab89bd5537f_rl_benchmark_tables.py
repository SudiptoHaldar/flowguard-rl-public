"""rl benchmark tables

Revision ID: 2ab89bd5537f
Revises: 480cada04ea5
Create Date: 2026-08-17 04:38:22.905114

Creates ``rl_benchmarks`` and ``rl_benchmark_results`` (req_002 v2.06).

These exist for **provenance**, not for speed: the metrics they hold could be recomputed from
``rl_runs``/``rl_steps`` cheaply, but the catalog version and the method used to establish a
"true optimum" could not be reconstructed after the fact. Pinning them alongside each number
is what makes a reported figure re-checkable months later — the property whose absence
produced three wrong figures during v2.02/v2.07 development.

``optimum_method`` is ``text`` + a named CHECK rather than a native PostgreSQL ``ENUM``,
matching the v2.01/v2.02 pattern.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2ab89bd5537f'
down_revision: Union[str, Sequence[str], None] = '480cada04ea5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create rl_benchmarks and rl_benchmark_results."""
    op.create_table(
        "rl_benchmarks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("catalog_name", sa.Text(), nullable=False),
        sa.Column("catalog_version", sa.Integer(), nullable=False),
        sa.Column("n_seeds", sa.Integer(), nullable=False),
        sa.Column("bound_factor", sa.Double(), nullable=False),
        sa.Column("enumeration_cap", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "rl_benchmark_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "benchmark_id",
            sa.Integer(),
            sa.ForeignKey("rl_benchmarks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("rl_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("circuit_name", sa.Text(), nullable=False),
        sa.Column("total_load", sa.Double(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("strategy_version", sa.Text(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("allocation_mode", sa.Text(), nullable=False),
        sa.Column("observation_mode", sa.Text(), nullable=False),
        sa.Column("cold_start", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("first_cost", sa.Double(), nullable=False),
        sa.Column("best_cost", sa.Double(), nullable=False),
        sa.Column("improvement", sa.Double(), nullable=False),
        sa.Column("trials_used", sa.Integer(), nullable=False),
        sa.Column("convergence_step", sa.Integer(), nullable=False),
        sa.Column("optimum", sa.Double(), nullable=True),
        sa.Column("optimum_method", sa.Text(), nullable=False),
        sa.Column("regret", sa.Double(), nullable=True),
        sa.Column("safety_trials", sa.Integer(), nullable=False),
        sa.Column("safety_fraction", sa.Double(), nullable=False),
        sa.CheckConstraint(
            "optimum_method IN ('enumerated', 'best_observed', 'unknown')",
            name="ck_rl_benchmark_results_optimum_method",
        ),
    )


def downgrade() -> None:
    """Drop results first (it references the header)."""
    op.drop_table("rl_benchmark_results")
    op.drop_table("rl_benchmarks")
