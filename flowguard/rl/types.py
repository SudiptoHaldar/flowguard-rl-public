"""Vocabularies and the SQLAlchemy-free records the RL layers exchange (req_002 v2.01).

This module deliberately imports neither SQLAlchemy nor anything from ``flowguard.circuits``:
v2.02 proposers are unit-tested against synthetic histories with no database, and the v2.07
CLI needs the vocabularies for argument parsing. Anything that would drag the persistence
layer into a DB-free path does not belong here.

The enums are :class:`enum.StrEnum` — their members *are* strings, so they bind straight into
``Text`` columns and compare equal to the stored value (``row.status == RunStatus.RUNNING``
is ``True``). A native PostgreSQL ``ENUM`` type is deliberately avoided (spec D6.2a): the
vocabularies grow as v2.02 adds stopping rules, and ``ALTER TYPE`` is the one migration
Alembic will not autogenerate. Each column carries a named CHECK constraint instead — see
:mod:`flowguard.rl.store`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RunStatus(StrEnum):
    """Lifecycle state of an algo-run (spec D6.1).

    ``failed`` and ``abandoned`` are both terminal and both unusable downstream (D6.5); they
    are kept apart because they tell an operator different things.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class TerminationReason(StrEnum):
    """Why a run stopped (spec D6.2).

    v2.02 owns the *triggers* (the stopping rules); the vocabulary is fixed here because this
    is stored data that outlives the code that wrote it. New values arrive by migration.
    """

    BUDGET_EXHAUSTED = "budget_exhausted"
    CONVERGED = "converged"
    TARGET_REACHED = "target_reached"
    ERROR = "error"
    INTERRUPTED = "interrupted"


class ObservationMode(StrEnum):
    """Whether the private cost breakdown reaches the caller (spec D5).

    ``opaque`` is the default and the posture of the whole group: the breakdown is recorded
    for audit but never returned to anything that chooses the next allocation. ``enhanced``
    is an opt-in oracle baseline that prices opacity — its runs must never be pooled with
    opaque ones (v2.06) nor used to warm-start them (v2.03).
    """

    OPAQUE = "opaque"
    ENHANCED = "enhanced"


class AllocationMode(StrEnum):
    """Whether loads must be whole numbers (req_002 v2.02 D3).

    ``continuous`` is a strict *superset* of ``integer``, so a continuous run can never do
    worse than its integer counterpart — which is exactly why the mode is recorded per run
    and why v2.06 must never pool the two populations. Measured cost of integrality on C2 is
    under half a percent.
    """

    INTEGER = "integer"
    CONTINUOUS = "continuous"


@dataclass(frozen=True)
class PenaltyAudit:
    """Per-category breakdown of one trial — private audit data (blueprint §10).

    Deliberately a local record rather than ``circuits.model.PenaltyBreakdown``: the RL side
    reaches circuits only through ``circuits.interface``, so the breakdown object it gets
    back is read attribute-wise and re-wrapped here.
    """

    delay: float
    overload: float
    safety: float

    @property
    def total(self) -> float:
        return self.delay + self.overload + self.safety


@dataclass(frozen=True)
class Trial:
    """One persisted probe of a circuit: the allocation tried and the scalar cost it earned.

    ``allocation`` is positional against the run's ``external_node_names``. ``audit`` is
    ``None`` unless the run is in ``enhanced`` mode — the stripping happens in
    :func:`flowguard.rl.store.to_trial`, the single place that rule lives.

    ``step_index`` is **0-based**, dense and monotonic within a run (it is also the index of
    this trial in the history list). Note that ``position`` in the ``v_rl_step_loads`` view
    is **1-based**, because PostgreSQL arrays are — different axes, deliberately not
    reconciled.
    """

    step_index: int
    allocation: tuple[float, ...]
    total_cost: float
    audit: PenaltyAudit | None = None


@dataclass(frozen=True)
class ProposalContext:
    """Everything a proposer may see — and nothing else (req_002 v2.02 D1.2).

    This is the opacity boundary in object form: if a field is not here, a proposer cannot
    reach it. Node factors, safety caps, penalty coefficients and (outside ``enhanced`` mode)
    the cost breakdown are all absent by construction.

    Passed as one frozen object rather than a parameter list because the list will grow, and
    every addition would otherwise break every existing proposer.
    """

    node_names: tuple[str, ...]
    total_load: float
    history: tuple[Trial, ...]
    trials_used: int
    budget: int
    #: Lowest-cost trial so far; ties broken by earliest ``step_index`` (D1.2). ``None``
    #: before the first evaluation. Note this pins only the *recorded* best — a proposer is
    #: free to break its own internal ties randomly (D5.3).
    best: Trial | None
    observation_mode: ObservationMode
    allocation_mode: AllocationMode
    #: Smallest permitted *positive* load: 1 in integer mode, the config floor otherwise.
    #: Zero is always legal, which is what keeps ``sum <= total_load`` satisfiable when a
    #: circuit has more nodes than the load can cover.
    min_allocation: float

    @property
    def node_count(self) -> int:
        return len(self.node_names)

    @property
    def trials_remaining(self) -> int:
        return max(0, self.budget - self.trials_used)
