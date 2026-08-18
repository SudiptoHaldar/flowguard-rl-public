"""rl run tables

Revision ID: dd53c67e6a11
Revises: 98cd3f35e14e
Create Date: 2026-08-16 19:58:12.402117

Creates ``rl_runs`` and ``rl_steps`` plus the ``v_rl_step_loads`` view (req_002 v2.01).

Allocations and external-node names are native ``double precision[]`` / ``text[]`` rather
than JSONB: they are the columns analytics filters and aggregates per node. JSONB is kept
only for ``config_snapshot``, which is schemaless and always read whole.

The view expands an allocation array into one row per node — ``(run_id, step_index,
position, node_name, load, total_cost)`` — so charting and the v2.06 benchmark harness can
query per-node data as if it were normalised, without multiplying the write path by the node
count. ``position`` is 1-based (PostgreSQL arrays and ``WITH ORDINALITY`` both are), while
``rl_steps.step_index`` is 0-based; different axes, deliberately not reconciled.

Status/mode vocabularies are ``text`` + named CHECK constraints, not native PG ``ENUM``
types: the termination-reason vocabulary grows as req_002 v2.02 adds stopping rules, and
``ALTER TYPE ... ADD VALUE`` is the one migration Alembic does not autogenerate. The literal
values here are frozen in time on purpose — do not import the application enums.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'dd53c67e6a11'
down_revision: Union[str, Sequence[str], None] = '98cd3f35e14e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STEP_LOADS_VIEW = """
CREATE VIEW v_rl_step_loads AS
SELECT s.run_id,
       s.step_index,
       a.ord::int                        AS position,
       r.external_node_names[a.ord::int] AS node_name,
       a.load_value                      AS load,
       s.total_cost
FROM rl_steps AS s
JOIN rl_runs  AS r ON r.id = s.run_id
CROSS JOIN LATERAL unnest(s.allocation) WITH ORDINALITY AS a(load_value, ord)
"""


def upgrade() -> None:
    """Create rl_runs, rl_steps, and the v_rl_step_loads view."""
    op.create_table(
        "rl_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("circuit_name", sa.Text(), nullable=False),
        sa.Column("total_load", sa.Double(), nullable=False),
        sa.Column(
            "external_node_names",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("strategy_version", sa.Text(), nullable=True),
        sa.Column(
            "observation_mode",
            sa.Text(),
            server_default="opaque",
            nullable=False,
        ),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("budget", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("termination_reason", sa.Text(), nullable=True),
        sa.Column("best_cost", sa.Double(), nullable=True),
        sa.Column("best_allocation", postgresql.ARRAY(sa.Double()), nullable=True),
        sa.Column(
            "parent_run_id",
            sa.Integer(),
            sa.ForeignKey("rl_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_progress_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'abandoned')",
            name="ck_rl_runs_status",
        ),
        sa.CheckConstraint(
            "observation_mode IN ('opaque', 'enhanced')",
            name="ck_rl_runs_observation_mode",
        ),
        sa.CheckConstraint(
            "termination_reason IS NULL OR termination_reason IN "
            "('budget_exhausted', 'converged', 'target_reached', 'error', 'interrupted')",
            name="ck_rl_runs_termination_reason",
        ),
        sa.CheckConstraint("total_load > 0", name="ck_rl_runs_total_load_positive"),
        sa.CheckConstraint(
            "circuit_name <> ''", name="ck_rl_runs_circuit_name_not_empty"
        ),
    )
    op.create_table(
        "rl_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("rl_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("allocation", postgresql.ARRAY(sa.Double()), nullable=False),
        sa.Column("total_cost", sa.Double(), nullable=False),
        sa.Column("audit_delay", sa.Double(), nullable=False),
        sa.Column("audit_overload", sa.Double(), nullable=False),
        sa.Column("audit_safety", sa.Double(), nullable=False),
        sa.Column("is_best", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # This unique index is also the ordered-replay index the charting contract needs.
        sa.UniqueConstraint("run_id", "step_index", name="uq_rl_steps_run_step"),
        sa.CheckConstraint(
            "step_index >= 0", name="ck_rl_steps_step_index_non_negative"
        ),
    )
    op.execute(STEP_LOADS_VIEW)


def downgrade() -> None:
    """Drop the view first — PostgreSQL refuses to drop a table a view depends on."""
    op.execute("DROP VIEW IF EXISTS v_rl_step_loads")
    op.drop_table("rl_steps")
    op.drop_table("rl_runs")
