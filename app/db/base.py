from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, StaticPool

from app.config import get_settings
from app.logger import logging
from app.exception import CustomException

# Lazy singleton globals
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


# Engine builder
def _build_engine() -> AsyncEngine:
    """
    Create the async SQLAlchemy engine from centralised settings.
    Supports SQLite (for tests), NullPool mode, and standard MySQL pooling.
    """
    settings = get_settings()
    cfg = settings.db
    use_null_pool = "no_pool=true" in cfg.DATABASE_URL_ASYNC
    is_sqlite = cfg.DATABASE_URL_ASYNC.startswith("sqlite")

    engine_kwargs: dict[str, Any] = {
        "echo": cfg.DB_ECHO_SQL,
    }

    if is_sqlite:
        # SQLite (used in tests) - StaticPool, single connection
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        engine_kwargs["poolclass"] = StaticPool
        logging.info("DB engine: using StaticPool for SQLite.")
    elif use_null_pool:
        engine_kwargs["poolclass"] = NullPool
        logging.info("DB engine: using NullPool (no_pool flag detected in URL).")
    else:
        # Standard MySQL / asyncmy configuration
        engine_kwargs["pool_pre_ping"] = True
        engine_kwargs["pool_recycle"] = cfg.DB_POOL_RECYCLE_SECONDS
        engine_kwargs["pool_size"] = cfg.DB_POOL_SIZE
        engine_kwargs["max_overflow"] = cfg.DB_MAX_OVERFLOW
        engine_kwargs["pool_timeout"] = 30  # seconds
        engine_kwargs["connect_args"] = {
            "charset": "utf8mb4",
            "connect_timeout": 10,
        }

    try:
        engine = create_async_engine(cfg.DATABASE_URL_ASYNC, **engine_kwargs)
    except Exception as exc:
        logging.critical("Failed to create async engine: %s", exc, exc_info=True)
        raise CustomException(
            error_message = "Unable to create database engine. Check DATABASE_URL and connection parameters.",
            error_detail = str(exc),
        ) from exc

    # Emit pool events so pool exhaustion is observable
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn: Any, _: Any) -> None:
        logging.debug("DB pool: new physical connection opened.")

    @event.listens_for(engine.sync_engine, "checkout")
    def _on_checkout(dbapi_conn: Any, _: Any, __: Any) -> None:
        logging.debug("DB pool: connection checked out to caller.")

    @event.listens_for(engine.sync_engine, "checkin")
    def _on_checkin(dbapi_conn: Any, _: Any) -> None:
        logging.debug("DB pool: connection returned to pool.")

    logging.info(
        "Async DB engine created | pool_size=%d | max_overflow=%d | recycle=%ds | echo=%s",
        cfg.DB_POOL_SIZE,
        cfg.DB_MAX_OVERFLOW,
        cfg.DB_POOL_RECYCLE_SECONDS,
        cfg.DB_ECHO_SQL,
    )

    return engine


def get_engine() -> AsyncEngine:
    """Return the singleton engine, building it lazily on first call."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the singleton session factory, building it lazily."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


def AsyncSessionLocal() -> AsyncSession:
    """
    Convenience alias that returns a brand‑new AsyncSession.
    This preserves the callable interface used by FastAPI DI and legacy code.
    """
    return get_session_factory()()


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# Session providers
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency - provides a scoped AsyncSession per HTTP request.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            logging.exception("Database session error occurred; rolling back.")
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_session_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for sessions outside FastAPI (agents, tools, tasks).
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            logging.exception("Database session error in context manager; rolling back.")
            await session.rollback()
            raise
        finally:
            await session.close()


# Application lifecycle helpers
async def init_db() -> None:
    """Verify database connectivity at application startup."""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        logging.info("Database connectivity verified successfully.")
    except Exception as exc:
        logging.critical(
            "Database connectivity check FAILED at startup: %s", exc, exc_info=True
        )
        raise CustomException(
            error_message="Cannot connect to MySQL at startup. Check DATABASE_URL in .env.",
            error_detail=str(exc),
        ) from exc


async def close_db() -> None:
    """Gracefully drain and close the connection pool at shutdown."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    logging.info("Database connection pool closed.")


def get_sync_url() -> str:
    """Return the synchronous DSN (for Alembic's env.py)."""
    return get_settings().db.DATABASE_URL_SYNC