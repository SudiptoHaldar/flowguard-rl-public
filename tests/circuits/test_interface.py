"""Tests for flowguard.circuits.interface: the opaque RL-facing surface."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from flowguard.circuits import Circuit, Node, PenaltyBreakdown, interface, store
from flowguard.data import database
from flowguard.settings import MissingEnvVarError

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def clean_caches():
    interface.clear_cache()
    database.reset_engine()
    yield
    interface.clear_cache()
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


def unique_name(prefix: str = "test_iface") -> str:
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
def test_ext_nodes_returns_names_only(db_session):
    name = unique_name()
    try:
        save_c1_copy(db_session, name)
        names = interface.ext_nodes(name)
        assert names == ["N1", "N2"]
        assert all(isinstance(n, str) for n in names)
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_evaluate_default_returns_bare_float(db_session):
    name = unique_name()
    try:
        save_c1_copy(db_session, name)
        result = interface.evaluate(name, 60, [10, 10])
        assert result == 92.0
        assert isinstance(result, float)
        assert not isinstance(result, PenaltyBreakdown)
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_evaluate_breakdown_flag_returns_breakdown(db_session):
    name = unique_name()
    try:
        save_c1_copy(db_session, name)
        result = interface.evaluate(name, 60, [10, 10], breakdown=True)
        assert result == PenaltyBreakdown(delay=3.0, overload=55.0, safety=34.0)
    finally:
        cleanup(db_session, name)


# --- edge (db) ---

@pytest.mark.db
def test_loads_map_positionally_onto_external_order(db_session):
    name = unique_name()
    nodes = [Node("A", 10, 16), Node("B", 5, 8)]
    try:
        store.save_circuit(db_session, Circuit(name, nodes, ["B", "A"]))
        db_session.commit()
        assert interface.ext_nodes(name) == ["B", "A"]
        # First load (20) goes to B: overload f1(15)=465, delay 1, and the default
        # safety f2(12) = 12+288+5184+82944+1244160 = 1332588.
        result = interface.evaluate(name, 20, [20, 0], breakdown=True)
        assert (result.overload, result.safety) == (465.0, 1332588.0)
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_circuit_is_cached_until_cleared(db_session):
    name = unique_name()
    try:
        save_c1_copy(db_session, name)
        assert interface.evaluate(name, 60, [10, 10]) == 92.0  # fills the cache
        store.delete_circuit(db_session, name)
        db_session.commit()
        # Still served from the per-process cache after DB deletion:
        assert interface.evaluate(name, 60, [10, 10]) == 92.0
        interface.clear_cache()
        with pytest.raises(ValueError, match="does not exist"):
            interface.evaluate(name, 60, [10, 10])
    finally:
        cleanup(db_session, name)


# --- failure ---

@pytest.mark.db
def test_wrong_load_count_raises(db_session):
    name = unique_name()
    try:
        save_c1_copy(db_session, name)
        with pytest.raises(ValueError, match="2 external nodes, got 3 loads"):
            interface.evaluate(name, 60, [10, 10, 10])
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_unknown_circuit_raises_and_is_not_cached(db_session):
    ghost = unique_name("test_ghost")
    with pytest.raises(ValueError, match="does not exist"):
        interface.ext_nodes(ghost)
    assert ghost not in interface._cache


def test_import_touches_no_engine():
    assert database._engine is None
