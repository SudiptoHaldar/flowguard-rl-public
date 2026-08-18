"""FastAPI application for the data/charting backend.

Factory contract: no module-level app instance — build one with :func:`create_app`
(dev server: ``uvicorn flowguard.data.api:create_app --factory``). Lazy-DB contract:
importing this module and creating the app never reads ``DATABASE_URL`` and never
connects; only the ``/health/db`` handler and the per-request session dependency touch the
engine, at request time.

Chart endpoints (req_003 v3.02) live in :mod:`flowguard.data.routers` under ``/api/v1``.
Health stays at its bare paths — it is liveness, not data, and the Flutter shell already
targets it. Error mapping is registered **once** here rather than as per-route
``try``/``except``: seven routes cannot each be trusted to remember.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import flowguard
from flowguard.data import queries, routers
from flowguard.data.database import get_engine
from flowguard.settings import MissingEnvVarError

# Dev-only CORS: the Flutter web app runs on an arbitrary localhost port.
# Deliberately no wildcard origin; revisit before any non-local deployment.
_CORS_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"


def create_app() -> FastAPI:
    app = FastAPI(title="flowguard-rl API", version=flowguard.__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=_CORS_ORIGIN_REGEX,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        """Liveness check; never touches the database."""
        return {"status": "ok", "version": flowguard.__version__}

    @app.get("/health/db")
    def health_db():
        """Database reachability check: SELECT 1 through the lazy engine."""
        try:
            with get_engine().connect() as connection:
                connection.execute(text("SELECT 1"))
        except (MissingEnvVarError, OperationalError) as exc:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "detail": exc.__class__.__name__},
            )
        return {"status": "ok"}

    _register_error_handlers(app)
    app.include_router(routers.router)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    """Map the query layer's typed failures onto HTTP (req_003 v3.02 D5, D7).

    Both run failures are **404**: a partial run is not a chart resource, so the surface does
    not advertise one (v3.01 D5). The distinct ``detail.reason`` keeps the diagnostic, so the
    UI can say "this run failed" rather than "not found" — hiding means not presenting, not
    lying about a run the caller named.
    """

    @app.exception_handler(queries.UnknownRun)
    def _unknown_run(request: Request, exc: queries.UnknownRun) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": {"reason": "unknown_run", "run_id": exc.run_id}},
        )

    @app.exception_handler(queries.RunNotChartable)
    def _run_not_chartable(
        request: Request, exc: queries.RunNotChartable
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "detail": {
                    "reason": "run_not_chartable",
                    "run_id": exc.run_id,
                    "status": exc.status,
                }
            },
        )

    @app.exception_handler(queries.UnknownBenchmark)
    def _unknown_benchmark(
        request: Request, exc: queries.UnknownBenchmark
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "detail": {
                    "reason": "unknown_benchmark",
                    "benchmark_id": exc.benchmark_id,
                }
            },
        )

    # A database that is down at request time is 503, not 500 — reusing the vocabulary
    # /health/db established. (That handler catches these locally, so it is unaffected.)
    @app.exception_handler(MissingEnvVarError)
    @app.exception_handler(OperationalError)
    def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "detail": exc.__class__.__name__},
        )
