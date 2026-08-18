"""Tests for flowguard.rl.proposers — all DB-free, against synthetic contexts.

Being able to test proposers with no database is exactly why `ProposalContext` lives in
`types.py` rather than alongside the SQLAlchemy models.
"""

import json
import math

import pytest

from flowguard.rl.proposers import (
    BASELINES,
    EqualSplit,
    HillClimb,
    ProposerExhausted,
    RandomSimplex,
    ReleaseSweep,
    split_by_weights,
    split_equally,
)
from flowguard.rl.types import (
    AllocationMode,
    ObservationMode,
    ProposalContext,
    Trial,
)


def make_context(
    history=(),
    *,
    node_count=2,
    total_load=60.0,
    budget=50,
    mode=AllocationMode.INTEGER,
    min_allocation=1.0,
):
    trials = tuple(history)
    best = min(trials, key=lambda t: t.total_cost, default=None) if trials else None
    return ProposalContext(
        node_names=tuple(f"N{i + 1}" for i in range(node_count)),
        total_load=total_load,
        history=trials,
        trials_used=len(trials),
        budget=budget,
        best=best,
        observation_mode=ObservationMode.OPAQUE,
        allocation_mode=mode,
        min_allocation=min_allocation,
    )


def simulate(proposer, cost_fn, *, node_count=2, total_load=60.0, budget=40, mode=None):
    """Drive a proposer against a synthetic cost function — the driver loop, minus the DB."""
    mode = mode or AllocationMode.INTEGER
    proposer.reset(7)
    history = []
    for step in range(budget):
        context = make_context(
            history,
            node_count=node_count,
            total_load=total_load,
            budget=budget,
            mode=mode,
            min_allocation=1.0 if mode is AllocationMode.INTEGER else 0.1,
        )
        try:
            loads = tuple(float(x) for x in proposer.propose(context))
        except ProposerExhausted:
            break
        history.append(Trial(step, loads, cost_fn(loads)))
    return history


# --- expected ---

def test_split_equally_is_exact_in_integer_mode():
    context = make_context(node_count=4)
    parts = split_equally(30, context)
    assert sum(parts) == 30  # largest remainder, not lossy floor division
    assert parts == [8.0, 8.0, 7.0, 7.0]
    assert all(float(p).is_integer() for p in parts)


def test_split_by_weights_respects_proportions():
    context = make_context(node_count=3)
    parts = split_by_weights(10, [1, 2, 7], context)
    assert sum(parts) == 10
    assert parts[2] > parts[1] > parts[0]


def test_equal_split_uses_the_whole_load_then_exhausts():
    proposer = EqualSplit()
    proposer.reset(1)
    context = make_context(node_count=4)
    loads = proposer.propose(context)
    assert sum(loads) == 60  # the degenerate one-cycle disposal, by design
    with pytest.raises(ProposerExhausted):
        proposer.propose(context)


def test_release_sweep_is_log_spaced_and_monotonic():
    proposer = ReleaseSweep()
    proposer.reset(1)
    sums = []
    for _ in range(40):
        try:
            sums.append(sum(proposer.propose(make_context(budget=40, total_load=1000.0))))
        except ProposerExhausted:
            break
    assert sums == sorted(sums)
    assert len(set(sums)) == len(sums)  # deduplicated
    # Log spacing puts most probes in the low-S region, where z = ceil(L/S) actually moves.
    assert sums[len(sums) // 2] < 1000.0 / 2


def test_hill_climb_finds_the_optimum_of_a_synthetic_bowl():
    # Convex bowl with its minimum at (7, 7); no plateaus, so this isolates basic descent.
    def cost(loads):
        return (loads[0] - 7) ** 2 + (loads[1] - 7) ** 2

    history = simulate(HillClimb(), cost, budget=60)
    assert min(t.total_cost for t in history) == 0.0


def test_hill_climb_crosses_a_plateau():
    # Flat for every sum below 30, then a cliff down — the shape that stalls a climber which
    # only accepts strict improvements (measured on C3 at L=60).
    def cost(loads):
        return 2.0 if sum(loads) >= 30 else 3.0

    history = simulate(HillClimb(), cost, budget=60)
    assert min(t.total_cost for t in history) == 2.0


# --- edge ---

def test_random_simplex_respects_the_sum_bound_and_floor():
    proposer = RandomSimplex()
    proposer.reset(3)
    context = make_context(node_count=3, mode=AllocationMode.CONTINUOUS, min_allocation=0.1)
    for _ in range(200):
        loads = proposer.propose(context)
        assert 0 < sum(loads) <= context.total_load + 1e-9
        assert all(value == 0 or value >= 0.1 - 1e-9 for value in loads)


def test_random_simplex_differs_across_seeds():
    # Not a determinism claim (D5 withdrew that) — just that the seed is actually wired in.
    def first(seed):
        proposer = RandomSimplex()
        proposer.reset(seed)
        return tuple(proposer.propose(make_context()))

    assert first(1) != first(2)
    assert first(1) == first(1)  # same seed, same process: still reproducible in practice


def test_every_baseline_reports_json_serialisable_params():
    for name, factory in BASELINES.items():
        params = factory().params()
        json.dumps(params)  # lands in JSONB; must round-trip
        assert isinstance(params, dict), name


def test_every_baseline_declares_its_required_mode_and_name():
    for name, factory in BASELINES.items():
        proposer = factory()
        assert proposer.name == name
        assert proposer.requires_mode is ObservationMode.OPAQUE
        assert proposer.version  # feeds rl_runs.strategy_version, the v2.06 grouping key


def test_continuous_mode_allows_fractional_loads():
    context = make_context(mode=AllocationMode.CONTINUOUS, min_allocation=0.1)
    parts = split_equally(15, context)
    assert parts == [7.5, 7.5]  # a floor, not a grid — 7.5 is legal


# --- failure ---

def test_invalid_tunables_are_rejected_at_construction():
    with pytest.raises(ValueError, match="concentration must be > 0"):
        RandomSimplex(concentration=0)
    with pytest.raises(ValueError, match="initial_step_fraction"):
        HillClimb(initial_step_fraction=0)
    with pytest.raises(ValueError, match="initial_step_fraction"):
        HillClimb(initial_step_fraction=1.5)


def test_release_sweep_exhausts_rather_than_repeating():
    proposer = ReleaseSweep()
    proposer.reset(1)
    with pytest.raises(ProposerExhausted):
        for _ in range(500):
            proposer.propose(make_context(budget=10, total_load=20.0))


def test_proposers_module_does_not_import_sqlalchemy():
    import ast

    import flowguard.rl.proposers as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "sqlalchemy" not in imported
    assert math  # keep the import used
