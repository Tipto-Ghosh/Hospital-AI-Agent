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
from sqlalchemy.orm import DeclarativeBase, MappedColumn
from sqlalchemy.pool import NullPool
 
from app.config import get_settings
from app.logger import logging
from app.exception import CustomException


# Database Engine Factory
def _build_engine() -> AsyncEngine:
    """
    Create the async SQLAlchemy engine from centralised settings.
    """
    settings = get_settings()
    cfg = settings.db
    use_null_pool = "no_pool=true" in cfg.DATABASE_URL_ASYNC
 
    engine_kwargs: dict[str, Any] = {
        "echo": cfg.DB_ECHO_SQL,
        "pool_pre_ping": True,
        "pool_recycle": cfg.DB_POOL_RECYCLE_SECONDS,
        "connect_args": {
            # asyncmy-specific: enforce UTF-8 and a sane statement timeout
            "charset": "utf8mb4",
            # MySQL server-side connect timeout (seconds)
            "connect_timeout": 10,
        },
    }
 
    if use_null_pool:
        engine_kwargs["poolclass"] = NullPool
        logging.info("DB engine: using NullPool (no_pool flag detected in URL).")
    else:
        engine_kwargs["pool_size"] = cfg.DB_POOL_SIZE
        engine_kwargs["max_overflow"] = cfg.DB_MAX_OVERFLOW
        engine_kwargs["pool_timeout"] = 30  # seconds
 
    try:
        engine = create_async_engine(cfg.DATABASE_URL_ASYNC, **engine_kwargs)
    except Exception as exc:
        logging.critical("Failed to create async engine: %s", exc, exc_info=True)
        raise CustomException(
            error_message="Unable to create database engine. Check DATABASE_URL and connection parameters.",
            error_detail=str(exc),
        ) from exc
 
    # Emit pool events to the logging so pool exhaustion is observable
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

engine: AsyncEngine = _build_engine()

# Session Factory
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind = engine,
    class_ = AsyncSession,
    expire_on_commit = False,   
    autocommit = False,
    autoflush = False, 
)


class Base(DeclarativeBase):
    """ 
    Shared declarative base for all ORM models.
    """
    pass 

# FastAPI dependency - async session per request
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """ 
    FastAPI dependency that provides a scoped AsyncSession per HTTP request.
 
    - Opens a new session on entry.
    - Commits on clean exit.
    - Rolls back and re-raises on any exception — the request never leaves
      the handler in a partially-committed state.
    - Always closes the session (returns connection to pool) in the finally block.
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
    
# Context manager for use outside FastAPI (agents, tools, Celery tasks)
@asynccontextmanager
async def get_session_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions outside of FastAPI's DI system.
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
    """
    Verify database connectivity at application startup.
    """
    try:
        async with engine.connect() as conn:
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
    """
    Gracefully drain and close the connection pool at application shutdown.
    """
    await engine.dispose()
    logging.info("Database connection pool closed.")

def get_sync_url() -> str:
    """
    Returns the synchronous DSN (pymysql driver) for Alembic's env.py.
    """
    return get_settings().db.DATABASE_URL_SYNC