"""Tests for flowguard.circuits.cli: describe/evaluate/save/list + ordering contract."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from flowguard.circuits import Circuit, Node, cli, store
from flowguard.data import database
from flowguard.settings import MissingEnvVarError

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def clean_engine_cache():
    database.reset_engine()
    yield
    database.reset_engine()


@pytest.fixture
def db_session():
    """Live session; skips when the DB is unreachable or the tables are missing."""
    try:
        engine = database.get_engine()
        inspector = inspect(engine)
        has_tables = inspector.has_table("circuits") and inspector.has_table(
            "circuit_nodes"
        )
    except (MissingEnvVarError, OperationalError) as exc:
        pytest.skip(f"database unreachable: {exc.__class__.__name__}")
    if not has_tables:
        pytest.skip("circuit tables missing — run: alembic upgrade head")
    session = database.get_session_factory()()
    yield session
    session.rollback()
    session.close()


def unique_name(prefix: str = "test_cli") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def cleanup(session, name: str) -> None:
    try:
        store.delete_circuit(session, name)
        session.commit()
    except ValueError:
        session.rollback()


def save_c1_copy(session, name: str) -> None:
    c1 = Circuit.from_config(REPO_ROOT / "config" / "example_circuit.yaml")
    copy = Circuit(name, c1.nodes(), [n.name for n in c1.ext_nodes()],
                   delay_override=c1.delay_override)
    store.save_circuit(session, copy)
    session.commit()


# --- expected (db) ---

@pytest.mark.db
def test_describe_lists_externals_in_order(db_session):
    name = unique_name()
    try:
        save_c1_copy(db_session, name)
        output = cli.cmd_describe(db_session, name)
        lines = output.splitlines()
        assert lines[0] == f"circuit: {name}"
        assert "[0] N1" in lines[3] and "load_factor=10" in lines[3]
        assert "[1] N2" in lines[4] and "load_safety_cap=8" in lines[4]
        assert "override [1, 2]" in lines[3]  # C1 keeps explicit coefficients
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_evaluate_positional_c1_numbers(db_session):
    name = unique_name()
    try:
        save_c1_copy(db_session, name)
        output = cli.cmd_evaluate(db_session, name, 60, [10, 10])
        assert "total=92.0" in output
        assert "delay=3.0" in output and "overload=55.0" in output
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_save_with_name_override_round_trips(db_session):
    name = unique_name()
    try:
        output = cli.cmd_save(
            db_session, str(REPO_ROOT / "config" / "example_circuit.yaml"), name=name
        )
        db_session.commit()
        assert f"saved '{name}'" in output
        assert name in cli.cmd_list(db_session).splitlines()
    finally:
        cleanup(db_session, name)


# --- edge (db): ordering contract ---

@pytest.mark.db
def test_describe_stable_across_fresh_sessions(db_session):
    name = unique_name()
    nodes = [Node("A", 10, 16), Node("B", 5, 8)]
    try:
        store.save_circuit(db_session, Circuit(name, nodes, ["B", "A"]))
        db_session.commit()
        first = cli.cmd_describe(db_session, name)
        fresh = database.get_session_factory()()
        try:
            second = cli.cmd_describe(fresh, name)
        finally:
            fresh.close()
        assert first == second
        assert "[0] B" in first and "[1] A" in first  # definition order, not declaration
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_evaluate_maps_loads_onto_external_order(db_session):
    name = unique_name()
    nodes = [Node("A", 10, 16), Node("B", 5, 8)]
    try:
        store.save_circuit(db_session, Circuit(name, nodes, ["B", "A"]))
        db_session.commit()
        # First load (20) goes to B (factor 5, cap 8): x=15 -> f1=465,
        # y=12 -> default f2(12) = 12+288+5184+82944+1244160 = 1332588.
        output = cli.cmd_evaluate(db_session, name, 20, [20, 0])
        assert "overload=465.0" in output
        assert "safety=1332588.0" in output
    finally:
        cleanup(db_session, name)


# --- failure ---

@pytest.mark.db
def test_evaluate_wrong_load_count_raises(db_session):
    name = unique_name()
    try:
        save_c1_copy(db_session, name)
        with pytest.raises(ValueError, match="2 external nodes, got 1 loads"):
            cli.cmd_evaluate(db_session, name, 60, [10])
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_main_unknown_circuit_exits_1(db_session, capsys):
    ghost = unique_name("test_ghost")
    assert cli.main(["describe", ghost]) == 1
    assert f"error: circuit '{ghost}' does not exist" in capsys.readouterr().err


def test_main_argparse_shortfall_exits_2():
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["evaluate", "x"])  # missing total_load and loads; no DB needed
    assert excinfo.value.code == 2


def test_import_touches_no_engine():
    assert database._engine is None
