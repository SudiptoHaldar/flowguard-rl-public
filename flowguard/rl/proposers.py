"""The proposer protocol and the four heuristic baselines (req_002 v2.02).

A proposer sees only a :class:`~flowguard.rl.types.ProposalContext` — external-node names,
the total load, the trials so far and their costs — and returns one allocation. It never sees
node factors, safety caps, penalty coefficients, or (outside ``enhanced`` mode) the cost
breakdown. Whatever it learns about a circuit, it learns from scalar feedback.

Proposers are **stateful objects**, not pure functions: a seeded ``random.Random`` has to
persist across calls. ``reset(seed)`` is called by the driver before the first proposal, so
the driver owns the seed and records it — reusing a proposer instance across runs would
otherwise continue its RNG stream and make the recorded seed a lie.

Reproducibility is best-effort, not contractual (spec D5): proposers may randomise freely,
including tie-breaking, which the measured flat ridges make a genuinely useful escape
mechanism rather than a hazard.

**Baselines may exploit structural knowledge but never parametric knowledge.** That the delay
term depends only on the *sum* of the loads is public in the high-level plan and fair game —
it is what ``ReleaseSweep`` is built on. This circuit's factors and caps are hidden and must
be discovered by probing.
"""

from __future__ import annotations

import math
import random
from typing import Protocol, Sequence

from . import config
from .types import AllocationMode, ObservationMode, ProposalContext


class ProposerExhausted(Exception):
    """Raised when no distinct proposals remain.

    The driver ends the run with ``converged`` rather than padding the remaining budget with
    repeat trials (spec D4): a finite sweep that has run out of ideas should say so, not
    manufacture work to hit a number.
    """


class Proposer(Protocol):
    """What the driver requires of a strategy.

    Not ``runtime_checkable`` on purpose — a protocol with non-method members cannot support
    ``isinstance`` cleanly, and the driver duck-types instead.
    """

    #: Persisted to ``rl_runs.strategy`` (NOT NULL), so it is required.
    name: str
    #: Persisted to ``rl_runs.strategy_version`` (nullable). Bump it whenever a default
    #: changes in a way that makes runs incomparable — v2.06 groups on it.
    version: str | None
    #: Checked by the driver *before* the run row is created (spec D1.5).
    requires_mode: ObservationMode

    def reset(self, seed: int | None) -> None:
        """Re-seed and clear per-run state. Called once before the first proposal."""

    def propose(self, context: ProposalContext) -> Sequence[float]:
        """Return one allocation, positional against ``context.node_names``."""

    def params(self) -> dict:
        """Resolved tunables, recorded in ``rl_runs.config_snapshot`` (JSON-serialisable)."""


# --- shared helpers ---

def _snap(loads, context: ProposalContext) -> list[float]:
    """Make a raw vector representable in the run's allocation mode.

    This is a proposer producing a *valid* proposal, not the driver repairing an invalid one
    — the driver never repairs (spec D1.4). Negative values clamp to zero, and positive
    values below the floor snap to zero, since zero is always legal but a sub-floor positive
    load is not.
    """
    out = []
    for value in loads:
        value = max(0.0, float(value))
        if context.allocation_mode is AllocationMode.INTEGER:
            value = float(int(round(value)))
        if 0 < value < context.min_allocation:
            value = 0.0
        out.append(value)
    return out


def split_by_weights(total: float, weights, context: ProposalContext) -> list[float]:
    """Divide ``total`` across the nodes in proportion to ``weights``.

    Integer mode uses the largest-remainder method so the parts sum to exactly ``total``;
    naive floor division would quietly lose up to ``n-1`` units and change the release total,
    which is the one quantity the delay term depends on.
    """
    weight_sum = float(sum(weights))
    count = len(weights)
    if weight_sum <= 0:
        weights = [1.0] * count
        weight_sum = float(count)
    raw = [total * float(w) / weight_sum for w in weights]

    if context.allocation_mode is not AllocationMode.INTEGER:
        return _snap(raw, context)

    floors = [int(math.floor(value)) for value in raw]
    remainder = int(round(total)) - sum(floors)
    if remainder > 0:
        order = sorted(range(count), key=lambda i: raw[i] - floors[i], reverse=True)
        for index in order[:remainder]:
            floors[index] += 1
    return [float(value) for value in floors]


def split_equally(total: float, context: ProposalContext) -> list[float]:
    return split_by_weights(total, [1.0] * context.node_count, context)


# --- the four baselines ---

class EqualSplit:
    """Split the whole load equally and dispose of it in one cycle.

    A **degenerate reference**, not a competitor: with no history and no parameters, the only
    well-defined release total is the full load, which measures ~3e7 on C2 at L=60 and ~1e21
    at L=20000. Its job is to show that naive disposal is catastrophic — i.e. that the
    problem needs solving at all — so it is reported separately and excluded from averaged
    comparisons. Exhausts after one proposal rather than burning the budget on repeats.
    """

    name = "equal_split"
    version = "1"
    requires_mode = ObservationMode.OPAQUE

    def __init__(self):
        self._proposed = False

    def reset(self, seed: int | None) -> None:
        self._proposed = False

    def propose(self, context: ProposalContext) -> Sequence[float]:
        if self._proposed:
            raise ProposerExhausted("equal_split has exactly one proposal")
        self._proposed = True
        return split_equally(context.total_load, context)

    def params(self) -> dict:
        return {}


class RandomSimplex:
    """Dirichlet-shaped split at a **log-uniformly** random release total.

    The "is this just sampling?" control, and it has to be a *fair* one to mean anything.

    Version 2 draws the release total log-uniformly rather than uniformly (2026-08-17). The
    linear version was close to a strawman: the useful release totals sit in a narrow band
    near the sum of the node capacities — roughly 30-40 out of 10,000 on C4 — so a uniform
    draw over ``[1, L]`` landed there about 0.3% of the time and the control lost for a
    reason that had nothing to do with sampling being a weak strategy. Log-uniform spreads
    the draws evenly across orders of magnitude, which is the same reasoning that makes
    :class:`ReleaseSweep` log-spaced: ``z = ceil(L/S)`` varies as ``1/S``.

    ``strategy_version`` is bumped to ``2`` because runs before and after are not comparable
    — exactly the case the version column exists for (spec D2.6.5).
    """

    name = "random_simplex"
    version = "2"
    requires_mode = ObservationMode.OPAQUE

    def __init__(self, concentration: float | None = None):
        self._concentration = (
            concentration
            if concentration is not None
            else config.random_simplex_concentration()
        )
        if self._concentration <= 0:
            raise ValueError(
                f"concentration must be > 0, got {self._concentration!r}"
            )
        self._rng = random.Random()

    def reset(self, seed: int | None) -> None:
        self._rng = random.Random(seed)

    def propose(self, context: ProposalContext) -> Sequence[float]:
        weights = [
            self._rng.gammavariate(self._concentration, 1.0)
            for _ in range(context.node_count)
        ]
        # Log-uniform scale: even coverage across orders of magnitude, so the narrow band of
        # useful release totals gets a fair share of the draws.
        low = 1.0 if context.allocation_mode is AllocationMode.INTEGER else (
            context.min_allocation
        )
        high = max(low, context.total_load)
        if high > low:
            total = math.exp(self._rng.uniform(math.log(low), math.log(high)))
        else:
            total = low
        if context.allocation_mode is AllocationMode.INTEGER:
            total = float(min(int(context.total_load), max(1, int(round(total)))))
        else:
            total = min(high, max(low, total))
        loads = split_by_weights(total, weights, context)
        if sum(loads) <= 0:  # every share snapped to zero — keep the proposal legal
            loads[self._rng.randrange(context.node_count)] = context.min_allocation
        return loads

    def params(self) -> dict:
        return {"concentration": self._concentration}


class ReleaseSweep:
    """Sweep the release *total* on a log scale, splitting equally at each.

    **The bar to beat.** It uses only structural knowledge — that the delay term depends on
    the sum of the loads — and nothing about this circuit's hidden factors or caps. Log
    spacing is essential rather than cosmetic: ``z = ceil(L/S)`` varies as ``1/S``, so linear
    spacing spends almost the whole budget in the high-S region where the cycle count barely
    moves.

    Its weakness is informative: it finds a good release total but cannot fix the *split*,
    so it does well on the near-symmetric C2 (~15% above optimum) and trails badly on C3,
    whose capacities are 10/5/20/2. Separating "total" from "split" is what makes it a
    diagnostic rather than just a number.
    """

    name = "release_sweep"
    version = "1"
    requires_mode = ObservationMode.OPAQUE

    def __init__(self):
        self._index = 0
        self._previous: float | None = None

    def reset(self, seed: int | None) -> None:
        self._index = 0
        self._previous = None

    def propose(self, context: ProposalContext) -> Sequence[float]:
        total_load = context.total_load
        steps = max(1, context.budget)
        while True:
            if self._index >= steps:
                raise ProposerExhausted("release_sweep has covered its range")
            exponent = (self._index + 1) / steps
            total = total_load ** exponent
            if context.allocation_mode is AllocationMode.INTEGER:
                total = float(max(1, int(round(total))))
            else:
                total = max(context.min_allocation, total)
            self._index += 1
            # Deduplicate against the previous value only: the sequence is monotonic, so an
            # ordered comparison suffices and no set iteration is involved.
            if self._previous is None or total != self._previous:
                break
        self._previous = total
        return split_equally(total, context)

    def params(self) -> dict:
        return {"spacing": "log"}


class HillClimb:
    """Coordinate hill-climb around the best-so-far, with a halving step schedule.

    Measured to converge in 35–452 trials across ``n`` in {2, 4, 10} and ``L`` in
    {60 … 20000} with ``initial_step_fraction = 0.25`` — a validated default rather than a
    guess.

    **Plateau escape is the reason this tracks a ``current`` point separately from
    ``best``.** The cost surface has genuinely flat regions: `z = ceil(L/S)` is constant
    across a band of release totals, so while every node stays under its capacity, changing
    one load by a step leaves the cost *exactly* unchanged. A climber that only accepts
    strict improvements stalls there — measured stalling at cost 3.0 on C3 at L=60 when the
    optimum is 2.0, because reaching it needs the release sum to drift from 22 up to 30
    through a stretch where nothing improves. So this accepts **non-worsening** moves, which
    lets the point drift laterally across a plateau until the next cliff, while the step is
    only halved when a full sweep of ``2n`` perturbations yields no *strict* improvement.
    Once the step falls below the mode's quantum there is nothing finer to try and the
    proposer exhausts.
    """

    name = "hill_climb"
    version = "1"
    requires_mode = ObservationMode.OPAQUE

    def __init__(self, initial_step_fraction: float | None = None):
        self._initial_step_fraction = (
            initial_step_fraction
            if initial_step_fraction is not None
            else config.hill_climb_initial_step_fraction()
        )
        if not 0 < self._initial_step_fraction <= 1:
            raise ValueError(
                "initial_step_fraction must be in (0, 1], got "
                f"{self._initial_step_fraction!r}"
            )
        self._reset_state()

    def _reset_state(self) -> None:
        self._step: float | None = None
        self._cursor = 0
        self._current: list[float] | None = None
        self._current_cost: float | None = None
        self._sweep_improved = False
        self._since_halve = 0

    def reset(self, seed: int | None) -> None:
        self._reset_state()

    def _quantum(self, context: ProposalContext) -> float:
        return 1.0 if context.allocation_mode is AllocationMode.INTEGER else (
            context.min_allocation
        )

    def _halve(self, context: ProposalContext) -> None:
        """Refine the step, clamping at the mode's quantum — never exhausting.

        Deliberately does *not* raise once the finest step is reached. Crossing a plateau
        takes many lateral moves in the same direction, far more than the single sweep that
        triggers a halving, so quitting at the finest step abandons the search exactly where
        it is doing the most useful work. It also matches spec D4: the budget is the stopping
        rule, and trials cost microseconds.
        """
        quantum = self._quantum(context)
        if context.allocation_mode is AllocationMode.INTEGER:
            self._step = float(max(1, int(self._step) // 2))
        else:
            self._step = max(quantum, self._step / 2)

    def propose(self, context: ProposalContext) -> Sequence[float]:
        if not context.history:  # first call — evaluate a mid-range starting point
            self._step = max(
                self._quantum(context),
                self._initial_step_fraction * context.total_load,
            )
            if context.allocation_mode is AllocationMode.INTEGER:
                self._step = float(max(1, int(round(self._step))))
            start = split_equally(context.total_load / 2, context)
            self._current = list(start)
            return start

        # Learn the outcome of whatever we proposed last. Accepting equal-cost moves is what
        # lets the point cross a plateau; only a strict improvement counts towards keeping
        # the current step size.
        last = context.history[-1]
        accepted = False
        if self._current_cost is None:
            self._current = list(last.allocation)
            self._current_cost = last.total_cost
        elif last.total_cost < self._current_cost:
            self._current = list(last.allocation)
            self._current_cost = last.total_cost
            self._sweep_improved = True
            accepted = True
        elif last.total_cost <= self._current_cost:
            self._current = list(last.allocation)  # lateral drift along the plateau
            accepted = True

        # Line search: while a direction keeps being accepted, keep going that way. Without
        # this, alternating +/- passes undo their own lateral progress — the "+" sweep drifts
        # up a plateau at equal cost and the "-" sweep drifts straight back down, netting
        # nothing. Persisting in a direction is what actually crosses a flat region.
        if not accepted:
            self._cursor += 1
            self._since_halve += 1

        perturbations = 2 * context.node_count
        for _ in range(perturbations * 2 + 2):
            if self._since_halve >= perturbations:
                if not self._sweep_improved:
                    self._halve(context)
                self._sweep_improved = False
                self._since_halve = 0

            coordinate = self._cursor % context.node_count
            sign = 1.0 if (self._cursor // context.node_count) % 2 == 0 else -1.0

            candidate = list(self._current)
            candidate[coordinate] = self._current[coordinate] + sign * self._step
            candidate = _snap(candidate, context)
            total = sum(candidate)
            if 0 < total <= context.total_load and candidate != self._current:
                return candidate

            self._cursor += 1  # this direction is unrepresentable; try the next
            self._since_halve += 1

        # Nothing representable at this step size; refine and try again.
        self._halve(context)
        return self.propose(context)

    def params(self) -> dict:
        return {"initial_step_fraction": self._initial_step_fraction}


#: Name -> factory, for the CLI (v2.07) and the benchmark harness (v2.06).
BASELINES = {
    "equal_split": EqualSplit,
    "random_simplex": RandomSimplex,
    "release_sweep": ReleaseSweep,
    "hill_climb": HillClimb,
}
