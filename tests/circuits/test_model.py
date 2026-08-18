"""Tests for flowguard.circuits.model: the C1 fixture, overrides, validation."""

import warnings
from pathlib import Path

import pytest

from flowguard.circuits import Circuit, Node, Polynomial, defaults
from flowguard.circuits.model import Edge

REPO_ROOT = Path(__file__).resolve().parents[2]

# The plan's C1: evaluate(60, {N1: 10, N2: 10}) -> delay 3, overload 55, safety 34.
C1_EXPECTED = (3.0, 55.0, 34.0, 92.0)


@pytest.fixture(autouse=True)
def clean_defaults_cache():
    defaults.reset()
    yield
    defaults.reset()


def build_c1_explicit() -> Circuit:
    f1 = Polynomial.from_list([1, 2])
    f2 = Polynomial.from_list([1, 2, 3])
    nodes = [
        Node("N1", load_factor=10, load_safety_cap=16,
             overload_override=f1, safety_override=f2),
        Node("N2", load_factor=5, load_safety_cap=8,
             overload_override=f1, safety_override=f2),
    ]
    return Circuit("C1", nodes, ["N1", "N2"],
                   delay_override=Polynomial.from_list([1]))


def build_c1_defaults_only() -> Circuit:
    nodes = [
        Node("N1", load_factor=10, load_safety_cap=16),
        Node("N2", load_factor=5, load_safety_cap=8),
    ]
    return Circuit("C1", nodes, ["N1", "N2"])


def assert_c1_numbers(circuit: Circuit):
    breakdown = circuit.evaluate(60, {"N1": 10, "N2": 10})
    assert (breakdown.delay, breakdown.overload, breakdown.safety,
            breakdown.total) == C1_EXPECTED


# --- expected: the C1 fixture, three construction paths ---

def test_c1_explicit_construction():
    assert_c1_numbers(build_c1_explicit())


def test_c1_from_config():
    assert_c1_numbers(Circuit.from_config(REPO_ROOT / "config" / "example_circuit.yaml"))


def test_c1_defaults_only():
    # C1's shape (factors/caps) with NO overrides — so every penalty comes from
    # config/circuit_defaults.yaml. Since 2026-08-16 the default safety ([1,2,3,4,5]) is
    # deliberately steeper than C1's explicit override ([1,2,3]), so these numbers differ
    # from the C1 fixture on the safety term alone: f2(2) = 2+8+24+64+160 = 258.
    breakdown = build_c1_defaults_only().evaluate(60, {"N1": 10, "N2": 10})
    assert (breakdown.delay, breakdown.overload, breakdown.safety,
            breakdown.total) == (3.0, 55.0, 258.0, 316.0)


def test_ext_nodes_returns_external_nodes_in_declaration_order():
    circuit = build_c1_defaults_only()
    assert [node.name for node in circuit.ext_nodes()] == ["N1", "N2"]
    assert all(isinstance(node, Node) for node in circuit.ext_nodes())


# --- edge ---

def test_explicit_zero_load_on_external_node_is_valid():
    breakdown = build_c1_defaults_only().evaluate(60, {"N1": 20, "N2": 0})
    # lpc 20 -> z 3 -> delay 3; N1: x=10 -> f1=210, y=4 -> default f2(4) = 4+32+192+1024+5120
    # = 6372; N2 idle -> 0.
    assert breakdown.delay == 3.0
    assert breakdown.overload == 210.0
    assert breakdown.safety == 6372.0


def test_cycles_round_up():
    # total 61 over 20/cycle -> ceil = 4 cycles.
    assert build_c1_defaults_only().evaluate(61, {"N1": 10, "N2": 10}).delay == 4.0


def test_c1_produces_no_warnings():
    # Neither construction may trip the safety-steeper heuristic: C1's explicit f2 (degree 3)
    # and the system default f2 (degree 5) both out-rank the overload degree of 2.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert_c1_numbers(build_c1_explicit())
        build_c1_defaults_only().evaluate(60, {"N1": 10, "N2": 10})


def test_less_steep_safety_override_warns():
    node = Node("N1", load_factor=10, load_safety_cap=16,
                safety_override=Polynomial.from_list([9]))  # degree 1 < default overload 2
    circuit = Circuit("C", [node], ["N1"])
    with pytest.warns(UserWarning, match="N1"):
        circuit.evaluate(10, {"N1": 10})


def test_overrides_resolve_at_evaluation_time(tmp_path, monkeypatch):
    circuit = build_c1_defaults_only()  # built BEFORE the config switch
    tweaked = tmp_path / "circuit_defaults.yaml"
    tweaked.write_text(
        "overload_penalty_coefficients: [1, 2]\n"
        "safety_penalty_coefficients: [1, 2, 3]\n"
        "delay_penalty_coefficients: [2]\n",  # f3(z) = 2z
        encoding="utf-8",
    )
    monkeypatch.setattr(defaults, "_CONFIG_PATH", tweaked)
    defaults.reset()
    assert circuit.evaluate(60, {"N1": 10, "N2": 10}).delay == 6.0


def test_override_equal_to_default_behaves_identically():
    # Tests the property directly rather than relying on C1's coefficients happening to
    # equal the system defaults — a coincidence that ended when the default safety became
    # [1, 2, 3, 4, 5] on 2026-08-16.
    nodes_explicit = [
        Node("N1", load_factor=10, load_safety_cap=16,
             overload_override=Polynomial.from_list(defaults.default_overload().as_list()),
             safety_override=Polynomial.from_list(defaults.default_safety().as_list())),
        Node("N2", load_factor=5, load_safety_cap=8,
             overload_override=Polynomial.from_list(defaults.default_overload().as_list()),
             safety_override=Polynomial.from_list(defaults.default_safety().as_list())),
    ]
    explicit = Circuit(
        "C", nodes_explicit, ["N1", "N2"],
        delay_override=Polynomial.from_list(defaults.default_delay().as_list()),
    ).evaluate(60, {"N1": 10, "N2": 10})
    implicit = build_c1_defaults_only().evaluate(60, {"N1": 10, "N2": 10})
    assert explicit == implicit


# --- failure: evaluate() validation ---

@pytest.mark.parametrize(
    "total_load, assignment, match",
    [
        (60, {"N1": 10}, "missing external nodes"),
        (60, {"N1": 10, "N2": 10, "N9": 1}, "unknown"),
        (60, {"N1": -1, "N2": 10}, "must be >= 0"),
        (60, {"N1": 0, "N2": 0}, "positive total per-cycle load"),
        (0, {"N1": 10, "N2": 10}, "total_load"),
        (-5, {"N1": 10, "N2": 10}, "total_load"),
        (60, {"N1": float("nan"), "N2": 10}, "finite"),
    ],
)
def test_evaluate_rejects_invalid_input(total_load, assignment, match):
    with pytest.raises(ValueError, match=match):
        build_c1_defaults_only().evaluate(total_load, assignment)


# --- failure: construction validation ---

def test_node_rejects_cap_below_factor():
    with pytest.raises(ValueError, match="load_safety_cap"):
        Node("N1", load_factor=10, load_safety_cap=9)


def test_node_rejects_non_positive_load_factor():
    with pytest.raises(ValueError, match="load_factor"):
        Node("N1", load_factor=0, load_safety_cap=5)


def test_circuit_rejects_duplicate_node_names():
    nodes = [Node("N1", 10, 16), Node("N1", 5, 8)]
    with pytest.raises(ValueError, match="duplicate"):
        Circuit("C", nodes, ["N1"])


def test_circuit_rejects_unknown_external_node():
    with pytest.raises(ValueError, match="not defined"):
        Circuit("C", [Node("N1", 10, 16)], ["N1", "N9"])


def test_circuit_rejects_empty_external_list():
    with pytest.raises(ValueError, match="at least one external"):
        Circuit("C", [Node("N1", 10, 16)], [])


# --- carried_loads (req_003 v3.07 D1) ---------------------------------------------------


def build_c4_dag() -> Circuit:
    """The shipped C4 shape: three externals feeding four internals, with two merges."""
    nodes = [
        Node("N1", 13, 18),
        Node("N2", 7, 10),
        Node("N3", 17, 20),
        Node("N4", 4, 7),
        Node("N5", 10, 12),
        Node("N6", 15, 20),
        Node("N7", 2, 3),
    ]
    edges = [
        Edge("N1", "N4", 0.4),
        Edge("N1", "N5", 0.6),
        Edge("N2", "N5", 0.7),
        Edge("N2", "N6", 0.3),
        Edge("N3", "N6", 0.8),
        Edge("N3", "N7", 0.2),
    ]
    return Circuit("C4t", nodes, ["N1", "N2", "N3"], edges=edges)


def test_carried_loads_propagates_through_the_dag():
    """The measured figures for C4's optimum — the numbers the topology view renders."""
    carried = build_c4_dag().carried_loads({"N1": 13, "N2": 6, "N3": 17})

    assert carried["N1"] == 13.0
    assert carried["N2"] == 6.0
    assert carried["N3"] == 17.0
    assert carried["N4"] == pytest.approx(5.2)
    # N5 merges N1 and N2 and lands exactly on its safety cap of 12 — the binding constraint.
    assert carried["N5"] == pytest.approx(12.0)
    assert carried["N6"] == pytest.approx(15.4)
    # N7 sits above its cap of 3: the optimum knowingly pays a safety penalty here.
    assert carried["N7"] == pytest.approx(3.4)


def test_carried_loads_needs_no_total_load():
    """Carried load is a property of the assignment and the graph, not of the cycle count."""
    circuit = build_c4_dag()
    once = circuit.carried_loads({"N1": 13, "N2": 6, "N3": 17})
    # Same assignment, wildly different totals -> evaluate differs, carried load does not.
    assert circuit.evaluate(60, {"N1": 13, "N2": 6, "N3": 17}).delay != circuit.evaluate(
        10000, {"N1": 13, "N2": 6, "N3": 17}
    ).delay
    assert once == circuit.carried_loads({"N1": 13, "N2": 6, "N3": 17})


def test_carried_loads_on_a_flat_circuit_is_the_assignment():
    assert build_c1_defaults_only().carried_loads({"N1": 10, "N2": 10}) == {
        "N1": 10.0,
        "N2": 10.0,
    }


def test_carried_loads_validates_like_evaluate():
    circuit = build_c1_defaults_only()
    with pytest.raises(ValueError, match="unknown/non-external"):
        circuit.carried_loads({"N1": 10, "N9": 1})
    with pytest.raises(ValueError, match="missing external nodes"):
        circuit.carried_loads({"N1": 10})
    with pytest.raises(ValueError, match="must be >= 0"):
        circuit.carried_loads({"N1": 10, "N2": -1})


def test_evaluate_is_unchanged_by_the_extraction():
    """The regression that matters: req_001 is a closed group and every RL number rests here.

    Penalties and the *order* of validation errors must both be exactly as before the
    propagation was extracted into `carried_loads`.
    """
    # The explicit-override C1 — the plan's worked example, and the figure every later
    # acceptance criterion quotes. (The defaults-only build uses the steeper system safety
    # polynomial and is asserted separately above.)
    circuit = build_c1_explicit()
    breakdown = circuit.evaluate(60, {"N1": 10, "N2": 10})
    assert (breakdown.delay, breakdown.overload, breakdown.safety, breakdown.total) == C1_EXPECTED

    circuit = build_c1_defaults_only()
    # total_load is rejected before anything about the assignment is examined...
    with pytest.raises(ValueError, match="total_load must be > 0"):
        circuit.evaluate(0, {"N1": 10, "N9": 1})
    # ...then unknown names, then missing ones, then negative loads.
    with pytest.raises(ValueError, match="unknown/non-external"):
        circuit.evaluate(60, {"N1": 10, "N2": 10, "N9": 1})
    with pytest.raises(ValueError, match="missing external nodes"):
        circuit.evaluate(60, {"N1": 10})
    with pytest.raises(ValueError, match="must be >= 0"):
        circuit.evaluate(60, {"N1": 10, "N2": -1})
    # ...and only then the per-cycle total.
    with pytest.raises(ValueError, match="positive total per-cycle load"):
        circuit.evaluate(60, {"N1": 0, "N2": 0})


def test_evaluate_and_carried_loads_agree_on_the_dag():
    """One implementation, not two: the penalty path and the accessor see the same loads."""
    circuit = build_c4_dag()
    assignment = {"N1": 13, "N2": 6, "N3": 17}
    carried = circuit.carried_loads(assignment)
    # N7 is over its cap, so evaluate must report a non-zero safety term for this assignment.
    assert carried["N7"] > 3
    assert circuit.evaluate(10000, assignment).safety > 0
