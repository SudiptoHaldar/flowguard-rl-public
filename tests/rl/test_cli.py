"""Tests for flowguard.rl.cli: optimize / runs / show, --json, and the stale-run sweep."""

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, inspect, update
from sqlalchemy.exc import OperationalError

from flowguard.circuits import Circuit, Node, interface
from flowguard.circuits import store as circuits_store
from flowguard.data import database
from flowguard.rl import cli, store
from flowguard.rl.driver import run_algo
from flowguard.rl.proposers import HillClimb
from flowguard.rl.types import AllocationMode, RunStatus, TerminationReason
from flowguard.settings import MissingEnvVarError


@pytest.fixture(autouse=True)
def clean_caches():
    database.reset_engine()
    interface.clear_cache()
    yield
    database.reset_engine()
    interface.clear_cache()


@pytest.fixture
def db_session():
    try:
        engine = database.get_engine()
        inspector = inspect(engine)
        ready = inspector.has_table("rl_runs") and inspector.has_table("circuits")
        if ready:
            columns = {c["name"] for c in inspector.get_columns("rl_runs")}
            ready = "allocation_mode" in columns
    except (MissingEnvVarError, OperationalError) as exc:
        pytest.skip(f"database unreachable: {exc.__class__.__name__}")
    if not ready:
        pytest.skip("rl/circuit tables missing or stale — run: alembic upgrade head")
    session = database.get_session_factory()()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def circuit_name(db_session):
    name = f"test_cli_rl_{uuid.uuid4().hex[:8]}"
    circuits_store.save_circuit(
        db_session, Circuit(name, [Node("N1", 10, 16), Node("N2", 5, 8)], ["N1", "N2"])
    )
    db_session.commit()
    interface.clear_cache()
    yield name
    for run in store.list_runs(db_session, circuit_name=name):
        store.delete_run(db_session, run.id)
    circuits_store.delete_circuit(db_session, name)
    db_session.commit()
    interface.clear_cache()


# --- expected (db) ---

@pytest.mark.db
def test_optimize_matches_the_driver(db_session, circuit_name):
    direct = run_algo(circuit_name, 60, HillClimb(), seed=1, session=db_session)
    output = cli.cmd_optimize(db_session, circuit_name, 60, strategy="hill_climb", seed=1)
    assert circuit_name in output
    assert f"best_cost        : {direct.best_cost:.4f}" in output
    # allocations are labelled by node name, not left as an anonymous array
    assert "N1=" in output and "N2=" in output


@pytest.mark.db
def test_runs_lists_the_run_just_created(db_session, circuit_name):
    result = cli.cmd_optimize(db_session, circuit_name, 60, seed=1)
    assert result  # created
    output = cli.cmd_runs(db_session, circuit=circuit_name)
    assert circuit_name in output
    assert "hill_climb" in output


@pytest.mark.db
def test_show_renders_header_and_trace(db_session, circuit_name):
    result = run_algo(circuit_name, 60, HillClimb(), seed=1, session=db_session)

    header = cli.cmd_show(db_session, result.run_id)
    assert f"run_id           : {result.run_id}" in header
    assert "step" not in header  # no trace unless asked

    traced = cli.cmd_show(db_session, result.run_id, trace=True)
    assert "step" in traced
    # `Trial` has no is_best, so the CLI recomputes it as a running minimum; the very first
    # trial is always the best-so-far at the time it ran.
    assert "*best" in traced
    body = traced.split("cost")[-1]
    assert body.count("\n") == result.trials_used


# --- the stale-run sweep (db) — v2.01 D6.3's trigger, wired here for the first time ---

@pytest.mark.db
def test_runs_sweeps_a_stale_running_run(db_session, circuit_name):
    stale = store.create_run(
        db_session,
        circuit_name=circuit_name,
        total_load=60,
        external_node_names=["N1", "N2"],
        strategy="stuck",
    )
    db_session.commit()
    db_session.execute(
        update(store.RunRow)
        .where(store.RunRow.id == stale.id)
        .values(last_progress_at=func.now() - timedelta(days=1))
    )
    db_session.commit()

    output = cli.cmd_runs(db_session, circuit=circuit_name)
    db_session.commit()

    assert "swept" in output
    swept = store.load_run(db_session, stale.id)
    assert swept.status == RunStatus.ABANDONED
    assert swept.termination_reason == TerminationReason.INTERRUPTED


# --- json (db) ---

@pytest.mark.db
def test_json_output_parses_for_every_command(db_session, circuit_name):
    optimize = json.loads(
        cli.cmd_optimize(db_session, circuit_name, 60, seed=1, as_json=True)
    )
    assert optimize["circuit"] == circuit_name
    assert optimize["external_node_names"] == ["N1", "N2"]

    listed = json.loads(cli.cmd_runs(db_session, circuit=circuit_name, as_json=True))
    assert set(listed) == {"swept", "runs"}
    assert listed["runs"][0]["run_id"] == optimize["run_id"]

    shown = json.loads(
        cli.cmd_show(db_session, optimize["run_id"], trace=True, as_json=True)
    )
    assert shown["best_cost"] == optimize["best_cost"]
    assert len(shown["trace"]) == optimize["trials_used"]


@pytest.mark.db
def test_continuous_flag_selects_the_continuous_mode(db_session, circuit_name):
    payload = json.loads(
        cli.cmd_optimize(db_session, circuit_name, 60, seed=1, continuous=True, as_json=True)
    )
    assert payload["allocation_mode"] == AllocationMode.CONTINUOUS


# --- failure ---

@pytest.mark.db
def test_unknown_run_id_raises(db_session):
    with pytest.raises(ValueError, match="does not exist"):
        cli.cmd_show(db_session, -1)


def test_unknown_strategy_lists_the_valid_names_without_a_session():
    # The strategy lookup happens before any database use, so this needs no session.
    with pytest.raises(ValueError, match="unknown strategy 'nope'") as excinfo:
        cli.cmd_optimize(None, "C2", 60, strategy="nope")
    message = str(excinfo.value)
    assert "hill_climb" in message and "release_sweep" in message


@pytest.mark.parametrize("argv", [[], ["show"], ["optimize", "C2"], ["bogus"]])
def test_argparse_misuse_exits_two(argv):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(argv)
    assert excinfo.value.code == 2


def test_enhanced_flag_warns_on_stderr(capsys, monkeypatch):
    # Fail the session creation immediately: we only care that the warning precedes it.
    monkeypatch.setattr(
        cli, "get_session_factory", lambda: (_ for _ in ()).throw(
            MissingEnvVarError("DATABASE_URL")
        )
    )
    assert cli.main(["optimize", "C2", "60", "--enhanced"]) == 1
    assert "NOT comparable" in capsys.readouterr().err


def test_import_touches_no_engine():
    assert database._engine is None
