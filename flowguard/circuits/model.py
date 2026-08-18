"""Circuit and node domain model (req_001 v1.01).

A circuit exposes only :meth:`Circuit.ext_nodes` — the external input nodes where a
caller places per-cycle loads — and :meth:`Circuit.evaluate`, which returns the penalty
for disposing of a total load with a given per-cycle assignment. That black-box surface
is what the future RL element optimizes against.

Topology (req_001 v1.03): circuits may carry weighted, acyclic edges. External nodes
are entry points (no incoming edges) and receive assigned per-cycle loads; a split
divides a node's carried load across its outgoing edges by stored weights (which must
sum to 1 per node); a merge sums a node's incoming lines. Every node — external and
internal alike — is penalized on the load it carries. The delay penalty is unaffected
by topology (z depends only on the external assignment). A circuit with no edges
behaves exactly as before v1.03.
"""

from __future__ import annotations

import math
import warnings
from collections import deque
from dataclasses import dataclass

from flowguard.settings import load_config

from . import defaults
from .polynomial import Polynomial


def _require_finite_number(value, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite, got {value!r}")


@dataclass(frozen=True)
class PenaltyBreakdown:
    """Per-category penalties for one load assignment; ``total`` is the RL scalar."""

    delay: float
    overload: float
    safety: float

    @property
    def total(self) -> float:
        return self.delay + self.overload + self.safety


@dataclass(frozen=True)
class Edge:
    """A directed connection; ``weight`` is the fraction of the source's load sent on."""

    source: str
    target: str
    weight: float

    def __post_init__(self):
        for label, value in (("source", self.source), ("target", self.target)):
            if not isinstance(value, str) or not value:
                raise ValueError(f"Edge {label} must be a non-empty string, got {value!r}")
        if self.source == self.target:
            raise ValueError(f"Edge cannot connect '{self.source}' to itself")
        _require_finite_number(
            self.weight, f"weight of edge {self.source}->{self.target}"
        )
        if not 0 < self.weight <= 1:
            raise ValueError(
                f"weight of edge {self.source}->{self.target} must be in (0, 1], "
                f"got {self.weight}"
            )


@dataclass(frozen=True)
class Node:
    """A circuit node. ``None`` overrides mean "use the system default"."""

    name: str
    load_factor: float
    load_safety_cap: float
    overload_override: Polynomial | None = None
    safety_override: Polynomial | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(f"Node name must be a non-empty string, got {self.name!r}")
        _require_finite_number(self.load_factor, f"load_factor of node '{self.name}'")
        _require_finite_number(
            self.load_safety_cap, f"load_safety_cap of node '{self.name}'"
        )
        if self.load_factor <= 0:
            raise ValueError(
                f"load_factor of node '{self.name}' must be > 0, got {self.load_factor}"
            )
        if self.load_safety_cap < self.load_factor:
            raise ValueError(
                f"load_safety_cap of node '{self.name}' ({self.load_safety_cap}) must "
                f"be >= load_factor ({self.load_factor})"
            )


class Circuit:
    """A named set of nodes, a subset of which are external (load-accepting)."""

    def __init__(self, name, nodes, external_nodes, delay_override=None, edges=()):
        if not isinstance(name, str) or not name:
            raise ValueError(f"Circuit name must be a non-empty string, got {name!r}")
        nodes = list(nodes)
        names = [node.name for node in nodes]
        if len(set(names)) != len(names):
            raise ValueError(f"Circuit '{name}' has duplicate node names: {names}")
        external_nodes = list(external_nodes)
        if not external_nodes:
            raise ValueError(f"Circuit '{name}' must expose at least one external node")
        if len(set(external_nodes)) != len(external_nodes):
            raise ValueError(
                f"Circuit '{name}' lists duplicate external nodes: {external_nodes}"
            )
        unknown = [n for n in external_nodes if n not in set(names)]
        if unknown:
            raise ValueError(f"Circuit '{name}' external nodes not defined: {unknown}")
        self.name = name
        self._nodes = {node.name: node for node in nodes}
        self._external = [self._nodes[n] for n in external_nodes]  # declaration order
        self.delay_override = delay_override
        self._edges = tuple(edges)
        self._validate_topology()

    def _validate_topology(self) -> None:
        names = set(self._nodes)
        seen_pairs = set()
        incoming: dict[str, list[Edge]] = {}
        outgoing: dict[str, list[Edge]] = {}
        for edge in self._edges:
            if edge.source not in names:
                raise ValueError(
                    f"edge {edge.source}->{edge.target}: source is not a circuit node"
                )
            if edge.target not in names:
                raise ValueError(
                    f"edge {edge.source}->{edge.target}: target is not a circuit node"
                )
            pair = (edge.source, edge.target)
            if pair in seen_pairs:
                raise ValueError(f"duplicate edge {edge.source}->{edge.target}")
            seen_pairs.add(pair)
            outgoing.setdefault(edge.source, []).append(edge)
            incoming.setdefault(edge.target, []).append(edge)
        external_names = {node.name for node in self._external}
        for target in incoming:
            if target in external_names:
                raise ValueError(
                    f"external node '{target}' cannot have incoming edges "
                    f"(externals are entry points)"
                )
        for source, edges_out in outgoing.items():
            total_weight = sum(edge.weight for edge in edges_out)
            if abs(total_weight - 1.0) > 1e-9:
                raise ValueError(
                    f"outgoing edge weights of node '{source}' must sum to 1, "
                    f"got {total_weight}"
                )
        # Kahn's algorithm: topological order for propagation + acyclicity proof.
        indegree = {name: 0 for name in self._nodes}
        for edge in self._edges:
            indegree[edge.target] += 1
        queue = deque(name for name in self._nodes if indegree[name] == 0)
        order = []
        while queue:
            current = queue.popleft()
            order.append(current)
            for edge in outgoing.get(current, ()):
                indegree[edge.target] -= 1
                if indegree[edge.target] == 0:
                    queue.append(edge.target)
        if len(order) != len(self._nodes):
            cyclic = sorted(set(self._nodes) - set(order))
            raise ValueError(
                f"Circuit '{self.name}' contains a cycle involving: {cyclic}"
            )
        self._topo_order = order
        self._incoming = incoming

    def nodes(self) -> list[Node]:
        """All nodes in declaration order (external and internal alike)."""
        return list(self._nodes.values())

    def ext_nodes(self) -> list[Node]:
        """The exposed input nodes — all an external optimizer gets to see."""
        return list(self._external)

    def edges(self) -> list[Edge]:
        """All edges in declaration order."""
        return list(self._edges)

    def _validate_assignment(self, assignment) -> None:
        """Check an assignment covers exactly the external nodes with non-negative loads.

        Extracted verbatim from :meth:`evaluate` so both entry points raise the same errors in
        the same order; nothing here is new behaviour.
        """
        expected = {node.name for node in self._external}
        unknown = sorted(set(assignment) - expected)
        if unknown:
            raise ValueError(f"assignment names unknown/non-external nodes: {unknown}")
        missing = sorted(expected - set(assignment))
        if missing:
            raise ValueError(f"assignment is missing external nodes: {missing}")
        for node_name, load in assignment.items():
            _require_finite_number(load, f"load for node '{node_name}'")
            if load < 0:
                raise ValueError(f"load for node '{node_name}' must be >= 0, got {load}")

    def _propagate(self, assignment) -> dict:
        """Externals carry their assignment; internals sum weighted incoming lines.

        Resolved in the topological order computed once at construction, so this adds no
        traversal work beyond the accumulation itself.
        """
        carried = {name: 0.0 for name in self._nodes}
        for node in self._external:
            carried[node.name] = float(assignment[node.name])
        for name in self._topo_order:
            for edge in self._incoming.get(name, ()):
                carried[name] += edge.weight * carried[edge.source]
        return carried

    def carried_loads(self, assignment) -> dict:
        """Load each node carries under ``assignment`` — the propagation, returned.

        :meth:`evaluate` has always computed this internally on its way to a penalty; this
        exposes it so a caller that wants *where the load goes* need not re-derive the rule.
        Both use :meth:`_propagate`, so there is one implementation, not two.

        Deliberately takes no ``total_load``: carried load is a property of the assignment and
        the graph, not of how many cycles the total implies.

        On a flat circuit (no edges) the result is the assignment itself, with every
        non-external node at zero.
        """
        self._validate_assignment(assignment)
        return self._propagate(assignment)

    def evaluate(self, total_load, assignment) -> PenaltyBreakdown:
        """Penalty for disposing of ``total_load`` with per-cycle loads ``assignment``.

        ``assignment`` maps every external node name to its per-cycle load (explicit 0
        allowed). The assignment repeats for ``z = ceil(total_load / load_per_cycle)``
        cycles, where ``load_per_cycle`` is the sum of assigned loads.
        """
        _require_finite_number(total_load, "total_load")
        if total_load <= 0:
            raise ValueError(f"total_load must be > 0, got {total_load}")
        self._validate_assignment(assignment)
        load_per_cycle = sum(assignment.values())
        if load_per_cycle <= 0:
            raise ValueError("assignment must place a positive total per-cycle load")

        cycles = math.ceil(total_load / load_per_cycle)
        delay_fn = self.delay_override or defaults.default_delay()
        delay = delay_fn.evaluate(cycles)

        carried = self._propagate(assignment)

        overload = 0.0
        safety = 0.0
        for node in self.nodes():  # every node is penalized on its carried load
            overload_fn = node.overload_override or defaults.default_overload()
            safety_fn = node.safety_override or defaults.default_safety()
            if safety_fn.degree < overload_fn.degree:
                warnings.warn(
                    f"Node '{node.name}': safety penalty (degree {safety_fn.degree}) "
                    f"is less steep than overload penalty (degree "
                    f"{overload_fn.degree}); the plan requires safety to be the more "
                    f"prohibitive function",
                    UserWarning,
                    stacklevel=2,
                )
            load = carried[node.name]
            overload += overload_fn.evaluate(max(0.0, load - node.load_factor))
            safety += safety_fn.evaluate(max(0.0, load - node.load_safety_cap))
        return PenaltyBreakdown(delay=delay, overload=overload, safety=safety)

    @classmethod
    def from_dict(cls, data: dict) -> "Circuit":
        """Build from the ``circuit:`` mapping shape of ``config/example_circuit.yaml``.

        The ``*_penalty_coefficients`` keys are optional: absent means "use the system
        default", present means override (even if numerically equal to the default).
        """

        def optional_polynomial(mapping: dict, key: str) -> Polynomial | None:
            coefficients = mapping.get(key)
            if coefficients is None:
                return None
            return Polynomial.from_list(coefficients)

        nodes = [
            Node(
                name=node_data["name"],
                load_factor=node_data["load_factor"],
                load_safety_cap=node_data["load_safety_cap"],
                overload_override=optional_polynomial(
                    node_data, "overload_penalty_coefficients"
                ),
                safety_override=optional_polynomial(
                    node_data, "safety_penalty_coefficients"
                ),
            )
            for node_data in data["nodes"]
        ]
        edges = tuple(
            Edge(source=e["from"], target=e["to"], weight=e["weight"])
            for e in data.get("edges", ())
        )
        return cls(
            name=data["name"],
            nodes=nodes,
            external_nodes=data["external_nodes"],
            delay_override=optional_polynomial(data, "delay_penalty_coefficients"),
            edges=edges,
        )

    @classmethod
    def from_config(cls, path) -> "Circuit":
        return cls.from_dict(load_config(path)["circuit"])
