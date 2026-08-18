"""Tests for flowguard.rl.store: run/step persistence, the opacity rule, view, reconciliation."""

from datetime import timedelta

import pytest
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import OperationalError

from flowguard.data import database
from flowguard.rl import store
from flowguard.rl.types import (
    ObservationMode,
    PenaltyAudit,
    RunStatus,
    TerminationReason,
)
from flowguard.settings import MissingEnvVarError

AUDIT = PenaltyAudit(3.0, 55.0, 34.0)


@pytest.fixture(autouse=True)
def clean_engine_cache():
    database.reset_engine()
    yield
    database.reset_engine()


@pytest.fixture
def db_session():
    """Live session; skips when the DB is unreachable or the RL tables are missing."""
    try:
        engine = database.get_engine()
        inspector = inspect(engine)
        has_tables = inspector.has_table("rl_runs") and inspector.has_table("rl_steps")
    except (MissingEnvVarError, OperationalError) as exc:
        pytest.skip(f"database unreachable: {exc.__class__.__name__}")
    if not has_tables:
        pytest.skip("rl tables missing — run: alembic upgrade head")
    session = database.get_session_factory()()
    yield session
    session.rollback()
    session.close()


def make_run(session, **overrides):
    kwargs = dict(
        circuit_name="test_circuit",
        total_load=60.0,
        external_node_names=["N1", "N2"],
        strategy="test",
    )
    kwargs.update(overrides)
    run = store.create_run(session, **kwargs)
    session.commit()
    return run


def add_steps(session, run_id, count=3):
    for index in range(count):
        store.append_step(
            session,
            run_id,
            index,
            [10.0 + index, 20.0 + index],
            92.0 + index,
            AUDIT,
            is_best=(index == 0),
        )
    session.commit()


def cleanup(session, run_id):
    try:
        store.delete_run(session, run_id)
        session.commit()
    except ValueError:
        session.rollback()


# --- expected (db) ---

@pytest.mark.db
def test_run_and_steps_round_trip(db_session):
    run = make_run(db_session)
    try:
        add_steps(db_session, run.id, 3)
        history = store.load_history(db_session, run.id)
        assert [t.step_index for t in history] == [0, 1, 2]
        assert history[0].allocation == (10.0, 20.0)
        assert history[2].total_cost == 94.0
        assert store.load_run(db_session, run.id).status == RunStatus.RUNNING
    finally:
        cleanup(db_session, run.id)


@pytest.mark.db
def test_close_run_writes_terminal_state(db_session):
    run = make_run(db_session)
    try:
        store.close_run(
            db_session,
            run.id,
            RunStatus.COMPLETED,
            TerminationReason.CONVERGED,
            best_cost=92.0,
            best_allocation=[10.0, 10.0],
        )
        db_session.commit()
        reloaded = store.load_run(db_session, run.id)
        assert reloaded.status == RunStatus.COMPLETED
        assert reloaded.termination_reason == TerminationReason.CONVERGED
        assert reloaded.best_cost == 92.0
        assert reloaded.best_allocation == [10.0, 10.0]
        assert reloaded.completed_at is not None
    finally:
        cleanup(db_session, run.id)


# --- the opacity rule (db) — this is what protects every downstream result ---

@pytest.mark.db
def test_opaque_run_hides_audit_but_still_records_it(db_session):
    run = make_run(db_session, observation_mode=ObservationMode.OPAQUE)
    try:
        add_steps(db_session, run.id, 2)

        # The proposer-facing reader strips the components...
        assert all(t.audit is None for t in store.load_history(db_session, run.id))
        # ...while the columns are populated all the same (private audit, blueprint §10).
        row = db_session.scalar(
            select(store.StepRow).where(store.StepRow.run_id == run.id).limit(1)
        )
        assert (row.audit_delay, row.audit_overload, row.audit_safety) == (
            3.0,
            55.0,
            34.0,
        )
        # ...and the explicitly-named audit path returns them.
        audited = store.load_audit(db_session, run.id)
        assert audited[0].audit == AUDIT
    finally:
        cleanup(db_session, run.id)


@pytest.mark.db
def test_enhanced_run_exposes_audit_to_history(db_session):
    run = make_run(db_session, observation_mode=ObservationMode.ENHANCED)
    try:
        add_steps(db_session, run.id, 2)
        history = store.load_history(db_session, run.id)
        assert all(t.audit == AUDIT for t in history)
        assert history[0].audit.total == 92.0
    finally:
        cleanup(db_session, run.id)


# --- edge (db) ---

@pytest.mark.db
def test_view_expands_allocation_to_one_row_per_node(db_session):
    run = make_run(db_session, external_node_names=["B", "A"])  # order ≠ alphabetical
    try:
        add_steps(db_session, run.id, 2)
        rows = db_session.execute(
            text(
                "SELECT step_index, position, node_name, load, total_cost "
                "FROM v_rl_step_loads WHERE run_id = :r ORDER BY step_index, position"
            ),
            {"r": run.id},
        ).all()
        assert len(rows) == 4  # 2 steps x 2 nodes
        # position is 1-based (array ordinality); node_name comes from the run's own list.
        assert tuple(rows[0]) == (0, 1, "B", 10.0, 92.0)
        assert tuple(rows[1]) == (0, 2, "A", 20.0, 92.0)
    finally:
        cleanup(db_session, run.id)


@pytest.mark.db
def test_stale_running_run_is_swept_but_fresh_one_is_not(db_session):
    stale = make_run(db_session)
    fresh = make_run(db_session)
    try:
        db_session.execute(
            update(store.RunRow)
            .where(store.RunRow.id == stale.id)
            .values(last_progress_at=func.now() - timedelta(seconds=3600))
        )
        db_session.commit()

        assert store.reconcile_stale_runs(db_session, 60) >= 1
        db_session.commit()

        swept = store.load_run(db_session, stale.id)
        assert swept.status == RunStatus.ABANDONED
        assert swept.termination_reason == TerminationReason.INTERRUPTED
        assert store.load_run(db_session, fresh.id).status == RunStatus.RUNNING
    finally:
        cleanup(db_session, stale.id)
        cleanup(db_session, fresh.id)


@pytest.mark.db
def test_delete_run_cascades_to_steps(db_session):
    run = make_run(db_session)
    add_steps(db_session, run.id, 3)
    run_id = run.id
    store.delete_run(db_session, run_id)
    db_session.commit()
    orphans = db_session.scalars(
        select(store.StepRow).where(store.StepRow.run_id == run_id)
    ).all()
    assert orphans == []


@pytest.mark.db
def test_list_runs_filters_and_orders_newest_first(db_session):
    first = make_run(db_session, circuit_name="test_list_circuit")
    second = make_run(db_session, circuit_name="test_list_circuit")
    try:
        names = [r.id for r in store.list_runs(db_session, circuit_name="test_list_circuit")]
        assert names.index(second.id) < names.index(first.id)
        assert store.list_runs(
            db_session, circuit_name="test_list_circuit", status=RunStatus.COMPLETED
        ) == []
    finally:
        cleanup(db_session, first.id)
        cleanup(db_session, second.id)


# --- failure (db) ---

@pytest.mark.db
def test_unknown_run_raises(db_session):
    with pytest.raises(ValueError, match="does not exist"):
        store.load_run(db_session, -1)
    with pytest.raises(ValueError, match="does not exist"):
        store.load_history(db_session, -1)


@pytest.mark.db
def test_duplicate_step_index_rejected_by_constraint(db_session):
    run = make_run(db_session)
    try:
        store.append_step(db_session, run.id, 0, [1.0, 2.0], 5.0, AUDIT)
        db_session.commit()
        store.append_step(db_session, run.id, 0, [3.0, 4.0], 6.0, AUDIT)
        with pytest.raises(Exception):  # IntegrityError from uq_rl_steps_run_step
            db_session.commit()
        db_session.rollback()
    finally:
        cleanup(db_session, run.id)


# --- failure (DB-free) ---

def test_create_run_validates_arguments():
    with pytest.raises(ValueError, match="at least one external node"):
        store.create_run(
            None, circuit_name="c", total_load=60, external_node_names=[], strategy="s"
        )
    with pytest.raises(ValueError, match="total_load must be > 0"):
        store.create_run(
            None,
            circuit_name="c",
            total_load=0,
            external_node_names=["N1"],
            strategy="s",
        )
    with pytest.raises(ValueError, match="unknown observation_mode"):
        store.create_run(
            None,
            circuit_name="c",
            total_load=60,
            external_node_names=["N1"],
            strategy="s",
            observation_mode="peeking",
        )


def test_close_run_rejects_non_terminal_status():
    with pytest.raises(ValueError, match="not a terminal run status"):
        store.close_run(None, 1, RunStatus.RUNNING)


def test_reconcile_rejects_non_positive_threshold():
    with pytest.raises(ValueError, match="threshold_seconds must be >= 1"):
        store.reconcile_stale_runs(None, 0)


def test_import_touches_no_engine():
    assert database._engine is None
