"""Tests for flowguard.data.database: lazy engine, session factory, and live-DB integration."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ArgumentError, OperationalError

from flowguard.data import database
from flowguard.settings import MissingEnvVarError

FAKE_URL = "postgresql+psycopg://user:secret@db.example.invalid:5432/fake_db"


@pytest.fixture(autouse=True)
def clean_engine_cache():
    database.reset_engine()
    yield
    database.reset_engine()


# --- expected ---

def test_get_engine_uses_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    engine = database.get_engine()  # no connection is made
    assert engine.url.database == "fake_db"
    assert engine.url.drivername == "postgresql+psycopg"


def test_session_factory_binds_cached_engine(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    session = database.get_session_factory()()
    assert session.get_bind() is database.get_engine()
    session.close()


# --- edge ---

def test_engine_is_cached_and_resettable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    first = database.get_engine()
    assert database.get_engine() is first
    database.reset_engine()
    assert database.get_engine() is not first


# --- failure ---

def test_missing_database_url_raises_named_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(MissingEnvVarError, match="DATABASE_URL"):
        database.get_engine()


def test_malformed_url_raises(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "not-a-valid-url")
    with pytest.raises(ArgumentError):
        database.get_engine()


# --- integration (live DB) ---

@pytest.mark.db
def test_select_one_against_live_database():
    try:
        connection = database.get_engine().connect()
    except (MissingEnvVarError, OperationalError) as exc:
        pytest.skip(f"database unreachable: {exc.__class__.__name__}")
    with connection:
        assert connection.execute(text("SELECT 1")).scalar() == 1
