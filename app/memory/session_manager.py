import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_session_context
from app.db.models.memory import SESSION_CHANNELS, ConversationSession
from app.logger import logging

logger = logging.getLogger(__name__)

SESSION_KEY_PREFIX = "session:"

ChannelType = Literal["web", "whatsapp", "kiosk", "api"]


class SessionData(BaseModel):
    session_id: str
    patient_id: Optional[str] = None
    is_authenticated: bool = False
    channel: str = "web"
    is_active: bool = True
    started_at: str
    last_active_at: Optional[str] = None
    metadata: dict[str, Any] = {}


def _session_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def _ttl_seconds() -> int:
    return get_settings().redis.SESSION_TTL_MINUTES * 60


async def create_session(
    redis: Redis,
    patient_id: Optional[str] = None,
    channel: ChannelType = "web",
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    """
    Create a new conversation session.

    Generates a UUID session_id, writes session metadata to Redis as a
    JSON hash under "session:{session_id}", and inserts a row into the
    conversation_sessions table. Returns the session_id.

    Parameters
    ----------
    redis       Async Redis client.
    patient_id  Patient PK if already known (e.g. authenticated API call).
                None for unauthenticated/anonymous sessions.
    channel     Interface the patient is using. One of SESSION_CHANNELS:
                "web", "whatsapp", "kiosk", "api". Default "web".
    metadata    Optional free-form dict (device info, language preference,
                A/B flags). Must be JSON-serializable. Never include PHI.

    Returns
    -------
    The new session_id string (UUID4).
    """
    if channel not in SESSION_CHANNELS:
        raise ValueError(f"Invalid channel {channel!r}. Must be one of {SESSION_CHANNELS}.")

    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    session_data = SessionData(
        session_id=session_id,
        patient_id=patient_id,
        is_authenticated=False,
        channel=channel,
        is_active=True,
        started_at=now_iso,
        last_active_at=now_iso,
        metadata=metadata or {},
    )

    try:
        await redis.setex(
            _session_key(session_id),
            _ttl_seconds(),
            session_data.model_dump_json(),
        )
        logger.info(f"create_session: Redis entry created for session={session_id}")
    except Exception as exc:
        logger.error(f"create_session: Redis write failed for session={session_id}: {exc}")
        raise

    try:
        async with get_session_context() as db:
            row = ConversationSession(
                session_id=session_id,
                patient_id=patient_id,
                started_at=now,
                last_active_at=now,
                channel=channel,
                is_active=True,
                metadata_json=json.dumps(metadata) if metadata else None,
            )
            db.add(row)
    except Exception as exc:
        logger.error(f"create_session: MySQL insert failed for session={session_id}: {exc}")
        raise

    return session_id


async def get_session(
    redis: Redis,
    session_id: str,
) -> Optional[SessionData]:
    """
    Retrieve session metadata for the given session_id.

    Checks Redis first (fast path). If the key is missing — either
    because the session expired from Redis or was never stored there —
    falls back to MySQL, returning the row only if is_active is True.
    Returns None if the session does not exist or has ended.

    Parameters
    ----------
    redis       Async Redis client.
    session_id  The session UUID to look up.

    Returns
    -------
    SessionData on success, or None if not found / expired / inactive.
    """
    try:
        raw = await redis.get(_session_key(session_id))
        if raw is not None:
            data = SessionData.model_validate_json(raw)
            logger.debug(f"get_session: Redis hit for session={session_id}")
            return data
    except Exception as exc:
        logger.error(f"get_session: Redis read failed for session={session_id}: {exc}")

    logger.debug(f"get_session: Redis miss, falling back to MySQL for session={session_id}")
    try:
        async with get_session_context() as db:
            result = await db.execute(
                select(ConversationSession).where(
                    ConversationSession.session_id == session_id,
                    ConversationSession.is_active.is_(True),
                )
            )
            row = result.scalar_one_or_none()

        if row is None:
            logger.info(f"get_session: session={session_id} not found or inactive in MySQL")
            return None

        data = SessionData(
            session_id=row.session_id,
            patient_id=row.patient_id,
            is_authenticated=False,
            channel=row.channel,
            is_active=row.is_active,
            started_at=row.started_at.isoformat(),
            last_active_at=row.last_active_at.isoformat() if row.last_active_at else None,
            metadata=json.loads(row.metadata_json) if row.metadata_json else {},
        )

        try:
            await redis.setex(
                _session_key(session_id),
                _ttl_seconds(),
                data.model_dump_json(),
            )
            logger.info(f"get_session: MySQL hit, re-hydrated Redis for session={session_id}")
        except Exception as exc:
            logger.warning(
                f"get_session: MySQL hit but Redis re-hydration failed for session={session_id}: {exc}"
            )

        return data

    except Exception as exc:
        logger.error(f"get_session: MySQL fallback failed for session={session_id}: {exc}")
        return None


async def touch_session(
    redis: Redis,
    session_id: str,
    patient_id: Optional[str] = None,
    is_authenticated: Optional[bool] = None,
) -> bool:
    """
    Reset the Redis TTL for an active session to SESSION_TTL_MINUTES.

    Also updates last_active_at in the Redis payload (and optionally
    patches patient_id / is_authenticated if these have changed during
    this turn, e.g. immediately after a successful auth flow).

    Does NOT write to MySQL on every touch — MySQL last_active_at is
    updated in batch by a Celery cleanup task (Phase 7) to avoid per-
    message DB writes.

    Parameters
    ----------
    redis             Async Redis client.
    session_id        The session to touch.
    patient_id        If provided, overwrite the stored patient_id
                      (used after verify_identity() succeeds).
    is_authenticated  If provided, overwrite the stored is_authenticated
                      flag (used after verify_identity() succeeds).

    Returns
    -------
    True if the session existed and was refreshed, False if it was
    missing from Redis (expired or never created).
    """
    key = _session_key(session_id)
    try:
        raw = await redis.get(key)
        if raw is None:
            logger.warning(f"touch_session: session={session_id} not found in Redis")
            return False

        data = SessionData.model_validate_json(raw)
        data.last_active_at = datetime.now(timezone.utc).isoformat()

        if patient_id is not None:
            data.patient_id = patient_id
        if is_authenticated is not None:
            data.is_authenticated = is_authenticated

        ttl = _ttl_seconds()
        await redis.setex(key, ttl, data.model_dump_json())

        logger.debug(
            f"touch_session: TTL reset to {ttl}s for session={session_id} "
            f"patient={data.patient_id or 'anonymous'}"
        )
        return True

    except Exception as exc:
        logger.error(f"touch_session: failed for session={session_id}: {exc}")
        return False


async def end_session(redis: Redis, session_id: str) -> None:
    """
    Terminate a session: set is_active=False in MySQL, delete from Redis.

    This is the explicit logout path (DELETE /api/v1/auth/session/{id}).
    Passive expiry (Redis TTL fires with no explicit logout) leaves
    MySQL is_active=True until the Celery cleanup task (Phase 7)
    reconciles it.

    Also deletes the conversation history key ("chat:{session_id}") so
    no orphaned message data remains in Redis after logout.

    Parameters
    ----------
    redis       Async Redis client.
    session_id  The session to terminate.
    """
    from app.memory.redis_history import HISTORY_KEY_PREFIX

    session_key = _session_key(session_id)
    history_key = f"{HISTORY_KEY_PREFIX}{session_id}"

    try:
        await redis.delete(session_key, history_key)
        logger.info(f"end_session: Redis keys deleted for session={session_id}")
    except Exception as exc:
        logger.error(f"end_session: Redis delete failed for session={session_id}: {exc}")

    try:
        async with get_session_context() as db:
            result = await db.execute(
                select(ConversationSession).where(
                    ConversationSession.session_id == session_id
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                row.is_active = False
                row.last_active_at = datetime.now(timezone.utc)

        logger.info(f"end_session: MySQL is_active=False for session={session_id}")
    except Exception as exc:
        logger.error(f"end_session: MySQL update failed for session={session_id}: {exc}")