"""
FastAPI database session dependency.

This module is the single import point for all FastAPI route handlers that need a database session.  
It wraps the base session factories so that every session lifecycle event is logged and any unexpected 
error is re-raised as a Exception for consistent error reporting.
"""

from __future__ import annotations
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logging
from app.exception import CustomException
from app.db.base import AsyncSessionLocal as AsyncSessionLocal

# FastAPI dependency: logged and wrapped
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a database session.
    """
    logging.debug("Acquiring database session via get_db dependency.")
    from app.db.base import get_db_session as _base_get_db
    
    session: AsyncSession | None = None 
    
    try:
        async for session in _base_get_db():
            yield session
    except CustomException:
        raise 
    except Exception as exc:
        logging.exception("Unhandled error in get_db dependency session.")
        raise CustomException(
            error_message="Database session error in FastAPI dependency.",
            error_detail=str(exc),
        ) from exc
    finally:
        if session is not None:
            logging.debug("Database session returned to pool (get_db).")
            
# Context manager for agents / tasks – logged & wrapped
from contextlib import asynccontextmanager
@asynccontextmanager
async def session_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for use outside FastAPI DI.

    Wraps ``app.db.base.get_session_context`` with the same logging and
    exception handling as ``get_db``.
    """
    logging.debug("Acquiring database session via session_context manager.")
    from app.db.base import get_session_context as _base_session_context

    session: AsyncSession | None = None
    try:
        async with _base_session_context() as session:
            yield session
    except CustomException:
        raise
    except Exception as exc:
        logging.exception("Unhandled error in session_context context manager.")
        raise CustomException(
            error_message="Database session error in context manager.",
            error_detail=str(exc),
        ) from exc
    finally:
        if session is not None:
            logging.debug("Database session returned to pool (session_context).")


__all__ = [
    "AsyncSessionLocal",
    "get_db",
    "session_context",
]