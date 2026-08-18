"""SQLAlchemy plumbing for the data/charting component.

Lazy-init contract: importing this module never reads ``DATABASE_URL`` and never touches
the database. The engine is created (and cached at module level) only on the first
:func:`get_engine` call; a missing ``DATABASE_URL`` surfaces as
:class:`flowguard.settings.MissingEnvVarError` at that point, not at import.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from flowguard.settings import get_str


class Base(DeclarativeBase):
    """Declarative base for all flowguard models (none yet — the charting group adds them)."""


_engine = None


def get_engine():
    """Return the module-cached engine, creating it from ``DATABASE_URL`` on first call."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_str("DATABASE_URL"))
    return _engine


def reset_engine() -> None:
    """Dispose and forget the cached engine (test hook; safe on a never-connected engine)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def get_session_factory() -> sessionmaker:
    """Return a ``sessionmaker`` bound to the cached engine."""
    return sessionmaker(bind=get_engine())


def get_session():
    """FastAPI dependency yielding a request-scoped session (req_003 v3.02).

    Lives here rather than in :mod:`flowguard.data.api` for two reasons: session plumbing
    already belongs to this module, and ``api`` imports ``routers`` — a dependency defined in
    ``api`` would close an ``api → routers → api`` cycle.

    **Never commits.** The chart API is read-only, so the session is rolled back on close and
    a stray transaction cannot linger. Engine creation happens per request, which is what keeps
    ``create_app()`` free of any database contact; a database that is down surfaces here as
    ``MissingEnvVarError``/``OperationalError`` and is mapped to 503 by the app's handlers.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
