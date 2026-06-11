from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.dependencies import (
    SessionData,
    get_authenticated_patient,
    get_current_session,
    get_db,
    get_redis,
)
from app.config import get_settings
from app.logger import logging

settings = get_settings()

router = APIRouter()

SESSION_KEY_PREFIX = "session:"
MEMORY_KEY_PREFIX  = "memory:"
class ChatRequest(BaseModel):
    """Request body for POST /api/v1/chat."""
    session_id: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Session ID obtained from POST /api/v1/chat/session.",
    )
    text: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Patient message text.",
    )


class ChatResponse(BaseModel):
    """Response body for POST /api/v1/chat."""

    session_id: str
    response: str = Field(description="Agent's reply to the patient.")
    agent: str = Field(description="Name of the sub-agent that handled the turn.")
    intent: Optional[str] = Field(None, description="Detected patient intent.")
    is_emergency: bool = Field(False, description="True if emergency routing was triggered.")
    turn: int = Field(description="Turn number within this session.")


class SessionCreateRequest(BaseModel):
    """Request body for POST /api/v1/chat/session."""

    channel: str = Field(
        default="web",
        pattern="^(web|whatsapp|kiosk|api)$",
        description="Interface channel.",
    )
    language: str = Field(
        default="en",
        min_length=2,
        max_length=10,
        description="Preferred language (ISO 639-1 code).",
    )


class SessionCreateResponse(BaseModel):
    """Response body for POST /api/v1/chat/session."""
    session_id: str
    channel: str
    expires_in_seconds: int
    message: str

async def _invoke_graph(
    session_id: str,
    patient_id: Optional[str],
    text: str,
    turn: int,
    db: AsyncSession,
    redis: Redis,
) -> dict[str, Any]:
    
    text_lower = text.lower()

    # Emergency detection
    emergency_keywords = {
        "chest pain", "can't breathe", "cannot breathe", "stroke",
        "heart attack", "unconscious", "not responding", "severe bleeding",
        "overdose", "seizure", "emergency",
    }
    if any(kw in text_lower for kw in emergency_keywords):
        return {
            "response": (
                "🚨 EMERGENCY DETECTED 🚨\n\n"
                "Please call our Emergency Department immediately:\n"
                "📞 Emergency Hotline: 109 (24/7)\n"
                "📞 Ambulance: 01711-AMBU (01711-2628)\n\n"
                "If this is a life-threatening emergency, "
                "please call 999 or go to the Emergency entrance "
                "(Ground Floor, Block A) right away.\n\n"
                "Do not wait — your safety comes first."
            ),
            "agent": "emergency_agent",
            "intent": "emergency",
            "is_emergency": True,
        }

    # Appointment booking
    if any(kw in text_lower for kw in ["book", "appointment", "schedule", "reserve"]):
        return {
            "response": (
                "I'd be happy to help you book an appointment. "
                "Could you tell me which doctor or department you'd like to visit, "
                "and your preferred date?"
            ),
            "agent": "booking_agent",
            "intent": "book_appointment",
            "is_emergency": False,
        }

    # General information
    return {
        "response": (
            f"Hello! I'm the {settings.HOSPITAL_NAME} AI Assistant. "
            "I can help you with appointment booking, doctor information, "
            "billing queries, medication information, and more. "
            "How can I assist you today?"
        ),
        "agent": "info_agent",
        "intent": "general_info",
        "is_emergency": False,
    }


# Session helpers
async def _update_session_turn(
    redis: Redis,
    session_id: str,
    session_data: dict,
    turn: int,
) -> None:
    """Persist the updated message count back to Redis after a turn."""
    session_data["message_count"] = turn
    ttl = settings.redis.SESSION_TTL_MINUTES * 60
    key = f"{SESSION_KEY_PREFIX}{session_id}"
    await redis.setex(key, ttl, json.dumps(session_data))


async def _append_to_memory(
    redis: Redis,
    session_id: str,
    role: str,
    content: str,
    agent_name: Optional[str] = None,
) -> None:
    """
    Append a message turn to the Redis sliding-window conversation history.

    Keeps the last REDIS_HISTORY_WINDOW messages per session.
    Used by the agents to load recent conversation context.
    """
    key = f"{MEMORY_KEY_PREFIX}{session_id}"
    entry = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if agent_name:
        entry["agent"] = agent_name

    await redis.rpush(key, json.dumps(entry))

    # Trim to sliding window
    window = settings.redis.REDIS_HISTORY_WINDOW
    await redis.ltrim(key, -window, -1)

    # Reset TTL on the memory key alongside the session
    ttl = settings.redis.SESSION_TTL_MINUTES * 60
    await redis.expire(key, ttl)


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a message to the hospital AI",
    description=(
        "Single-turn HTTP chat endpoint. "
        "The request is routed through the LangGraph supervisor to the "
        "appropriate sub-agent. "
        "For real-time streaming, use the WebSocket endpoint instead."
    ),
    responses={
        200: {"description": "Agent response"},
        401: {"description": "Session not found or expired"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def chat(
    body: ChatRequest,
    session: SessionData = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> ChatResponse:
    """
    Process one patient message turn and return the agent response.

    The session_id in the request body must match the query parameter
    used to validate the session.  This double-check prevents session
    fixation attacks.
    """
    if body.session_id != session.session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id in body does not match session_id query parameter.",
        )

    turn = session.message_count + 1

    logging.info(
        "chat turn=%d session=%s... patient=%s",
        turn,
        session.session_id[:8],
        session.patient_id or "anonymous",
    )

    # Append patient message to Redis memory
    await _append_to_memory(redis, session.session_id, "human", body.text)

    # Invoke the agent graph
    result = await _invoke_graph(
        session_id=session.session_id,
        patient_id=session.patient_id,
        text=body.text,
        turn=turn,
        db=db,
        redis=redis,
    )

    # Append agent response to Redis memory
    await _append_to_memory(
        redis, session.session_id,
        "ai", result["response"],
        agent_name=result["agent"],
    )

    # Persist updated turn count
    session_raw = {
        "patient_id": session.patient_id,
        "is_authenticated": session.is_authenticated,
        "channel": session.channel,
        "message_count": turn,
        "metadata": session.metadata,
    }
    await _update_session_turn(redis, session.session_id, session_raw, turn)

    return ChatResponse(
        session_id=session.session_id,
        response=result["response"],
        agent=result["agent"],
        intent=result.get("intent"),
        is_emergency=result.get("is_emergency", False),
        turn=turn,
    )


# POST /api/v1/chat/session 
@router.post(
    "/chat/session",
    response_model=SessionCreateResponse,
    summary="Create a new chat session",
    status_code=status.HTTP_201_CREATED,
    description=(
        "Create a new conversation session and receive a session_id. "
        "Pass this session_id to every subsequent /chat request."
    ),
)
async def create_session(
    body: SessionCreateRequest,
    redis: Redis = Depends(get_redis),
) -> SessionCreateResponse:
    """
    Initialise a new Redis session and return the session_id.

    The session starts unauthenticated.  Use POST /api/v1/auth/verify
    to authenticate the patient within this session.
    """
    session_id = f"sess_{uuid.uuid4().hex}"
    ttl = settings.redis.SESSION_TTL_MINUTES * 60

    session_data = {
        "patient_id": None,
        "is_authenticated": False,
        "channel": body.channel,
        "message_count": 0,
        "metadata": {"language": body.language},
    }

    key = f"{SESSION_KEY_PREFIX}{session_id}"
    await redis.setex(key, ttl, json.dumps(session_data))

    logging.info(
        f"Session created: {session_id[:8]}... channel={body.channel}"
    )

    return SessionCreateResponse(
        session_id=session_id,
        channel=body.channel,
        expires_in_seconds=ttl,
        message=(
            f"Session created. You have {settings.security.RATE_LIMIT_PER_SESSION} "
            f"messages before the session must be refreshed."
        ),
    )


# GET /api/v1/chat/history/{session_id}
@router.get(
    "/chat/history/{session_id}",
    summary="Retrieve conversation history for a session",
    description=(
        "Returns the sliding-window message history stored in Redis "
        "for the given session. Requires session ownership (session_id "
        "must match the validated session)."
    ),
)
async def get_history(
    session_id: str,
    session: SessionData = Depends(get_current_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    """
    Return the last N messages from the Redis conversation memory.

    The path parameter session_id must match the authenticated session
    to prevent cross-session data leakage.
    """
    if session_id != session.session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access history for a different session.",
        )

    key = f"{MEMORY_KEY_PREFIX}{session_id}"
    raw_messages = await redis.lrange(key, 0, -1)

    messages = []
    for raw in raw_messages:
        try:
            messages.append(json.loads(raw))
        except json.JSONDecodeError:
            pass  # skip corrupt entries

    return {
        "session_id": session_id,
        "message_count": len(messages),
        "messages": messages,
    }


# WebSocket /api/v1/chat/ws/{session_id}
@router.websocket("/chat/ws/{session_id}")
async def chat_websocket(
    websocket: WebSocket,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    
    await websocket.accept()

    # Validate session 
    redis_key = f"{SESSION_KEY_PREFIX}{session_id}"
    try:
        raw = await redis.get(redis_key)
    except Exception as exc:
        await websocket.send_json({
            "type": "error",
            "code": 503,
            "message": "Session service unavailable.",
        })
        await websocket.close(code=1011)
        return

    if raw is None:
        await websocket.send_json({
            "type": "error",
            "code": 401,
            "message": (
                "Session not found or expired. "
                "Create a new session via POST /api/v1/chat/session."
            ),
        })
        await websocket.close(code=4001)  # custom: session expired
        return

    try:
        session_data: dict = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.send_json({
            "type": "error",
            "code": 401,
            "message": "Session data is corrupt. Please create a new session.",
        })
        await websocket.close(code=4001)
        return

    patient_id: Optional[str] = session_data.get("patient_id")
    turn = int(session_data.get("message_count", 0))

    logging.info(
        f"WebSocket connected: session={session_id[:8]}... patient={patient_id or 'anonymous'}"
    )

    # Message loop
    try:
        while True:
            # Receive message from client
            try:
                raw_frame = await websocket.receive_text()
            except WebSocketDisconnect:
                logging.info(
                    f"WebSocket disconnected: session={session_id[:8]}...", 
                )
                break

            # Parse and validate frame
            try:
                frame: dict = json.loads(raw_frame)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "code": 400,
                    "message": "Invalid JSON frame.",
                })
                continue

            if frame.get("type") != "message":
                await websocket.send_json({
                    "type": "error",
                    "code": 400,
                    "message": (
                        f"Unknown frame type: {frame.get('type')!r}. "
                        "Expected: 'message'."
                    ),
                })
                continue

            text = str(frame.get("text", "")).strip()
            if not text:
                await websocket.send_json({
                    "type": "error",
                    "code": 400,
                    "message": "Message text cannot be empty.",
                })
                continue

            if len(text) > 4000:
                await websocket.send_json({
                    "type": "error",
                    "code": 400,
                    "message": "Message exceeds 4000 character limit.",
                })
                continue

            # Check per-session rate limit
            limit = settings.security.RATE_LIMIT_PER_SESSION
            if turn >= limit:
                await websocket.send_json({
                    "type": "error",
                    "code": 429,
                    "message": (
                        f"Session message limit ({limit}) reached. "
                        "Please start a new session."
                    ),
                })
                await websocket.close(code=4029)  # custom: rate limited
                break

            turn += 1

            # Append patient turn to Redis memory
            await _append_to_memory(redis, session_id, "human", text)

            # Invoke agent graph
            try:
                result = await _invoke_graph(
                    session_id=session_id,
                    patient_id=patient_id,
                    text=text,
                    turn=turn,
                    db=db,
                    redis=redis,
                )
            except Exception as exc:
                logging.exception(
                    f"Graph invocation error: session={session_id[:8]}... error={exc}"
                )
                await websocket.send_json({
                    "type": "error",
                    "code": 500,
                    "message": (
                        "An error occurred processing your message. "
                        "Please try again."
                    ),
                })
                continue

            agent_name = result["agent"]
            response_text = result["response"]

            # Stream response as word-level chunks
            words = response_text.split(" ")
            for i, word in enumerate(words):
                chunk = word if i == 0 else f" {word}"
                await websocket.send_json({
                    "type": "chunk",
                    "content": chunk,
                    "agent": agent_name,
                })

            # Append agent response to Redis memory
            await _append_to_memory(
                redis, session_id, "ai", response_text, agent_name=agent_name
            )

            # Persist updated turn count
            session_data["message_count"] = turn
            ttl = settings.redis.SESSION_TTL_MINUTES * 60
            await redis.setex(redis_key, ttl, json.dumps(session_data))

            # End-of-turn done frame
            await websocket.send_json({
                "type": "done",
                "session_id": session_id,
                "metadata": {
                    "agent":        agent_name,
                    "intent":       result.get("intent"),
                    "is_emergency": result.get("is_emergency", False),
                    "turn":         turn,
                },
            })

            logging.info(
                "WS turn=%d session=%s... agent=%s intent=%s",
                turn,
                session_id[:8],
                agent_name,
                result.get("intent", "unknown"),
            )

    except WebSocketDisconnect:
        logging.info("WebSocket disconnected (outer): session=%s...", session_id[:8])
    except Exception as exc:
        logging.exception(
            "Unhandled WebSocket error: session=%s... error=%s",
            session_id[:8], exc,
        )
        try:
            await websocket.send_json({
                "type": "error",
                "code": 500,
                "message": "Internal server error. Connection closing.",
            })
            await websocket.close(code=1011)
        except Exception:
            pass  # connection may already be closed