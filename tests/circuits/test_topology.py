"""Tests for DAG topology (req_001 v1.03): Edge, propagation, validation, C4 fixture."""

from pathlib import Path

import pytest

from flowguard.circuits import Circuit, Edge, Node, defaults

REPO_ROOT = Path(__file__).resolve().parents[2]

# C4 canonical acceptance (see config/example_dag_circuit.yaml header).
C4_EXPECTED = (2.0, 42.0, 15.0, 59.0)


@pytest.fixture(autouse=True)
def clean_defaults_cache():
    defaults.reset()
    yield
    defaults.reset()


def build_c4() -> Circuit:
    return Circuit.from_config(REPO_ROOT / "config" / "example_dag_circuit.yaml")


# --- expected: the C4 diagram fixture ---

def test_c4_from_yaml_exact_numbers():
    breakdown = build_c4().evaluate(60, {"N1": 10, "N2": 10, "N3": 10})
    assert (breakdown.delay, breakdown.overload, breakdown.safety,
            breakdown.total) == C4_EXPECTED


def test_c4_structure():
    c4 = build_c4()
    assert [n.name for n in c4.ext_nodes()] == ["N1", "N2", "N3"]
    assert len(c4.nodes()) == 7
    assert len(c4.edges()) == 6
    assert c4.edges()[0] == Edge("N1", "N4", 0.4)


def test_merge_sums_incoming_lines():
    # A and B both forward 100% into M: M carries 4 + 4 = 8; factor 5 -> x=3 -> f1=21.
    nodes = [Node("A", 10, 16), Node("B", 10, 16), Node("M", 5, 8)]
    circuit = Circuit("C", nodes, ["A", "B"],
                      edges=[Edge("A", "M", 1.0), Edge("B", "M", 1.0)])
    breakdown = circuit.evaluate(8, {"A": 4, "B": 4})
    assert breakdown.overload == 21.0
    assert breakdown.delay == 1.0


def test_split_divides_by_weights():
    # A=8 splits 0.25/0.75 -> M1 carries 2, M2 carries 6; factors make only M2 overload.
    nodes = [Node("A", 10, 16), Node("M1", 4, 8), Node("M2", 5, 8)]
    circuit = Circuit("C", nodes, ["A"],
                      edges=[Edge("A", "M1", 0.25), Edge("A", "M2", 0.75)])
    breakdown = circuit.evaluate(8, {"A": 8})
    # M2: x = 6 - 5 = 1 -> f1(1) = 3; M1 and A within factor.
    assert breakdown.overload == pytest.approx(3.0)
    assert breakdown.safety == 0.0


def test_multi_hop_propagation():
    # A -> M -> T chain: T carries what M forwards.
    nodes = [Node("A", 10, 16), Node("M", 10, 16), Node("T", 2, 8)]
    circuit = Circuit("C", nodes, ["A"],
                      edges=[Edge("A", "M", 1.0), Edge("M", "T", 1.0)])
    breakdown = circuit.evaluate(6, {"A": 6})
    # T: x = 6 - 2 = 4 -> f1(4) = 4 + 32 = 36.
    assert breakdown.overload == pytest.approx(36.0)


# --- edge ---

def test_no_edges_circuit_behaves_as_before():
    nodes = [Node("N1", 10, 16), Node("N2", 5, 8)]
    with_edges_arg = Circuit("C", nodes, ["N1", "N2"], edges=())
    breakdown = with_edges_arg.evaluate(60, {"N1": 10, "N2": 10})
    # Same numbers the pre-v1.03 defaults-only path produces (current defaults).
    legacy = Circuit("C", nodes, ["N1", "N2"]).evaluate(60, {"N1": 10, "N2": 10})
    assert breakdown == legacy


def test_unreached_internal_node_carries_zero():
    nodes = [Node("A", 10, 16), Node("Z", 1, 1)]
    breakdown = Circuit("C", nodes, ["A"]).evaluate(10, {"A": 5})
    assert breakdown.overload == 0.0
    assert breakdown.safety == 0.0


def test_external_may_branch_and_still_be_penalized():
    # A carries its assignment (12 > factor 10 -> f1(2) = 10) AND forwards it.
    nodes = [Node("A", 10, 16), Node("M", 20, 30)]
    circuit = Circuit("C", nodes, ["A"], edges=[Edge("A", "M", 1.0)])
    assert circuit.evaluate(12, {"A": 12}).overload == pytest.approx(10.0)


def test_edge_weight_exactly_one_is_valid():
    assert Edge("A", "B", 1.0).weight == 1.0


# --- failure: Edge validation ---

@pytest.mark.parametrize(
    "source, target, weight",
    [
        ("A", "A", 0.5),          # self-edge
        ("", "B", 0.5),           # empty source
        ("A", "B", 0.0),          # zero weight
        ("A", "B", 1.2),          # weight > 1
        ("A", "B", float("nan")),  # non-finite
    ],
)
def test_invalid_edge_raises(source, target, weight):
    with pytest.raises(ValueError):
        Edge(source, target, weight)


# --- failure: Circuit topology validation ---

def _two_nodes():
    return [Node("A", 10, 16), Node("B", 5, 8)]


def test_edge_endpoint_must_exist():
    with pytest.raises(ValueError, match="not a circuit node"):
        Circuit("C", _two_nodes(), ["A"], edges=[Edge("A", "X", 1.0)])


def test_duplicate_edge_rejected():
    with pytest.raises(ValueError, match="duplicate edge"):
        Circuit("C", _two_nodes(), ["A"],
                edges=[Edge("A", "B", 0.5), Edge("A", "B", 0.5)])


def test_weights_must_sum_to_one():
    nodes = [Node("A", 10, 16), Node("B", 5, 8), Node("C1", 5, 8)]
    with pytest.raises(ValueError, match="must sum to 1"):
        Circuit("C", nodes, ["A"],
                edges=[Edge("A", "B", 0.5), Edge("A", "C1", 0.4)])


def test_external_cannot_have_incoming_edges():
    with pytest.raises(ValueError, match="cannot have incoming edges"):
        Circuit("C", _two_nodes(), ["A", "B"], edges=[Edge("B", "A", 1.0)])


def test_cycle_rejected():
    nodes = [Node("A", 10, 16), Node("B", 5, 8), Node("C1", 5, 8)]
    with pytest.raises(ValueError, match="cycle"):
        Circuit("C", nodes, ["A"],
                edges=[Edge("A", "B", 1.0), Edge("B", "C1", 1.0),
                       Edge("C1", "B", 1.0)])
