"""
Patient identity verification — the authentication gate for the
Patient Records and Billing agents.

Endpoints
POST: /api/v1/auth/verify - verify identity, issue session JWT
DELETE /api/v1/auth/session/{session_id} - logout, remove session from Redis
"""

from __future__ import annotations
import json
import jwt
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_redis
from app.config import get_settings
from app.db.repositories.audit_repo import AuditRepository
from app.db.repositories.patient_repo import PatientRepository
from app.logger import logging

settings = get_settings()
router = APIRouter()
SESSION_KEY_PREFIX = "session:"

class VerifyRequest(BaseModel):
    """Request body for POST /api/v1/auth/verify."""
    session_id: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Existing chat session ID to attach authentication to.",
    )
    patient_id: str = Field(
        ...,
        min_length=5,
        max_length=20,
        description="Patient ID as claimed by the caller, e.g. 'P-2024-00001'.",
    )
    date_of_birth: date = Field(
        ...,
        description="Date of birth in YYYY-MM-DD format.",
    )
    phone_last4: str = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Last 4 digits of the registered phone number.",
    )

    @field_validator("phone_last4")
    @classmethod
    def _digits_only(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("phone_last4 must be exactly 4 digits.")
        return v

    @field_validator("patient_id")
    @classmethod
    def _patient_id_format(cls, v: str) -> str:
        if not v.startswith("P-"):
            raise ValueError("patient_id must start with 'P-', e.g. 'P-2024-00001'.")
        return v

class VerifyResponse(BaseModel):
    """Response body for a successful POST /api/v1/auth/verify."""

    session_token: str = Field(description="Short-lived JWT (15-min TTL).")
    expires_at: str = Field(description="ISO 8601 UTC expiry timestamp.")
    patient_id: str = Field(description="Verified patient PK.")
    session_id: str


class LogoutResponse(BaseModel):
    """Response body for DELETE /api/v1/auth/session/{session_id}."""

    session_id: str
    message: str

def _issue_jwt(patient_id: str, session_id: str) -> tuple[str, datetime]:
    """
    Create a short-lived JWT for the verified patient session.

    Payload contains ONLY: sub (patient_id), session_id, iat, exp.
    No name, DOB, phone, or any other PHI is embedded in the token —
    JWTs are base64-encoded, not encrypted, and may be logged by
    intermediate proxies.

    Returns
    -------
    (token, expires_at_utc)
    """
    sec = settings.security
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=sec.JWT_EXPIRY_MINUTES)

    payload = {
        "sub": patient_id,
        "session_id": session_id,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, sec.JWT_SECRET_KEY, algorithm=sec.JWT_ALGORITHM)
    return token, expires_at


# POST /api/v1/auth/verify
@router.post(
    "/auth/verify",
    response_model=VerifyResponse,
    summary="Verify patient identity and authenticate the session",
    description=(
        "Verifies patient_id + date_of_birth + last 4 digits of phone "
        "against the patients table. On success, issues a short-lived JWT "
        "and marks the chat session as authenticated in Redis, unlocking "
        "access to Patient Records and Billing endpoints for this session."
    ),
    responses={
        200: {"description": "Identity verified — session authenticated"},
        401: {"description": "Identity verification failed"},
        404: {"description": "Chat session not found"},
    },
)
async def verify_identity(
    body: VerifyRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> VerifyResponse:
    """
    Multi-factor identity verification.
    """
    # 1.Confirm the chat session exists 
    session_key = f"{SESSION_KEY_PREFIX}{body.session_id}"
    raw_session = await redis.get(session_key)

    if raw_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Chat session not found or expired. "
                "Create a new session via POST /api/v1/chat/session."
            ),
        )

    try:
        session_data: dict = json.loads(raw_session)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session data is corrupt. Please create a new session.",
        )

    # 2. Verify identity against the patients table
    patient_repo = PatientRepository(db)
    audit_repo = AuditRepository(db)

    is_valid = await patient_repo.verify_identity(
        patient_id=body.patient_id,
        dob=body.date_of_birth,
        phone_last4=body.phone_last4,
    )

    if not is_valid:
        await audit_repo.log(
            agent_name="auth_route",
            action="auth_verify_failed",
            session_id=body.session_id,
            patient_id=body.patient_id,  # claimed, not verified
            payload_summary="Identity verification failed (factor mismatch).",
        )
        await db.commit()

        logging.warning(
            "Failed identity verification: session=%s... claimed_patient=%s",
            body.session_id[:8], body.patient_id,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Identity verification failed. "
                "Please check your patient ID, date of birth, and phone number."
            ),
        )

    # 3. Issue JWT 
    token, expires_at = _issue_jwt(body.patient_id, body.session_id)

    # 4. Update Redis session: mark authenticated 
    session_data["is_authenticated"] = True
    session_data["patient_id"] = body.patient_id

    ttl = settings.redis.SESSION_TTL_MINUTES * 60
    await redis.setex(session_key, ttl, json.dumps(session_data))

    # 5. Audit log - success
    await audit_repo.log(
        agent_name="auth_route",
        action="auth_verify_success",
        session_id=body.session_id,
        patient_id=body.patient_id,
        payload_summary="Identity verified successfully.",
    )
    await db.commit()

    logging.info(
        "Identity verified: session=%s... patient=%s",
        body.session_id[:8], body.patient_id,
    )

    return VerifyResponse(
        session_token=token,
        expires_at=expires_at.isoformat(),
        patient_id=body.patient_id,
        session_id=body.session_id,
    )


# DELETE /api/v1/auth/session/{session_id} 

@router.delete(
    "/auth/session/{session_id}",
    response_model=LogoutResponse,
    summary="Log out — remove session from Redis",
    description=(
        "Removes the chat session and any authentication state from Redis. "
        "The session_id becomes immediately invalid. The patient must "
        "start a new session via POST /api/v1/chat/session afterward."
    ),
    responses={
        200: {"description": "Session removed (idempotent — also returns 200 "
                              "if the session was already gone)"},
    },
)
async def logout(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> LogoutResponse:
    """
    Remove a session from Redis, ending both the chat session and any
    authenticated state.

    Idempotent: calling this on an already-expired or nonexistent
    session_id still returns 200 — logout always "succeeds" from the
    caller's perspective.

    Also removes the associated conversation memory key
    (memory:<session_id>) so no orphaned data remains in Redis.
    """
    session_key = f"{SESSION_KEY_PREFIX}{session_id}"
    memory_key = f"memory:{session_id}"

    # Check if it existed (for audit logging) before deleting
    raw_session = await redis.get(session_key)
    patient_id: str | None = None
    if raw_session:
        try:
            session_data: dict = json.loads(raw_session)
            patient_id = session_data.get("patient_id")
        except json.JSONDecodeError:
            pass

    await redis.delete(session_key, memory_key)

    # Audit the logout event (only if there was something to log out of)
    if raw_session is not None:
        audit_repo = AuditRepository(db)
        await audit_repo.log(
            agent_name="auth_route",
            action="logout",
            session_id=session_id,
            patient_id=patient_id,
            payload_summary="Session terminated by patient.",
        )
        await db.commit()

        logging.info(
            "Session logged out: session=%s... patient=%s",
            session_id[:8], patient_id or "anonymous",
        )

    return LogoutResponse(
        session_id=session_id,
        message="Session ended successfully.",
    )