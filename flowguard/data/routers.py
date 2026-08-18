"""Chart HTTP endpoints (req_003 v3.02).

Seven read-only GET routes under ``/api/v1``, transport over
:mod:`flowguard.data.queries` and nothing more. **No SQL and no query logic live here**:
completed-runs-only, the never-pool grouping rules and the envelope-preserving thinning are all
enforced in the query layer, below any endpoint that could bypass them. An endpoint needing
data the query layer does not expose is a change to v3.01, not to this module.

Two structural rules worth stating, because both are easy to break by accident:

- **``queries`` is used through the module** (``queries.get_run_series(...)``), never
  ``from ... import get_run_series``. Route tests monkeypatch the module attribute to run
  without a database; a direct import would bind the function at import time and the patch
  would silently miss.
- **Config is read inside handlers**, never in a ``Query(...)`` default. Decorators are
  evaluated when this module is imported, so a ceiling in ``Query(le=...)`` would make the
  import read YAML — the same import-time side effect the lazy contracts forbid.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from flowguard.data import config, queries, schemas
from flowguard.data.database import get_session

#: The one place this string appears. Health stays bare (``/health``): it is liveness, not
#: data, and the shipped Flutter shell already targets it.
API_PREFIX = "/api/v1"

router = APIRouter(prefix=API_PREFIX, tags=["charts"])


def _resolve_max_points(requested: int | None) -> int:
    """Series cap: the client's value, or the configured default (spec D6)."""
    ceiling = config.max_points_ceiling()
    if requested is None:
        return config.default_max_points()
    if requested < 1 or requested > ceiling:
        raise HTTPException(
            status_code=422,
            detail=f"max_points must be between 1 and {ceiling}, got {requested}",
        )
    return requested


def _resolve_limit(requested: int | None) -> int:
    """Page size for ``/runs``: the client's value, or the configured default."""
    ceiling = config.max_run_limit()
    if requested is None:
        return config.default_run_limit()
    if requested < 1 or requested > ceiling:
        raise HTTPException(
            status_code=422,
            detail=f"limit must be between 1 and {ceiling}, got {requested}",
        )
    return requested


@router.get("/scenarios", response_model=list[schemas.ScenarioRefOut])
def scenarios(session=Depends(get_session)):
    """Every Circuit(Load) problem with at least one completed run — the picker feed."""
    return queries.list_scenarios(session)


@router.get("/runs", response_model=schemas.RunPage)
def runs(
    circuit_name: str | None = None,
    total_load: float | None = None,
    strategy: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    session=Depends(get_session),
):
    """Completed runs, newest first, paginated with a real unpaginated ``total``."""
    if offset < 0:
        raise HTTPException(status_code=422, detail=f"offset must be >= 0, got {offset}")
    resolved = _resolve_limit(limit)
    filters = {
        "circuit_name": circuit_name,
        "total_load": total_load,
        "strategy": strategy,
    }
    return schemas.RunPage(
        items=queries.list_runs_for(session, **filters, limit=resolved, offset=offset),
        total=queries.count_runs_for(session, **filters),
        limit=resolved,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=schemas.RunSummaryOut)
def run(run_id: int, session=Depends(get_session)):
    """Header for one completed run; 404 for unknown or non-completed (spec D5)."""
    return queries.get_run(session, run_id)


@router.get("/runs/{run_id}/series", response_model=schemas.RunSeriesOut)
def run_series(
    run_id: int, max_points: int | None = None, session=Depends(get_session)
):
    """Cost vs trial with the best-so-far envelope — the v3.04 replay feed."""
    return queries.get_run_series(
        session, run_id, max_points=_resolve_max_points(max_points)
    )


@router.get("/runs/{run_id}/allocations", response_model=schemas.AllocationSeriesOut)
def run_allocations(
    run_id: int, max_points: int | None = None, session=Depends(get_session)
):
    """Per-node loads over the run — the v3.06 feed, thinned to match the cost series."""
    return queries.get_allocation_series(
        session, run_id, max_points=_resolve_max_points(max_points)
    )


@router.get("/runs/{run_id}/topology", response_model=schemas.CircuitTopologyOut | None)
def run_topology(
    run_id: int, max_points: int | None = None, session=Depends(get_session)
):
    """The run's circuit as a graph, with per-node carried load — the v3.07 feed.

    Null when the circuit no longer exists; a flat circuit returns with `edges` empty.
    """
    return queries.get_run_topology(
        session, run_id, max_points=_resolve_max_points(max_points)
    )


@router.get("/benchmarks", response_model=list[schemas.BenchmarkHeaderOut])
def benchmarks(session=Depends(get_session)):
    """Harness invocations, newest first, with the provenance each result carries."""
    return queries.list_benchmarks(session)


@router.get("/comparison", response_model=schemas.ComparisonResponse)
def comparison(benchmark_id: int | None = None, session=Depends(get_session)):
    """The circuit x load x strategy grid for one invocation — the v3.05 feed.

    No ``benchmark_id`` selects the newest invocation; an empty corpus is a 200 with
    ``available: false`` (spec D10), while a *named* benchmark that does not exist is a 404.
    """
    grid = queries.get_comparison(session, benchmark_id)
    if grid is None:
        return schemas.ComparisonResponse(available=False, benchmark=None, cells=[])
    return schemas.ComparisonResponse(
        available=True,
        benchmark=schemas.BenchmarkHeaderOut.model_validate(grid.benchmark),
        cells=[schemas.ComparisonCellOut.model_validate(cell) for cell in grid.cells],
    )
