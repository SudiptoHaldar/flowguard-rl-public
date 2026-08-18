"""Tests for flowguard.data.api: health endpoints and the app-factory contract."""

import pytest
from fastapi.testclient import TestClient

import flowguard
from flowguard.data import database
from flowguard.data.api import create_app

# connect_timeout is essential: Windows drops (not refuses) SYNs to closed ports, so
# without it psycopg waits ~2 minutes for the OS to give up.
UNREACHABLE_URL = "postgresql+psycopg://user:secret@127.0.0.1:1/fake_db?connect_timeout=1"


@pytest.fixture(autouse=True)
def clean_engine_cache():
    database.reset_engine()
    yield
    database.reset_engine()


# --- expected ---

def test_health_needs_no_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": flowguard.__version__}


# --- edge ---

def test_factory_returns_independent_apps():
    assert create_app() is not create_app()


# --- failure ---

def test_health_db_503_when_database_url_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = TestClient(create_app()).get("/health/db")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["detail"] == "MissingEnvVarError"


def test_health_db_503_when_database_unreachable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_URL)
    response = TestClient(create_app()).get("/health/db")
    assert response.status_code == 503
    assert response.json()["detail"] == "OperationalError"


# --- CORS ---

def test_cors_allows_localhost_origins(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = TestClient(create_app()).get(
        "/health", headers={"Origin": "http://localhost:5555"}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5555"


def test_cors_ignores_unknown_origins(monkeypatch):
    # CORS is browser-enforced: the server still answers 200, but without the
    # allow-origin header the browser blocks the response.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = TestClient(create_app()).get(
        "/health", headers={"Origin": "http://evil.example.com"}
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


# --- integration (live DB) ---

@pytest.mark.db
def test_health_db_ok_against_live_database():
    try:
        database.get_engine().connect().close()
    except Exception as exc:  # noqa: BLE001 - any failure here means "no live DB"
        pytest.skip(f"database unreachable: {exc.__class__.__name__}")
    response = TestClient(create_app()).get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
