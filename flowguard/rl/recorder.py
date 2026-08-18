"""The recorded probe surface RL strategies use to evaluate a circuit (req_002 v2.01).

``RunRecorder`` wraps :func:`flowguard.circuits.interface.evaluate` so that **every call in
an algo-run is persisted as it happens** — the requirement is structural here rather than a
discipline any strategy could forget. It is a context manager for the same reason: the
close-time commit and the terminal status are written by ``__exit__``, not by remembering a
``finally`` at every call site (spec D3/D7).

Usage::

    from flowguard.rl.recorder import RunRecorder

    with RunRecorder("C2", 60, strategy="equal_split") as run:
        cost = run.evaluate([10, 10])       # 92.0 — the bare scalar, the RL signal
        history = run.history()             # [Trial(...)] — audit stripped unless enhanced

Transactions: the recorder owns the session and commits every ``commit_every_n_steps``
trials (config-driven; N=1 is per-step). A crash loses at most N trials, which is cheap —
a seeded run is replayable, and no reader needs mid-run visibility because charts replay
completed runs. The repository underneath stays commit-free.

Opacity: ``evaluate`` asks the circuit for the full breakdown so it can be **recorded**, but
what comes back to the caller is the bare total, and ``history()`` strips the components
unless the run is in ``enhanced`` mode. Note this module reads ``.delay``/``.overload``/
``.safety`` off the returned object without importing ``circuits.model`` — the RL side
reaches circuits only through ``circuits.interface``.
"""

from __future__ import annotations

from sqlalchemy import func

from flowguard.circuits import interface
from flowguard.data.database import get_session_factory

from . import config, store
from .types import (
    AllocationMode,
    ObservationMode,
    PenaltyAudit,
    RunStatus,
    TerminationReason,
    Trial,
)


class RunRecorder:
    """A persisted algo-run. Use as a context manager; every ``evaluate`` is recorded."""

    def __init__(
        self,
        circuit_name: str,
        total_load: float,
        *,
        strategy: str = "unspecified",
        observation_mode: str = ObservationMode.OPAQUE,
        allocation_mode: str = AllocationMode.INTEGER,
        strategy_version: str | None = None,
        seed: int | None = None,
        budget: int | None = None,
        config_snapshot: dict | None = None,
        parent_run_id: int | None = None,
        session=None,
        commit_every_n_steps: int | None = None,
    ):
        if observation_mode not in tuple(ObservationMode):
            raise ValueError(f"unknown observation_mode '{observation_mode}'")
        if allocation_mode not in tuple(AllocationMode):
            raise ValueError(f"unknown allocation_mode '{allocation_mode}'")
        if commit_every_n_steps is not None and (
            not isinstance(commit_every_n_steps, int)
            or isinstance(commit_every_n_steps, bool)
            or commit_every_n_steps < 1
        ):
            raise ValueError(
                f"commit_every_n_steps must be an integer >= 1, "
                f"got {commit_every_n_steps!r}"
            )
        self.circuit_name = circuit_name
        self.total_load = float(total_load)
        self.strategy = strategy
        self.observation_mode = observation_mode
        self.allocation_mode = allocation_mode
        self.strategy_version = strategy_version
        self.seed = seed
        self.budget = budget
        self.config_snapshot = config_snapshot
        self.parent_run_id = parent_run_id
        # v2.02's driver overrides this before exit when it stops for a different reason.
        self.termination_reason: str = TerminationReason.BUDGET_EXHAUSTED

        self._commit_every_n = commit_every_n_steps
        self._session = session
        self._owns_session = session is None
        self._enhanced = observation_mode == ObservationMode.ENHANCED
        self.run_id: int | None = None
        self._names: list[str] = []
        self._history: list[Trial] = []
        self._pending = 0
        self._next_index = 0
        self._best_cost: float | None = None
        self._best_allocation: tuple[float, ...] | None = None

    # --- lifecycle ---

    def __enter__(self) -> "RunRecorder":
        if self._commit_every_n is None:
            self._commit_every_n = config.commit_every_n_steps()
        if self._session is None:
            self._session = get_session_factory()()
        # Also proves the circuit exists before a run row is written.
        self._names = interface.ext_nodes(self.circuit_name)
        run = store.create_run(
            self._session,
            circuit_name=self.circuit_name,
            total_load=self.total_load,
            external_node_names=self._names,
            strategy=self.strategy,
            observation_mode=self.observation_mode,
            allocation_mode=self.allocation_mode,
            strategy_version=self.strategy_version,
            seed=self.seed,
            budget=self.budget,
            config_snapshot=self.config_snapshot,
            parent_run_id=self.parent_run_id,
        )
        self._session.commit()
        self.run_id = run.id
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is not None:
                # The failed transaction cannot accept further statements, and rolling back
                # discards the uncommitted partial batch — the accepted <= N loss (spec D3).
                self._session.rollback()
                status, reason = RunStatus.FAILED, TerminationReason.ERROR
            else:
                status, reason = RunStatus.COMPLETED, self.termination_reason
            store.close_run(
                self._session,
                self.run_id,
                status,
                reason,
                self._best_cost,
                self._best_allocation,
            )
            self._session.commit()
        finally:
            if self._owns_session:
                self._session.close()
        return False  # never suppress

    # --- probing ---

    def evaluate(self, allocation) -> float:
        """Evaluate one allocation, persist the trial, and return the bare total cost."""
        if self.run_id is None:
            raise RuntimeError("RunRecorder must be used as a context manager")
        loads = tuple(float(value) for value in allocation)
        if len(loads) != len(self._names):
            raise ValueError(
                f"circuit '{self.circuit_name}' has {len(self._names)} external nodes, "
                f"got {len(loads)} loads"
            )
        breakdown = interface.evaluate(
            self.circuit_name, self.total_load, loads, breakdown=True
        )
        total = float(breakdown.total)
        audit = PenaltyAudit(
            float(breakdown.delay), float(breakdown.overload), float(breakdown.safety)
        )
        is_best = self._best_cost is None or total < self._best_cost
        if is_best:
            self._best_cost, self._best_allocation = total, loads

        row = store.append_step(
            self._session, self.run_id, self._next_index, loads, total, audit, is_best
        )
        # Same strip helper as load_history, so opacity cannot drift between the two paths.
        self._history.append(store.to_trial(row, self._enhanced))
        self._next_index += 1
        self._pending += 1
        if self._pending >= self._commit_every_n:
            self._flush()
        return total

    def history(self) -> list[Trial]:
        """Trials so far, in step order — the in-memory mirror of what was persisted.

        Serving this from memory keeps a proposal loop off the database entirely; batching
        commits would be pointless if every proposal re-read the run.
        """
        return list(self._history)

    @property
    def trials_used(self) -> int:
        """Trials recorded so far — the budget is counted against this (spec v2.02 D4)."""
        return self._next_index

    @property
    def best(self) -> tuple[float | None, tuple[float, ...] | None]:
        """Lowest cost seen so far and the allocation that earned it."""
        return self._best_cost, self._best_allocation

    def _flush(self) -> None:
        """Commit the pending batch; the best-so-far update rides in it (spec D3)."""
        run = self._session.get(store.RunRow, self.run_id)
        run.best_cost = self._best_cost
        run.best_allocation = (
            list(self._best_allocation) if self._best_allocation is not None else None
        )
        run.last_progress_at = func.now()
        self._session.commit()
        self._pending = 0
