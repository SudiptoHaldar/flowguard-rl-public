"""Persistence for RL algo-runs and their trials (req_002 v2.01).

Repository contract, inherited from :mod:`flowguard.circuits.store`: every function takes an
open SQLAlchemy ``Session`` and **never commits** — the caller owns the transaction.
:class:`flowguard.rl.recorder.RunRecorder` is that caller, and it commits every N trials.

**Opacity contract (spec D5).** The per-category cost breakdown is recorded as private audit
on *every* trial, in both observation modes. :func:`load_history` — the proposer-facing
reader — strips it unless the run is in ``enhanced`` mode. Anything that legitimately needs
the components (human review, safety audit, blueprint §10) calls :func:`load_audit` **by
name**. No proposer, driver, environment, or policy code path may call :func:`load_audit`;
enforcing the rule down here means no layer above can bypass it by forgetting.

**Storage shape (spec D1/D4).** Allocations and node names are native PostgreSQL arrays, not
JSONB, because they are exactly the columns analytics filters and aggregates per node. JSONB
survives only for ``config_snapshot``, which is schemaless and always read whole. The
``v_rl_step_loads`` view (created in the same migration) expands an allocation array into one
row per node so charting can query it as if it were normalised, without multiplying the write
path by the node count.

**Status/mode vocabularies** are ``Text`` columns with named CHECK constraints, driven by the
``StrEnum``s in :mod:`flowguard.rl.types` — see that module for why not a native PG enum.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowguard.data.database import Base

from .types import (
    AllocationMode,
    ObservationMode,
    PenaltyAudit,
    RunStatus,
    TerminationReason,
    Trial,
)


def _in_clause(column: str, enum_cls) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} IN ({values})"


class RunRow(Base):
    """One algo-run: a strategy probing one circuit for one total load."""

    __tablename__ = "rl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    circuit_name: Mapped[str] = mapped_column(Text)
    total_load: Mapped[float] = mapped_column(Double)
    # Names AND their ordinality in one ordered column — the array index IS the position
    # (spec D4). Every run is self-describing, so replay survives later circuit changes.
    external_node_names: Mapped[list[str]] = mapped_column(ARRAY(Text))
    strategy: Mapped[str] = mapped_column(Text)
    strategy_version: Mapped[str | None] = mapped_column(Text)
    observation_mode: Mapped[str] = mapped_column(
        Text, server_default=ObservationMode.OPAQUE.value
    )
    # Continuous strictly dominates integer, so the two populations must never be pooled
    # in a comparison — hence a real column with a CHECK, not a config_snapshot key.
    allocation_mode: Mapped[str] = mapped_column(
        Text, server_default=AllocationMode.INTEGER.value
    )
    config_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    seed: Mapped[int | None] = mapped_column(Integer)
    budget: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default=RunStatus.RUNNING.value)
    termination_reason: Mapped[str | None] = mapped_column(Text)
    best_cost: Mapped[float | None] = mapped_column(Double)
    best_allocation: Mapped[list[float] | None] = mapped_column(ARRAY(Double))
    # Lineage for a warm start from a COMPLETED parent (spec D6.6). NULL is cold-started;
    # v2.06 groups on that rather than pooling warm and cold runs.
    parent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("rl_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Stamped on every batch commit; lazy reconciliation reads it to spot dead runs (D6.3).
    last_progress_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps: Mapped[list["StepRow"]] = relationship(
        cascade="all, delete-orphan",
        order_by="StepRow.step_index",
        back_populates="run",
    )

    __table_args__ = (
        CheckConstraint(_in_clause("status", RunStatus), name="ck_rl_runs_status"),
        CheckConstraint(
            _in_clause("observation_mode", ObservationMode),
            name="ck_rl_runs_observation_mode",
        ),
        CheckConstraint(
            _in_clause("allocation_mode", AllocationMode),
            name="ck_rl_runs_allocation_mode",
        ),
        CheckConstraint(
            "termination_reason IS NULL OR "
            + _in_clause("termination_reason", TerminationReason),
            name="ck_rl_runs_termination_reason",
        ),
        CheckConstraint("total_load > 0", name="ck_rl_runs_total_load_positive"),
        CheckConstraint("circuit_name <> ''", name="ck_rl_runs_circuit_name_not_empty"),
    )


class StepRow(Base):
    """One trial: one ``interface.evaluate`` call and everything it returned."""

    __tablename__ = "rl_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("rl_runs.id", ondelete="CASCADE"))
    # 0-based, dense, monotonic within a run — the ordered-replay key charting reads.
    step_index: Mapped[int] = mapped_column(Integer)
    allocation: Mapped[list[float]] = mapped_column(ARRAY(Double))
    total_cost: Mapped[float] = mapped_column(Double)
    # Private audit — written in BOTH modes, returned only in `enhanced` (spec D5).
    audit_delay: Mapped[float] = mapped_column(Double)
    audit_overload: Mapped[float] = mapped_column(Double)
    audit_safety: Mapped[float] = mapped_column(Double)
    is_best: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped[RunRow] = relationship(back_populates="steps")

    __table_args__ = (
        # Doubles as the ordered-replay index — no separate Index() needed.
        UniqueConstraint("run_id", "step_index", name="uq_rl_steps_run_step"),
        CheckConstraint("step_index >= 0", name="ck_rl_steps_step_index_non_negative"),
    )


OPTIMUM_METHODS = ("enumerated", "best_observed", "unknown")


class BenchmarkRow(Base):
    """One invocation of the benchmark harness (req_002 v2.06).

    Exists for **provenance**: pinning the catalog version and the settings that produced a
    number is what makes it re-checkable later. Aggregating the metrics themselves would be
    cheap to recompute; knowing which catalog and which optimum method produced them is not.
    """

    __tablename__ = "rl_benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalog_name: Mapped[str] = mapped_column(Text)
    catalog_version: Mapped[int] = mapped_column(Integer)
    n_seeds: Mapped[int] = mapped_column(Integer)
    bound_factor: Mapped[float] = mapped_column(Double)
    enumeration_cap: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    results: Mapped[list["BenchmarkResultRow"]] = relationship(
        cascade="all, delete-orphan", back_populates="benchmark"
    )


class BenchmarkResultRow(Base):
    """One (scenario, strategy, seed) measurement."""

    __tablename__ = "rl_benchmark_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benchmark_id: Mapped[int] = mapped_column(
        ForeignKey("rl_benchmarks.id", ondelete="CASCADE")
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("rl_runs.id", ondelete="SET NULL")
    )
    circuit_name: Mapped[str] = mapped_column(Text)
    total_load: Mapped[float] = mapped_column(Double)
    strategy: Mapped[str] = mapped_column(Text)
    strategy_version: Mapped[str | None] = mapped_column(Text)
    seed: Mapped[int | None] = mapped_column(Integer)
    # Grouping keys — never pool across these (v2.01 D5, v2.02 D3, v2.01 D6.6).
    allocation_mode: Mapped[str] = mapped_column(Text)
    observation_mode: Mapped[str] = mapped_column(Text)
    cold_start: Mapped[bool] = mapped_column(Boolean, server_default="true")
    first_cost: Mapped[float] = mapped_column(Double)
    best_cost: Mapped[float] = mapped_column(Double)
    improvement: Mapped[float] = mapped_column(Double)
    trials_used: Mapped[int] = mapped_column(Integer)
    convergence_step: Mapped[int] = mapped_column(Integer)
    optimum: Mapped[float | None] = mapped_column(Double)
    optimum_method: Mapped[str] = mapped_column(Text)
    regret: Mapped[float | None] = mapped_column(Double)
    safety_trials: Mapped[int] = mapped_column(Integer)
    safety_fraction: Mapped[float] = mapped_column(Double)

    benchmark: Mapped[BenchmarkRow] = relationship(back_populates="results")

    __table_args__ = (
        CheckConstraint(
            "optimum_method IN ('enumerated', 'best_observed', 'unknown')",
            name="ck_rl_benchmark_results_optimum_method",
        ),
    )


def create_benchmark(
    session,
    *,
    catalog_name: str,
    catalog_version: int,
    n_seeds: int,
    bound_factor: float,
    enumeration_cap: int,
    notes: str | None = None,
) -> BenchmarkRow:
    row = BenchmarkRow(
        catalog_name=catalog_name,
        catalog_version=catalog_version,
        n_seeds=n_seeds,
        bound_factor=float(bound_factor),
        enumeration_cap=enumeration_cap,
        notes=notes,
    )
    session.add(row)
    session.flush()
    return row


def add_benchmark_result(session, benchmark_id: int, **fields) -> BenchmarkResultRow:
    if fields.get("optimum_method") not in OPTIMUM_METHODS:
        raise ValueError(
            f"optimum_method must be one of {OPTIMUM_METHODS}, "
            f"got {fields.get('optimum_method')!r}"
        )
    row = BenchmarkResultRow(benchmark_id=benchmark_id, **fields)
    session.add(row)
    return row


def load_benchmark_results(session, benchmark_id: int) -> list[BenchmarkResultRow]:
    return list(
        session.scalars(
            select(BenchmarkResultRow)
            .where(BenchmarkResultRow.benchmark_id == benchmark_id)
            .order_by(BenchmarkResultRow.id)
        ).all()
    )


def best_observed_cost(session, circuit_name: str, total_load: float) -> float | None:
    """Lowest cost ever recorded for this (circuit, load) across **completed** runs.

    The fallback when the optimum search is too large to enumerate. Partial runs are excluded
    per v2.01 D6.5 — a truncated run's best is not evidence.
    """
    stmt = (
        select(func.min(RunRow.best_cost))
        .where(RunRow.circuit_name == circuit_name)
        .where(RunRow.total_load == float(total_load))
        .where(RunRow.status == str(RunStatus.COMPLETED))
    )
    return session.scalar(stmt)


def to_trial(row, include_audit: bool) -> Trial:
    """Build a :class:`Trial` from a step row — the single place the D5 strip rule lives.

    Used by :func:`load_history` and by the recorder's in-memory mirror, so opacity cannot
    drift between the two paths.
    """
    audit = (
        PenaltyAudit(row.audit_delay, row.audit_overload, row.audit_safety)
        if include_audit
        else None
    )
    return Trial(row.step_index, tuple(row.allocation), row.total_cost, audit)


def create_run(
    session,
    *,
    circuit_name: str,
    total_load: float,
    external_node_names,
    strategy: str,
    observation_mode: str = ObservationMode.OPAQUE,
    allocation_mode: str = AllocationMode.INTEGER,
    strategy_version: str | None = None,
    seed: int | None = None,
    budget: int | None = None,
    config_snapshot: dict | None = None,
    parent_run_id: int | None = None,
) -> RunRow:
    """Open a run in ``running`` state; returns the flushed row (``id`` populated)."""
    names = list(external_node_names)
    if not names:
        raise ValueError("create_run requires at least one external node name")
    if float(total_load) <= 0:
        raise ValueError(f"total_load must be > 0, got {total_load}")
    if observation_mode not in tuple(ObservationMode):
        raise ValueError(f"unknown observation_mode '{observation_mode}'")
    if allocation_mode not in tuple(AllocationMode):
        raise ValueError(f"unknown allocation_mode '{allocation_mode}'")
    # Integer mode means a countable quantity end to end: fractional loads are impossible,
    # so a fractional total is incoherent. This is the one place that sees both.
    if allocation_mode == AllocationMode.INTEGER and not float(total_load).is_integer():
        raise ValueError(
            f"integer allocation_mode requires an integral total_load, got {total_load}"
        )
    row = RunRow(
        circuit_name=circuit_name,
        total_load=float(total_load),
        external_node_names=names,
        strategy=strategy,
        strategy_version=strategy_version,
        observation_mode=str(observation_mode),
        allocation_mode=str(allocation_mode),
        config_snapshot=config_snapshot,
        seed=seed,
        budget=budget,
        status=str(RunStatus.RUNNING),
        parent_run_id=parent_run_id,
    )
    session.add(row)
    session.flush()
    return row


def append_step(
    session,
    run_id: int,
    step_index: int,
    allocation,
    total_cost: float,
    audit: PenaltyAudit,
    is_best: bool = False,
) -> StepRow:
    """Record one trial. The caller commits (the recorder does, every N trials)."""
    row = StepRow(
        run_id=run_id,
        step_index=step_index,
        allocation=[float(value) for value in allocation],
        total_cost=float(total_cost),
        audit_delay=float(audit.delay),
        audit_overload=float(audit.overload),
        audit_safety=float(audit.safety),
        is_best=is_best,
    )
    session.add(row)
    return row


def load_run(session, run_id: int) -> RunRow:
    row = session.get(RunRow, run_id)
    if row is None:
        raise ValueError(f"run {run_id} does not exist")
    return row


def _steps(session, run_id: int) -> list[StepRow]:
    load_run(session, run_id)  # ValueError for an unknown run, before returning []
    return list(
        session.scalars(
            select(StepRow)
            .where(StepRow.run_id == run_id)
            .order_by(StepRow.step_index)
        ).all()
    )


def load_history(session, run_id: int) -> list[Trial]:
    """Trials in step order, **mode-respecting** — the only reader proposers may use.

    Audit components are stripped unless the run is in ``enhanced`` mode (spec D5).
    """
    run = load_run(session, run_id)
    include_audit = run.observation_mode == ObservationMode.ENHANCED
    return [to_trial(row, include_audit) for row in _steps(session, run_id)]


def load_audit(session, run_id: int) -> list[Trial]:
    """Trials with the cost components **always** populated — the audit/review path.

    Blueprint §10: the environment may retain component-level telemetry for audit and
    safety review, but it must never reach action selection. This function is the reason
    that separation is checkable: no proposer, driver, environment, or policy may call it.
    """
    return [to_trial(row, True) for row in _steps(session, run_id)]


def list_runs(
    session, *, circuit_name: str | None = None, status: str | None = None
) -> list[RunRow]:
    """Runs newest first, optionally filtered by circuit and/or status."""
    stmt = select(RunRow).order_by(RunRow.id.desc())
    if circuit_name is not None:
        stmt = stmt.where(RunRow.circuit_name == circuit_name)
    if status is not None:
        stmt = stmt.where(RunRow.status == str(status))
    return list(session.scalars(stmt).all())


def close_run(
    session,
    run_id: int,
    status: str,
    termination_reason: str | None = None,
    best_cost: float | None = None,
    best_allocation=None,
) -> RunRow:
    """Write the terminal state. Called from ``RunRecorder.__exit__`` on both paths."""
    if status not in tuple(RunStatus) or status == RunStatus.RUNNING:
        raise ValueError(f"'{status}' is not a terminal run status")
    row = load_run(session, run_id)
    row.status = str(status)
    row.termination_reason = (
        str(termination_reason) if termination_reason is not None else None
    )
    if best_cost is not None:
        row.best_cost = float(best_cost)
    if best_allocation is not None:
        row.best_allocation = [float(value) for value in best_allocation]
    row.completed_at = func.now()
    row.last_progress_at = func.now()
    return row


def reconcile_stale_runs(session, threshold_seconds: int) -> int:
    """Sweep presumed-dead runs to ``abandoned``/``interrupted``; returns the row count.

    Lazy reconciliation (spec D6.3): batched commits mean a process that dies leaves its run
    ``running`` forever and nothing self-heals, so the next listing or run creation does the
    sweep. There is no background daemon. Both sides of the comparison use the **server**
    clock — ``last_progress_at`` is written with ``now()`` — so client skew cannot misfire it.
    """
    if threshold_seconds < 1:
        raise ValueError(f"threshold_seconds must be >= 1, got {threshold_seconds}")
    stmt = (
        update(RunRow)
        .where(
            RunRow.status == str(RunStatus.RUNNING),
            RunRow.last_progress_at < func.now() - timedelta(seconds=threshold_seconds),
        )
        .values(
            status=str(RunStatus.ABANDONED),
            termination_reason=str(TerminationReason.INTERRUPTED),
            completed_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    return session.execute(stmt).rowcount


def delete_run(session, run_id: int) -> None:
    """Delete a run and (by cascade) its steps. Mainly the tests' cleanup hook."""
    session.delete(load_run(session, run_id))
