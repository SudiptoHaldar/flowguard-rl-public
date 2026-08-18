"""Tests for DAG persistence + surfaces (req_001 v1.03): round-trip, cascade, CLI, interface."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import OperationalError

from flowguard.circuits import Circuit, PenaltyBreakdown, cli, interface, store
from flowguard.data import database
from flowguard.settings import MissingEnvVarError

REPO_ROOT = Path(__file__).resolve().parents[2]

C4_EXPECTED = (2.0, 42.0, 15.0, 59.0)


@pytest.fixture(autouse=True)
def clean_caches():
    interface.clear_cache()
    database.reset_engine()
    yield
    interface.clear_cache()
    database.reset_engine()


@pytest.fixture
def db_session():
    """Live session; skips when the DB is unreachable or the edges table is missing."""
    try:
        engine = database.get_engine()
        inspector = inspect(engine)
        has_tables = inspector.has_table("circuits") and inspector.has_table(
            "circuit_edges"
        )
    except (MissingEnvVarError, OperationalError) as exc:
        pytest.skip(f"database unreachable: {exc.__class__.__name__}")
    if not has_tables:
        pytest.skip("circuit tables missing — run: alembic upgrade head")
    session = database.get_session_factory()()
    yield session
    session.rollback()
    session.close()


def unique_name(prefix: str = "test_dag") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def cleanup(session, name: str) -> None:
    try:
        store.delete_circuit(session, name)
        session.commit()
    except ValueError:
        session.rollback()


def save_c4_copy(session, name: str) -> None:
    c4 = Circuit.from_config(REPO_ROOT / "config" / "example_dag_circuit.yaml")
    copy = Circuit(name, c4.nodes(), [n.name for n in c4.ext_nodes()],
                   delay_override=c4.delay_override, edges=c4.edges())
    store.save_circuit(session, copy)
    session.commit()


# --- expected (db) ---

@pytest.mark.db
def test_c4_database_round_trip(db_session):
    name = unique_name()
    try:
        save_c4_copy(db_session, name)
        loaded = store.load_circuit(db_session, name)
        assert len(loaded.edges()) == 6
        breakdown = loaded.evaluate(60, {"N1": 10, "N2": 10, "N3": 10})
        assert (breakdown.delay, breakdown.overload, breakdown.safety,
                breakdown.total) == C4_EXPECTED
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_edge_rows_cascade_on_delete(db_session):
    name = unique_name()
    try:
        save_c4_copy(db_session, name)
        store.delete_circuit(db_session, name)
        db_session.commit()
        orphans = db_session.scalars(
            select(store.CircuitEdgeRow).where(
                store.CircuitEdgeRow.circuit_id.notin_(select(store.CircuitRow.id))
            )
        ).all()
        assert orphans == []
    finally:
        cleanup(db_session, name)


# --- edge (db): transparent + opaque surfaces ---

@pytest.mark.db
def test_describe_shows_internals_and_edges(db_session):
    name = unique_name()
    try:
        save_c4_copy(db_session, name)
        output = cli.cmd_describe(db_session, name)
        assert "internal nodes:" in output
        assert "N4  load_factor=4.0" in output
        assert "edges:" in output
        assert "N1 -> N4  weight=0.4" in output
        # External block still lists exactly the three entry points.
        assert "[2] N3" in output and "[3]" not in output
    finally:
        cleanup(db_session, name)


@pytest.mark.db
def test_interface_stays_opaque_for_dag_circuits(db_session):
    name = unique_name()
    try:
        save_c4_copy(db_session, name)
        assert interface.ext_nodes(name) == ["N1", "N2", "N3"]
        result = interface.evaluate(name, 60, [10, 10, 10])
        assert result == 59.0
        assert isinstance(result, float)
        assert not isinstance(result, PenaltyBreakdown)
    finally:
        cleanup(db_session, name)


# --- failure ---

def test_import_touches_no_engine():
    assert database._engine is None
