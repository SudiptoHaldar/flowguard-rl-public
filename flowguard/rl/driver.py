"""The algo-run driver: propose → validate → record, under a fixed budget (req_002 v2.02).

``run_algo`` is the loop the whole group is built around. It opens a run through
:class:`~flowguard.rl.recorder.RunRecorder` (so every probe is persisted as it happens),
hands the proposer the history so far, validates what comes back, and records the result.

Two things it deliberately does **not** do:

* **It never repairs a proposal.** A negative load, a sub-floor positive, or a sum over the
  total load raises. Clipping or renormalising would make a strategy's behaviour untraceable
  and hide the bug that produced it. (Proposers generating valid candidates is a different
  thing — that is their job.)
* **It never stops early.** The budget is the stopping rule: no target cost (unknowable for
  an unseen circuit) and no no-improvement window (the cost surface has measured flat spots,
  so "no improvement" is not "converged"). Repeat proposals are charged, because evaluations
  are deterministic and a proposer repeating itself is genuinely wasting budget.

The one honest exception is :class:`~flowguard.rl.proposers.ProposerExhausted`: a finite
sweep that has run out of distinct proposals ends the run as ``converged`` rather than
padding the remainder with repeats.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from flowguard.circuits import interface

from . import config
from .proposers import ProposerExhausted
from .recorder import RunRecorder
from .types import AllocationMode, ObservationMode, ProposalContext, TerminationReason, Trial

#: Slack for float comparisons — 0.1 has no exact binary representation, so a value that is
#: ``0.1 - 1e-17`` after arithmetic must not be rejected as below the floor.
_EPSILON = 1e-9


@dataclass(frozen=True)
class RunResult:
    """What an algo-run produced. ``best_*`` are ``None`` only if no trial ever ran."""

    run_id: int
    best_cost: float | None
    best_allocation: tuple[float, ...] | None
    trials_used: int
    termination_reason: str


def default_budget(node_count: int, total_load: float) -> int:
    """``max(floor, ceil(k * n * log2(total_load)))`` — a formula, not a constant.

    Measured trials-to-converge scale **linearly in the node count** and **logarithmically in
    the total load** (at L=1440, n=2/4/10 needed 63/140/296 trials; at n=2, L=60→20000 needed
    35→88). A ``sqrt(n * L)`` shape errs in both directions at once and starves 7 of 12
    measured cases; this one holds 1.2x–2.9x headroom over a hill-climb's convergence point.
    """
    if node_count < 1:
        raise ValueError(f"node_count must be >= 1, got {node_count}")
    safe_load = max(2.0, float(total_load))  # log2 needs > 1 to be useful
    formula = config.budget_k() * node_count * math.log2(safe_load)
    return max(config.budget_floor(), math.ceil(formula))


def validate_allocation(loads, context: ProposalContext) -> tuple[float, ...]:
    """Check a proposal against the run's allocation rules; raise, never repair.

    Length is not checked here — ``RunRecorder.evaluate`` already owns that, and it owns it
    for v2.04's environment too.
    """
    values = []
    for index, raw in enumerate(loads):
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"load at index {index} is not finite: {raw!r}")
        if value < 0:
            raise ValueError(f"load at index {index} must be >= 0, got {value}")
        if context.allocation_mode is AllocationMode.INTEGER and not value.is_integer():
            raise ValueError(
                f"integer allocation_mode requires whole loads; index {index} is {value}"
            )
        if 0 < value < context.min_allocation - _EPSILON:
            raise ValueError(
                f"load at index {index} is {value}, below the minimum positive "
                f"allocation {context.min_allocation} (zero is allowed, sub-floor is not)"
            )
        values.append(value)

    total = sum(values)
    if total <= 0:
        raise ValueError("allocation must place a positive total per-cycle load")
    if total > context.total_load + _EPSILON:
        # Exceeding the total load is provably dominated: any sum >= L gives z = 1, so a
        # bigger sum buys no delay saving while penalties only grow.
        raise ValueError(
            f"per-cycle sum {total} exceeds total_load {context.total_load}"
        )
    return tuple(values)


def _best_trial(history) -> Trial | None:
    """Lowest cost, ties broken by earliest ``step_index`` (spec D1.2).

    Ties are structural here rather than rare — four distinct allocations cost exactly 93.0
    on C2 at L=1440 — so an unpinned rule would leave ``best_allocation`` ambiguous.
    """
    best = None
    for trial in history:
        if best is None or trial.total_cost < best.total_cost:
            best = trial
    return best


def run_algo(
    circuit_name: str,
    total_load: float,
    proposer,
    *,
    budget: int | None = None,
    seed: int | None = None,
    allocation_mode: str = AllocationMode.INTEGER,
    observation_mode: str = ObservationMode.OPAQUE,
    session=None,
    commit_every_n_steps: int | None = None,
) -> RunResult:
    """Run one algo-run to completion and return its result."""
    if allocation_mode not in tuple(AllocationMode):
        raise ValueError(f"unknown allocation_mode '{allocation_mode}'")
    if observation_mode not in tuple(ObservationMode):
        raise ValueError(f"unknown observation_mode '{observation_mode}'")

    # Fail before a run row exists: an enhanced-only proposer in an opaque run must not
    # leave a half-started run behind (spec D1.5).
    required = getattr(proposer, "requires_mode", ObservationMode.OPAQUE)
    if required == ObservationMode.ENHANCED and observation_mode != ObservationMode.ENHANCED:
        raise ValueError(
            f"proposer '{proposer.name}' requires enhanced observation_mode, "
            f"but the run is '{observation_mode}'"
        )
    if allocation_mode == AllocationMode.INTEGER and not float(total_load).is_integer():
        raise ValueError(
            f"integer allocation_mode requires an integral total_load, got {total_load}"
        )

    # ext_nodes is process-cached, so asking here costs nothing and lets the budget formula
    # see the node count before the recorder opens the run.
    node_names = tuple(interface.ext_nodes(circuit_name))
    if budget is None:
        budget = default_budget(len(node_names), total_load)
    elif budget < 1:
        raise ValueError(f"budget must be >= 1, got {budget}")

    min_allocation = (
        1.0
        if allocation_mode == AllocationMode.INTEGER
        else config.min_allocation()
    )
    proposer.reset(seed)

    with RunRecorder(
        circuit_name,
        total_load,
        strategy=proposer.name,
        strategy_version=getattr(proposer, "version", None),
        seed=seed,
        budget=budget,
        allocation_mode=allocation_mode,
        observation_mode=observation_mode,
        config_snapshot={"proposer": proposer.params()},
        session=session,
        commit_every_n_steps=commit_every_n_steps,
    ) as run:
        while run.trials_used < budget:
            history = tuple(run.history())
            context = ProposalContext(
                node_names=node_names,
                total_load=float(total_load),
                history=history,
                trials_used=run.trials_used,
                budget=budget,
                best=_best_trial(history),
                observation_mode=ObservationMode(observation_mode),
                allocation_mode=AllocationMode(allocation_mode),
                min_allocation=min_allocation,
            )
            try:
                raw = proposer.propose(context)
            except ProposerExhausted:
                run.termination_reason = TerminationReason.CONVERGED
                break
            run.evaluate(validate_allocation(raw, context))

        best_cost, best_allocation = run.best
        result = RunResult(
            run_id=run.run_id,
            best_cost=best_cost,
            best_allocation=best_allocation,
            trials_used=run.trials_used,
            termination_reason=run.termination_reason,
        )
    return result
