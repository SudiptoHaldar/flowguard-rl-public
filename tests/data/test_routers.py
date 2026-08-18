"""Tests for the chart HTTP API (req_003 v3.02).

Deliberately **DB-free by default**: the session dependency is overridden with a sentinel and
``queries`` is monkeypatched, so these run and pass with no database — the routers are
transport, and transport is exactly what should be testable without infrastructure. The
db-marked tests at the end are live smokes over the real corpus.
"""

import dataclasses
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from flowguard.data import config, database, queries
from flowguard.data.api import create_app
from flowguard.data.database import get_session
from flowguard.settings import MissingEnvVarError

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
SENTINEL = object()


@pytest.fixture(autouse=True)
def clean_caches():
    database.reset_engine()
    config.reset()
    yield
    database.reset_engine()
    config.reset()


@pytest.fixture
def client():
    """App with the session dependency stubbed — no database is ever reached."""
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SENTINEL
    return TestClient(app)


def make_summary(**overrides) -> queries.RunSummary:
    kwargs = dict(
        run_id=1091,
        circuit_name="C4",
        total_load=10000.0,
        strategy="hill_climb",
        strategy_version="v1",
        seed=0,
        budget=160,
        observation_mode="opaque",
        allocation_mode="integer",
        cold_start=True,
        termination_reason="budget_exhausted",
        external_node_names=("N1", "N2", "N3"),
        trials_used=160,
        first_cost=5.15e17,
        best_cost=299.1856,
        improvement=1.0,
        created_at=NOW,
        completed_at=NOW,
    )
    kwargs.update(overrides)
    return queries.RunSummary(**kwargs)


#: Distinguishes "caller passed reference=None" from "caller said nothing".
_UNSET = object()


def make_reference(**overrides) -> queries.ScenarioReference:
    kwargs = dict(
        optimum=299.1856,
        optimum_method="enumerated",
        best_of_random=364.16,
        best_of_random_strategy_version="2",
        catalog_name="default",
        catalog_version=1,
        benchmark_id=14,
    )
    kwargs.update(overrides)
    return queries.ScenarioReference(**kwargs)


def make_series(
    points=None, total_points=160, downsampled=True, reference=_UNSET
) -> queries.RunSeries:
    points = points or (
        queries.SeriesPoint(0, 5.15e17, 5.15e17, True),
        queries.SeriesPoint(105, 299.1856, 299.1856, True),
    )
    return queries.RunSeries(
        run=make_summary(),
        points=points,
        total_points=total_points,
        downsampled=downsampled,
        reference=make_reference() if reference is _UNSET else reference,
    )


def make_cell(**overrides) -> queries.ComparisonCell:
    kwargs = dict(
        circuit_name="C2",
        total_load=60.0,
        strategy="hill_climb",
        strategy_version="v1",
        allocation_mode="integer",
        observation_mode="opaque",
        cold_start=True,
        runs=1,
        best_cost_median=4.0,
        best_cost_min=4.0,
        best_cost_max=4.0,
        improvement_median=0.5,
        convergence_step_median=12,
        optimum=4.0,
        optimum_method="enumerated",
        regret_median=0.0,
        safety_fraction_median=0.0,
        excluded_from_aggregates=False,
    )
    kwargs.update(overrides)
    return queries.ComparisonCell(**kwargs)


def make_header() -> queries.BenchmarkHeader:
    return queries.BenchmarkHeader(
        benchmark_id=14,
        catalog_name="default",
        catalog_version=1,
        n_seeds=5,
        bound_factor=2.0,
        enumeration_cap=2000000,
        notes=None,
        created_at=NOW,
    )


def field_names(record_type) -> set[str]:
    return {field.name for field in dataclasses.fields(record_type)}


# --- expected: every endpoint, and the wire shape matches the records ---


def test_scenarios(client, monkeypatch):
    monkeypatch.setattr(
        queries, "list_scenarios", lambda session: (queries.ScenarioRef("C2", 60.0, 32, 4.0),)
    )
    response = client.get("/api/v1/scenarios")
    assert response.status_code == 200
    body = response.json()
    assert set(body[0]) == field_names(queries.ScenarioRef)
    assert body[0]["circuit_name"] == "C2" and body[0]["run_count"] == 32


def test_run_header(client, monkeypatch):
    monkeypatch.setattr(queries, "get_run", lambda session, run_id: make_summary())
    body = client.get("/api/v1/runs/1091").json()
    assert set(body) == field_names(queries.RunSummary)
    assert body["external_node_names"] == ["N1", "N2", "N3"]  # tuple -> JSON array
    assert body["best_cost"] == 299.1856


def test_run_series_shape(client, monkeypatch):
    monkeypatch.setattr(
        queries, "get_run_series", lambda session, run_id, max_points=None: make_series()
    )
    body = client.get("/api/v1/runs/1091/series").json()
    assert set(body) == {"run", "points", "total_points", "downsampled", "reference"}
    assert set(body["run"]) == field_names(queries.RunSummary)
    assert set(body["points"][0]) == field_names(queries.SeriesPoint)
    assert body["points"][-1]["best_so_far"] == 299.1856
    assert body["total_points"] == 160 and body["downsampled"] is True


def test_series_carries_the_scenario_reference(client, monkeypatch):
    """The chart's reference lines come from the API, not a second client-side call."""
    monkeypatch.setattr(
        queries, "get_run_series", lambda session, run_id, max_points=None: make_series()
    )
    reference = client.get("/api/v1/runs/1091/series").json()["reference"]
    assert set(reference) == field_names(queries.ScenarioReference)
    assert reference["optimum"] == 299.1856
    assert reference["optimum_method"] == "enumerated"
    assert reference["best_of_random"] == 364.16


def test_series_reference_is_null_without_benchmark_coverage(client, monkeypatch):
    monkeypatch.setattr(
        queries,
        "get_run_series",
        lambda session, run_id, max_points=None: make_series(reference=None),
    )
    assert client.get("/api/v1/runs/1091/series").json()["reference"] is None


def test_allocations_shape(client, monkeypatch):
    series = queries.AllocationSeries(
        run_id=1091,
        node_names=("N1", "N2", "N3"),
        points=(queries.AllocationPoint(0, (13.0, 6.0, 17.0)),),
        total_points=160,
        downsampled=True,
        capacities=queries.NodeCapacities(
            nodes=(
                queries.ExternalNode("N1", 13.0, 18.0),
                queries.ExternalNode("N2", 7.0, 10.0),
                queries.ExternalNode("N3", 17.0, 20.0),
            ),
            matches_run=True,
        ),
        best=queries.BestAllocations(cost=299.1856, allocations=((13.0, 6.0, 17.0),)),
    )
    monkeypatch.setattr(
        queries, "get_allocation_series", lambda session, run_id, max_points=None: series
    )
    body = client.get("/api/v1/runs/1091/allocations").json()
    assert set(body) == field_names(queries.AllocationSeries)
    assert body["points"][0]["loads"] == [13.0, 6.0, 17.0]
    # Capacity marks and the tie set ride on the same response — a client never joins two
    # endpoints to draw one chart.
    assert body["capacities"]["matches_run"] is True
    assert body["capacities"]["nodes"][0] == {
        "name": "N1",
        "load_factor": 13.0,
        "load_safety_cap": 18.0,
    }
    assert body["best"]["cost"] == 299.1856
    assert body["best"]["allocations"] == [[13.0, 6.0, 17.0]]


def test_benchmarks(client, monkeypatch):
    monkeypatch.setattr(queries, "list_benchmarks", lambda session: (make_header(),))
    body = client.get("/api/v1/benchmarks").json()
    assert set(body[0]) == field_names(queries.BenchmarkHeader)


def test_comparison_available(client, monkeypatch):
    grid = queries.ComparisonGrid(benchmark=make_header(), cells=(make_cell(),))
    monkeypatch.setattr(queries, "get_comparison", lambda session, bid=None: grid)
    body = client.get("/api/v1/comparison").json()
    assert body["available"] is True
    assert set(body["cells"][0]) == field_names(queries.ComparisonCell)
    assert body["benchmark"]["catalog_name"] == "default"


def test_runs_page(client, monkeypatch):
    captured = {}

    def fake_list(session, **kwargs):
        captured.update(kwargs)
        return (make_summary(),)

    monkeypatch.setattr(queries, "list_runs_for", fake_list)
    monkeypatch.setattr(queries, "count_runs_for", lambda session, **kwargs: 317)
    body = client.get("/api/v1/runs?circuit_name=C4&limit=10&offset=20").json()
    assert body["total"] == 317 and body["limit"] == 10 and body["offset"] == 20
    assert set(body["items"][0]) == field_names(queries.RunSummary)
    assert captured["limit"] == 10 and captured["offset"] == 20
    assert captured["circuit_name"] == "C4"


# --- edge: the caps come from config, not from literals ---


def test_series_applies_the_configured_default(client, monkeypatch):
    captured = {}

    def fake(session, run_id, max_points=None):
        captured["max_points"] = max_points
        return make_series()

    monkeypatch.setattr(queries, "get_run_series", fake)
    client.get("/api/v1/runs/1091/series")
    assert captured["max_points"] == config.default_max_points() == 1000


def test_series_honours_an_explicit_max_points(client, monkeypatch):
    captured = {}

    def fake(session, run_id, max_points=None):
        captured["max_points"] = max_points
        return make_series()

    monkeypatch.setattr(queries, "get_run_series", fake)
    client.get("/api/v1/runs/1091/series?max_points=12")
    assert captured["max_points"] == 12


def test_runs_applies_the_configured_default_limit(client, monkeypatch):
    captured = {}

    def fake_list(session, **kwargs):
        captured.update(kwargs)
        return ()

    monkeypatch.setattr(queries, "list_runs_for", fake_list)
    monkeypatch.setattr(queries, "count_runs_for", lambda session, **kwargs: 0)
    client.get("/api/v1/runs")
    assert captured["limit"] == config.default_run_limit() == 50


def test_comparison_empty_corpus_is_200_not_404(client, monkeypatch):
    """Spec D10: an empty corpus is a state to render, never a missing document."""
    monkeypatch.setattr(queries, "get_comparison", lambda session, bid=None: None)
    response = client.get("/api/v1/comparison")
    assert response.status_code == 200
    assert response.json() == {"available": False, "benchmark": None, "cells": []}


# --- failure: the error vocabulary ---


@pytest.mark.parametrize("path", ["/api/v1/runs/9", "/api/v1/runs/9/series"])
def test_unknown_run_is_404_with_reason(client, monkeypatch, path):
    def boom(session, run_id, **kwargs):
        raise queries.UnknownRun(run_id)

    monkeypatch.setattr(queries, "get_run", boom)
    monkeypatch.setattr(queries, "get_run_series", boom)
    response = client.get(path)
    assert response.status_code == 404
    assert response.json()["detail"] == {"reason": "unknown_run", "run_id": 9}


def test_partial_run_is_404_carrying_its_status(client, monkeypatch):
    """Hiding means not presenting — the body still says *why*, so the UI can too."""

    def boom(session, run_id, **kwargs):
        raise queries.RunNotChartable(run_id, "failed")

    monkeypatch.setattr(queries, "get_run_series", boom)
    response = client.get("/api/v1/runs/1099/series")
    assert response.status_code == 404
    assert response.json()["detail"] == {
        "reason": "run_not_chartable",
        "run_id": 1099,
        "status": "failed",
    }


def test_unknown_benchmark_is_404(client, monkeypatch):
    def boom(session, benchmark_id=None):
        raise queries.UnknownBenchmark(benchmark_id)

    monkeypatch.setattr(queries, "get_comparison", boom)
    response = client.get("/api/v1/comparison?benchmark_id=77")
    assert response.status_code == 404
    assert response.json()["detail"] == {"reason": "unknown_benchmark", "benchmark_id": 77}


@pytest.mark.parametrize("value", [0, -1, 20001])
def test_max_points_outside_the_ceiling_is_422(client, value):
    response = client.get(f"/api/v1/runs/1091/series?max_points={value}")
    assert response.status_code == 422


@pytest.mark.parametrize("query", ["limit=0", "limit=501", "offset=-1"])
def test_bad_pagination_is_422(client, query):
    response = client.get(f"/api/v1/runs?{query}")
    assert response.status_code == 422


@pytest.mark.parametrize(
    "error", [OperationalError("SELECT 1", {}, Exception("down")), MissingEnvVarError("DATABASE_URL")]
)
def test_database_down_is_503_not_500(error):
    """A dead database at request time reuses /health/db's vocabulary, not a 500."""
    app = create_app()

    def broken_session():
        raise error
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = broken_session
    response = TestClient(app).get("/api/v1/scenarios")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["detail"] == error.__class__.__name__


# --- contract guards ---


def test_every_route_is_get_only():
    """Spec D1: the dashboard never writes. Checked on the OpenAPI document, which is what a
    client sees — FastAPI 0.141 keeps an included router as one opaque entry in app.routes."""
    paths = create_app().openapi()["paths"]
    for path, operations in paths.items():
        assert set(operations) == {"get"}, f"{path} exposes {sorted(operations)}"


def test_openapi_documents_every_chart_endpoint():
    paths = set(create_app().openapi()["paths"])
    assert {
        "/api/v1/scenarios",
        "/api/v1/runs",
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/series",
        "/api/v1/runs/{run_id}/allocations",
        "/api/v1/benchmarks",
        "/api/v1/comparison",
    } <= paths
    assert {"/health", "/health/db"} <= paths, "health must stay at its bare paths"


def test_create_app_opens_no_connection(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database.reset_engine()
    create_app()
    assert database._engine is None


# --- integration (live DB) ---


@pytest.fixture
def live_client():
    try:
        database.get_engine().connect().close()
    except Exception as exc:  # noqa: BLE001 - any failure here means "no live DB"
        pytest.skip(f"database unreachable: {exc.__class__.__name__}")
    return TestClient(create_app())


@pytest.mark.db
def test_live_endpoints_answer(live_client):
    for path in ("/api/v1/scenarios", "/api/v1/runs?limit=5", "/api/v1/benchmarks"):
        assert live_client.get(path).status_code == 200, path
    page = live_client.get("/api/v1/runs?limit=5").json()
    assert len(page["items"]) <= 5
    assert page["total"] >= len(page["items"])


@pytest.mark.db
def test_live_c4_series_reaches_the_known_optimum(live_client):
    """The DAG optimum v2.06 established, served over HTTP."""
    page = live_client.get(
        "/api/v1/runs?circuit_name=C4&strategy=hill_climb&total_load=10000&limit=1"
    ).json()
    if not page["items"]:
        pytest.skip("no C4 hill_climb run at L=10000 in this database")
    run_id = page["items"][0]["run_id"]
    body = live_client.get(f"/api/v1/runs/{run_id}/series?max_points=12").json()
    assert body["points"][-1]["best_so_far"] == pytest.approx(299.1856)
    assert body["total_points"] >= len(body["points"])


@pytest.mark.db
def test_live_comparison_matches_the_corpus(live_client):
    body = live_client.get("/api/v1/comparison").json()
    assert body["available"] in (True, False)
    if body["available"] and body["cells"]:
        cell = body["cells"][0]
        assert cell["optimum_method"] in ("enumerated", "best_observed", "unknown")
