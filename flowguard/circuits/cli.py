"""Command-line interface for persisted circuits (req_001 v1.05).

Usage (from the repo root, venv active):

    python -m flowguard.circuits describe C2
    python -m flowguard.circuits evaluate C2 60 10 10
    python -m flowguard.circuits save config/example_circuit.yaml --name C2
    python -m flowguard.circuits list

Ordering contract: external nodes appear in definition order (persisted as
``external_position``), identical across calls and processes. ``evaluate`` assigns its
load arguments positionally onto that order and requires exactly one load per external
node.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.exc import OperationalError

from flowguard.data.database import get_session_factory
from flowguard.settings import MissingEnvVarError

from . import store
from .model import Circuit
from .polynomial import Polynomial


def _fmt(polynomial: Polynomial | None) -> str:
    return f"override {polynomial.as_list()}" if polynomial is not None else "default"


def cmd_describe(session, name: str) -> str:
    circuit = store.load_circuit(session, name)
    lines = [
        f"circuit: {circuit.name}",
        f"delay: {_fmt(circuit.delay_override)}",
        "external nodes (stable order):",
    ]
    for position, node in enumerate(circuit.ext_nodes()):
        lines.append(
            f"  [{position}] {node.name}  load_factor={node.load_factor}  "
            f"load_safety_cap={node.load_safety_cap}  "
            f"overload={_fmt(node.overload_override)}  "
            f"safety={_fmt(node.safety_override)}"
        )
    external_names = {node.name for node in circuit.ext_nodes()}
    internals = [node for node in circuit.nodes() if node.name not in external_names]
    if internals:
        lines.append("internal nodes:")
        for node in internals:
            lines.append(
                f"  {node.name}  load_factor={node.load_factor}  "
                f"load_safety_cap={node.load_safety_cap}  "
                f"overload={_fmt(node.overload_override)}  "
                f"safety={_fmt(node.safety_override)}"
            )
    if circuit.edges():
        lines.append("edges:")
        for edge in circuit.edges():
            lines.append(f"  {edge.source} -> {edge.target}  weight={edge.weight}")
    return "\n".join(lines)


def cmd_evaluate(session, name: str, total_load: float, loads: list[float]) -> str:
    circuit = store.load_circuit(session, name)
    externals = circuit.ext_nodes()
    if len(loads) != len(externals):
        raise ValueError(
            f"circuit '{name}' has {len(externals)} external nodes, "
            f"got {len(loads)} loads"
        )
    assignment = {node.name: load for node, load in zip(externals, loads)}
    breakdown = circuit.evaluate(total_load, assignment)
    return (
        f"delay={breakdown.delay} overload={breakdown.overload} "
        f"safety={breakdown.safety} total={breakdown.total}"
    )


def cmd_save(session, yaml_path: str, name: str | None = None) -> str:
    circuit = Circuit.from_config(yaml_path)
    if name and name != circuit.name:
        circuit = Circuit(
            name,
            circuit.nodes(),
            [node.name for node in circuit.ext_nodes()],
            delay_override=circuit.delay_override,
        )
    circuit_id = store.save_circuit(session, circuit)
    return f"saved '{circuit.name}' (id {circuit_id})"


def cmd_list(session) -> str:
    return "\n".join(store.list_circuit_names(session))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m flowguard.circuits",
        description="Inspect and exercise persisted flowguard circuits.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    describe = sub.add_parser("describe", help="show a circuit's external nodes")
    describe.add_argument("name")

    evaluate = sub.add_parser(
        "evaluate", help="evaluate a positional load assignment"
    )
    evaluate.add_argument("name")
    evaluate.add_argument("total_load", type=float)
    evaluate.add_argument("loads", type=float, nargs="+",
                          help="one per external node, in stable order")

    save = sub.add_parser("save", help="persist a circuit from a YAML definition")
    save.add_argument("yaml_path")
    save.add_argument("--name", help="override the name in the file")

    sub.add_parser("list", help="list persisted circuit names")
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)  # argparse errors need no DB
    try:
        session = get_session_factory()()
    except (MissingEnvVarError, OperationalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        if args.command == "describe":
            output = cmd_describe(session, args.name)
        elif args.command == "evaluate":
            output = cmd_evaluate(session, args.name, args.total_load, args.loads)
        elif args.command == "save":
            output = cmd_save(session, args.yaml_path, args.name)
            session.commit()
        else:
            output = cmd_list(session)
        print(output)
        return 0
    except (ValueError, FileNotFoundError, MissingEnvVarError, OperationalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()
