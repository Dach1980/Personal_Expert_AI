"""SQLAlchemy engine, sessions, and PostgreSQL RLS context."""
import os
from collections.abc import Generator
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.storage.models import Base


def build_engine(database_url: str | None = None) -> Engine:
    """Build an engine from explicit configuration or DATABASE_URL."""
    url = database_url or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL must be configured before database access.")
    return create_engine(url, pool_pre_ping=True)


def build_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    """Create a session factory; no connection is opened until first use."""
    return sessionmaker(bind=build_engine(database_url), autoflush=False, expire_on_commit=False)


@lru_cache(maxsize=1)
def _default_session_factory() -> sessionmaker[Session]:
    """Reuse one engine and connection pool for the application process."""
    return build_session_factory()


def set_tenant_context(session: Session, tenant_id: UUID) -> None:
    """Set transaction-local PostgreSQL RLS context from a trusted principal."""
    session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide factory for isolated background/service transactions."""
    return _default_session_factory()


def get_session() -> Generator[Session, None, None]:
    """Yield a request-scoped session and always close it."""
    with _default_session_factory()() as session:
        with session.begin():
            yield session


__all__ = ["Base", "build_engine", "build_session_factory", "get_session", "get_session_factory", "set_tenant_context"]
