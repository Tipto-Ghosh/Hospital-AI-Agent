"""
Reusable FastAPI dependency injectors for all route handlers.

All route handlers in the app/api directory should import from here, never
construct DB sessions, Redis clients or decode JWTs directly inside route functions.

Dependency hierarchy:
  - get_db -> AsyncSession(per-request DB session)
  - get_redis -> Redis client(shared pool)
  - get_current_session -> validated SessionData (requires get_redis)
  - get_authenticated_patient -> patient_id str (requires get_current_session)
  - get_current_staff -> StaffTokenData (requires JWT in Authorization header)
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Annotated, Optional
import jwt
from fastapi import Depends, Header, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from redis.asyncio import Redis, ConnectionPool

from app.logger import logging
from app.config import get_settings
from app.db.session import get_db as _get_db, AsyncSessionLocal

logger = logging.getLogger(__name__)

# reexport for route handlers to import from here
get_db = _get_db
settings = get_settings()

# redis connection pool 
_redis_pool: Optional[ConnectionPool] = None

async def get_redis_pool() -> Redis:
    """ 
    Return a shared aioredis client backed by a connection pool.
    
    The pool is created lazily on first request and reused for all subsequent requests.
    Called during lifespan startup for the initial ping check and get_redis() for 
    every request that needs Redis access.
    
    Connection parameters are read from settings.redis so there is one source of truth
    for all redis config.
    """
    global _redis_pool
    if _redis_pool is None:
        cfg = settings.redis
        _redis_pool = ConnectionPool.from_url(
            cfg.REDIS_URL,
            max_connections=cfg.REDIS_MAX_CONNECTIONS,
            socket_timeout=cfg.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=cfg.REDIS_SOCKET_CONNECT_TIMEOUT,
            decode_responses=True,
        )
        logger.info("Created Redis connection pool with max_connections=%d", cfg.REDIS_MAX_CONNECTIONS)
    
    return Redis(connection_pool=_redis_pool)

async def get_redis() -> Redis:
    """
    Return a Redis client backed by the shared connection pool.
    
    This is the dependency to use in route handlers that need Redis access.
    """
    redis = await get_redis_pool()
    return redis

# session data dataclass 
@dataclass
class SessionData:
    """ 
    Validated session payload extracted from Redis.
    
    Fields:
    session_id  The session key used to look up the session in Redis.
    patient_id  The authenticated patient ID
    is_authenticated  True if the session is authenticated, False otherwise
    channel  Interface channel: "web", "mobile", "api", etc.
    message_count   Number of messages exchanged in this session. Enforces 
                    RATE_LIMIT_PER_SESSION guardrail.
    metadata    Arbitrary session metadata.
    """
    session_id: str
    patient_id: Optional[str] = None
    is_authenticated: bool = False
    channel: Optional[str] = "web"
    message_count: int = 0
    metadata: dict = field(default_factory=dict)
    

# session dependency
SESSION_KEY_PREFIX = "session:"

async def get_current_session(
    session_id: Annotated[str, Query(
        description="Session ID issued by POST /api/v1/chat/session",
        min_length=8,
        max_length=128,
    )],
    redis: Redis = Depends(get_redis),
) -> SessionData:
    """
    Validate that a session exists in Redis and is still active.
 
    Raises HTTP 401 if the session is missing (expired or never created).
    Raises HTTP 429 if the session has exceeded RATE_LIMIT_PER_SESSION.
 
    The session is stored in Redis as a JSON hash under the key
    'session:<session_id>'.  The TTL is reset on every successful
    validation (sliding expiry).
 
    Parameters
    ----------
    session_id      Passed as a query parameter ?session_id=...
                    or extracted from the request body for WebSocket
                    connections.
    redis           Injected Redis client.
 
    Returns
    -------
    SessionData with all fields populated from Redis.
    """
    redis_key = f"{SESSION_KEY_PREFIX}{session_id}"
 
    try:
        raw = await redis.get(redis_key)
    except Exception as exc:
        logger.error("Redis error reading session %r: %s", session_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session service temporarily unavailable.",
        )
 
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Session not found or expired. "
                "Start a new session via POST /api/v1/chat/session."
            ),
        )
 
    try:
        data: dict = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.error("Corrupt session data for session_id=%r", session_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session data is corrupt. Please start a new session.",
        )
 
    # Enforce per-session message rate limit
    msg_count = int(data.get("message_count", 0))
    limit = settings.security.RATE_LIMIT_PER_SESSION
    if msg_count >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Session message limit ({limit}) reached. "
                "Please start a new session."
            ),
            headers={"Retry-After": "0"},
        )
 
    # Slide the TTL — resets the 30-minute inactivity clock
    ttl_seconds = settings.redis.SESSION_TTL_MINUTES * 60
    await redis.expire(redis_key, ttl_seconds)
 
    return SessionData(
        session_id=session_id,
        patient_id=data.get("patient_id"),
        is_authenticated=bool(data.get("is_authenticated", False)),
        channel=data.get("channel", "web"),
        message_count=msg_count,
        metadata=data.get("metadata", {}),
    )
 
 
# Authenticated patient dependency 
async def get_authenticated_patient(
    session: SessionData = Depends(get_current_session),
) -> str:
    """
    Extract the authenticated patient_id from a validated session.
 
    Raises HTTP 403 if the session exists but the patient has not yet
    completed the verify_identity() authentication flow.
 
    Route handlers that access PHI (records, billing, prescriptions)
    must declare this dependency, NOT just get_current_session.
 
    Returns
    -------
    patient_id      The authenticated patient's PK string.
    """
    if not session.is_authenticated or not session.patient_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Identity verification required. "
                "Please verify your identity via POST /api/v1/auth/verify "
                "before accessing personal records."
            ),
        )
    return session.patient_id
 
 
# Staff JWT data
@dataclass
class StaffTokenData:
    """
    Claims decoded from a valid staff JWT.
 
    Fields
    ------
    staff_id        Staff user identifier (sub claim).
    email           Staff email address.
    role            Role string: 'admin' | 'doctor' | 'billing' | 'receptionist'.
    hospital_name   Validates the token was issued for this hospital.
    """
    staff_id: str
    email: str
    role: str
    hospital_name: str
 
 
_bearer_scheme = HTTPBearer(auto_error=False)
 
STAFF_ROLES = {"admin", "doctor", "billing", "receptionist"}
 
 
async def get_current_staff(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(_bearer_scheme),
    ] = None,
) -> StaffTokenData:
    """
    Verify a staff Bearer JWT and return its decoded claims.
 
    Raises HTTP 401 if no token is provided.
    Raises HTTP 403 if the token is invalid, expired, or has an
    unrecognised role.
 
    The JWT must be signed with JWT_SECRET_KEY (HS256) and contain:
        sub           staff identifier string
        email         staff email
        role          one of: admin | doctor | billing | receptionist
        hospital      must match settings.HOSPITAL_NAME
        exp           standard JWT expiry claim
 
    Issued by POST /api/v1/auth/staff-login (Phase 5).
 
    Parameters
    ----------
    credentials     Extracted from the Authorization: Bearer <token> header
                    by the HTTPBearer scheme.  auto_error=False so we can
                    return a 401 with our own error envelope.
 
    Returns
    -------
    StaffTokenData with all decoded claims.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Staff authentication required. Provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
 
    token = credentials.credentials
    sec = settings.security
 
    try:
        payload = jwt.decode(
            token,
            sec.JWT_SECRET_KEY,
            algorithms=[sec.JWT_ALGORITHM],
            options={"require": ["exp", "sub", "email", "role", "hospital"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff token has expired. Please log in again.",
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid staff JWT: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid staff token.",
        )
 
    role = payload.get("role", "")
    if role not in STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Unknown staff role: {role!r}.",
        )
 
    hospital = payload.get("hospital", "")
    if hospital != settings.HOSPITAL_NAME:
        logger.warning(
            "Staff token hospital mismatch: got %r, expected %r",
            hospital, settings.HOSPITAL_NAME,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token was not issued for this hospital.",
        )
 
    return StaffTokenData(
        staff_id=payload["sub"],
        email=payload["email"],
        role=role,
        hospital_name=hospital,
    )
 
 
async def require_admin(
    staff: StaffTokenData = Depends(get_current_staff),
) -> StaffTokenData:
    """
    Stricter dependency requires the 'admin' role specifically.
 
    Use this for destructive or sensitive admin operations like
    querying audit logs or updating hospital info.
 
    Raises HTTP 403 if the authenticated staff member's role is not 'admin'.
    """
    if staff.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Admin role required. Your role: {staff.role!r}.",
        )
    return staff