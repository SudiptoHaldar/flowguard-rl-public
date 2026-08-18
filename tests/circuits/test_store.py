"""Tests for flowguard.circuits.store: persistence round-trip against the live DB."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import OperationalError

from flowguard.circuits import Circuit, Node, Polynomial, store
from flowguard.data import database
from flowguard.settings import MissingEnvVarError

REPO_ROOT = Path(__file__).resolve().parents[2]
C1_EXPECTED = (3.0, 55.0, 34.0, 92.0)


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


def unique_name(prefix: str = "test_circuit") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def cleanup(session, name: str) -> None:
    try:
        store.delete_circuit(session, name)
        session.commit()
    except ValueError:
        session.rollback()


# --- expected (db) ---

@pytest.mark.db
def test_c1_database_round_trip(db_session):
    name = unique_name()
    c1 = Circuit.from_config(REPO_ROOT / "config" / "example_circuit.yaml")
    circuit = Circuit(name, c1.nodes(), [n.name for n in c1.ext_nodes()],
                      delay_override=c1.delay_override)
    try:
        store.save_circuit(db_session, circuit)
        db_session.commit()
        loaded = store.load_circuit(db_session, name)
        breakdown = loaded.evaluate(60, {"N1": 10, "N2": 10})
        assert (breakdown.delay, breakdown.overload, breakdown.safety,
                breakdown.total) == C1_EXPECTED
        # C1's config keeps explicit coefficients -> stored as overrides, not NULL.
        row = db_session.scalar(
            select(store.CircuitNodeRow)
            .join(store.CircuitRow)
            .where(store.CircuitRow.name == name,
                   store.CircuitNodeRow.name == "N1")
        )
        assert row.overload_coefficients == [1, 2]
        assert row.safety_coefficients == [1, 2, 3]
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_defaults_only_circuit_stores_nulls(db_session):
    name = unique_name()
    circuit = Circuit(name, [Node("N1", 10, 16)], ["N1"])
    try:
        store.save_circuit(db_session, circuit)
        db_session.commit()
        circuit_row = db_session.scalar(
            select(store.CircuitRow).where(store.CircuitRow.name == name)
        )
        assert circuit_row.delay_coefficients is None
        assert circuit_row.nodes[0].overload_coefficients is None
        assert circuit_row.nodes[0].safety_coefficients is None
        # And the round-trip still evaluates via config defaults.
        assert store.load_circuit(db_session, name).evaluate(
            60, {"N1": 20}).delay == 3.0
    finally:
        cleanup(db_session, name)


# --- edge (db) ---

@pytest.mark.db
def test_external_order_differs_from_declaration_order(db_session):
    name = unique_name()
    nodes = [Node("A", 10, 16), Node("B", 5, 8)]
    circuit = Circuit(name, nodes, ["B", "A"])  # external order reversed
    try:
        store.save_circuit(db_session, circuit)
        db_session.commit()
        loaded = store.load_circuit(db_session, name)
        assert [n.name for n in loaded.ext_nodes()] == ["B", "A"]
        assert [n.name for n in loaded.nodes()] == ["A", "B"]
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_list_names_sorted_and_delete_cascades(db_session):
    name_b, name_a = unique_name("test_b"), unique_name("test_a")
    try:
        store.save_circuit(db_session, Circuit(name_b, [Node("N1", 10, 16)], ["N1"]))
        store.save_circuit(db_session, Circuit(name_a, [Node("N1", 10, 16)], ["N1"]))
        db_session.commit()
        names = store.list_circuit_names(db_session)
        assert names.index(name_a) < names.index(name_b)

        store.delete_circuit(db_session, name_a)
        db_session.commit()
        orphans = db_session.scalars(
            select(store.CircuitNodeRow).join(store.CircuitRow,
                                              isouter=True)
            .where(store.CircuitNodeRow.circuit_id.notin_(
                select(store.CircuitRow.id)))
        ).all()
        assert orphans == []
        with pytest.raises(ValueError, match="does not exist"):
            store.load_circuit(db_session, name_a)
    finally:
        cleanup(db_session, name_a)
        cleanup(db_session, name_b)


# --- failure ---

@pytest.mark.db
def test_duplicate_name_raises(db_session):
    name = unique_name()
    try:
        store.save_circuit(db_session, Circuit(name, [Node("N1", 10, 16)], ["N1"]))
        db_session.commit()
        with pytest.raises(ValueError, match="already exists"):
            store.save_circuit(db_session, Circuit(name, [Node("N1", 10, 16)], ["N1"]))
    finally:
        db_session.rollback()
        cleanup(db_session, name)


@pytest.mark.db
def test_unknown_name_raises_on_load_and_delete(db_session):
    ghost = unique_name("test_ghost")
    with pytest.raises(ValueError, match="does not exist"):
        store.load_circuit(db_session, ghost)
    with pytest.raises(ValueError, match="does not exist"):
        store.delete_circuit(db_session, ghost)


def test_save_rejects_non_circuit():
    with pytest.raises(ValueError, match="expects a Circuit"):
        store.save_circuit(None, "not a circuit")


def test_import_touches_no_engine():
    # store was imported at module top; the autouse fixture reset the cache, and
    # merely importing must not have created an engine.
    assert database._engine is None
