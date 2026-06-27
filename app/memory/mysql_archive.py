import json
from datetime import datetime, timezone
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import select

from app.agents.state import HospitalAgentState
from app.config import get_settings
from app.db.base import get_session_context
from app.db.models.memory import ConversationMemory, PatientLongTermContext
from app.logger import logging
from app.memory.redis_history import RedisMessageHistory
from app.memory.session_manager import SessionData, get_session, touch_session

logger = logging.getLogger(__name__)


def _get_redis():
    """
    Lazy import of the shared Redis client to avoid circular imports at
    module load time (dependencies.py imports graph.py indirectly via
    main.py).
    """
    import asyncio
    from app.api.dependencies import get_redis_pool
    return asyncio.get_event_loop().run_until_complete(get_redis_pool())


def _infer_last_concern(state: HospitalAgentState) -> Optional[str]:
    """
    Produce a short, non-clinical, non-PHI summary of what the patient
    raised in this turn for storage in patient_long_term_context.last_concern.

    Uses state["intent"] and state["active_agent"] rather than the raw
    message text so no patient-spoken content is stored in this field.
    The intent label is human-readable enough on its own; agent name
    adds context for operations.

    Returns None if intent is None or "out_of_scope" / "unknown" -
    those aren't useful signals to keep.
    """
    intent = state.get("intent")
    if not intent or intent in ("out_of_scope", "unknown"):
        return None

    agent = state.get("active_agent") or ""

    label_map: dict[str, str] = {
        "general_info": "asked for general hospital information",
        "doctor_info": "asked about a doctor or specialist",
        "book_appointment": "requested appointment booking",
        "cancel_appointment": "requested appointment cancellation",
        "reschedule_appointment": "requested appointment reschedule",
        "patient_records": "accessed patient records",
        "billing": "asked about billing or insurance",
        "medication_info": "asked for medication information",
        "feedback": "submitted feedback or complaint",
        "emergency": "triggered emergency triage",
    }

    description = label_map.get(intent, f"intent={intent}")
    if agent:
        return f"{description} (via {agent})"
    return description


async def _load_patient_long_term_context(patient_id: str) -> Optional[dict[str, Any]]:
    """
    Fetch the patient_long_term_context row for patient_id from MySQL.

    Returns a plain dict with preference signals that can be merged
    into state, or None if no row exists yet for this patient.

    Keys returned: preferred_doctor, preferred_time_slot,
    language_preference, communication_opt_in, last_concern.
    """
    try:
        async with get_session_context() as db:
            result = await db.execute(
                select(PatientLongTermContext).where(
                    PatientLongTermContext.patient_id == patient_id
                )
            )
            row = result.scalar_one_or_none()

        if row is None:
            return None

        return {
            "preferred_doctor": row.preferred_doctor,
            "preferred_time_slot": row.preferred_time_slot,
            "language_preference": row.language_preference,
            "communication_opt_in": row.communication_opt_in,
            "last_concern": row.last_concern,
        }
    except Exception as exc:
        logger.error(
            f"_load_patient_long_term_context: MySQL read failed for patient={patient_id}: {exc}"
        )
        return None


async def _upsert_patient_long_term_context(
    patient_id: str,
    last_concern: Optional[str],
    entities: dict[str, Any],
) -> None:
    """
    Create or update the patient_long_term_context row for patient_id.

    Updates last_concern if one was inferred for this turn.
    Also updates preferred_doctor if entities["doctor_id"] is present
    (the patient has indicated a doctor preference in this turn), and
    preferred_time_slot if entities["time"] is a time-of-day keyword.

    All writes are best-effort — failures are logged, never raised, so
    a context update failure never blocks the response delivery.
    """
    try:
        async with get_session_context() as db:
            result = await db.execute(
                select(PatientLongTermContext).where(
                    PatientLongTermContext.patient_id == patient_id
                )
            )
            row = result.scalar_one_or_none()

            now = datetime.now(timezone.utc)

            if row is None:
                row = PatientLongTermContext(
                    patient_id=patient_id,
                    language_preference="en",
                    communication_opt_in=True,
                )
                db.add(row)

            if last_concern is not None:
                row.last_concern = last_concern

            if entities.get("doctor_id"):
                try:
                    row.preferred_doctor = int(entities["doctor_id"])
                except (TypeError, ValueError):
                    pass

            time_val = str(entities.get("time", "")).lower()
            if time_val in ("morning", "afternoon", "evening"):
                row.preferred_time_slot = time_val

            row.updated_at = now

        logger.debug(
            f"_upsert_patient_long_term_context: updated for patient={patient_id} "
            f"last_concern={last_concern!r}"
        )
    except Exception as exc:
        logger.error(
            f"_upsert_patient_long_term_context: MySQL upsert failed for patient={patient_id}: {exc}"
        )


async def _archive_messages_to_mysql(
    session_id: str,
    patient_id: Optional[str],
    messages: list[BaseMessage],
    active_agent: Optional[str],
) -> None:
    """
    Write a list of messages to conversation_memory in MySQL.

    Maps LangChain message types to the role enum ("human", "ai",
    "system"). agent_name is only stored for AIMessage rows and is
    taken from state["active_agent"] — the node that produced the last
    response.

    All writes are best-effort — failures are logged, never raised.
    """
    if not messages:
        return

    try:
        async with get_session_context() as db:
            for message in messages:
                if isinstance(message, HumanMessage):
                    role = "human"
                    agent_name = None
                elif isinstance(message, AIMessage):
                    role = "ai"
                    agent_name = active_agent
                else:
                    role = "system"
                    agent_name = None

                content = (
                    message.content
                    if isinstance(message.content, str)
                    else str(message.content)
                )

                if not content.strip():
                    continue

                db.add(ConversationMemory(
                    session_id=session_id,
                    patient_id=patient_id,
                    role=role,
                    content=content,
                    agent_name=agent_name,
                ))

        logger.debug(
            f"_archive_messages_to_mysql: archived {len(messages)} message(s) "
            f"for session={session_id}"
        )
    except Exception as exc:
        logger.error(
            f"_archive_messages_to_mysql: MySQL write failed for session={session_id}: {exc}"
        )


async def load_session_memory_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    Load Redis message history and patient long-term
    context into the graph state at the start of each turn.

    Returns
    -------
    A partial state update dict with updated "messages" and, if a
    patient is known, "entities" enriched with their preference signals.
    """
    session_id = state["session_id"]

    try:
        from app.api.dependencies import get_redis_pool
        redis = await get_redis_pool()
    except Exception as exc:
        logger.error(f"load_session_memory_node: Redis unavailable for session={session_id}: {exc}")
        return {}

    session_data: Optional[SessionData] = await get_session(redis, session_id)

    if session_data is None:
        logger.warning(
            f"load_session_memory_node: session={session_id} not found in Redis or MySQL"
        )
        return {}

    history = RedisMessageHistory(session_id=session_id, redis_client=redis)
    prior_messages = await history.aget_messages()

    current_messages = state.get("messages", [])

    if prior_messages:
        combined_messages = prior_messages + current_messages
    else:
        combined_messages = current_messages

    patient_id = session_data.patient_id or state.get("patient_id")
    is_authenticated = session_data.is_authenticated or state.get("is_authenticated", False)

    update: dict[str, Any] = {
        "messages": combined_messages,
        "patient_id": patient_id,
        "is_authenticated": is_authenticated,
    }

    if patient_id:
        context = await _load_patient_long_term_context(patient_id)
        if context is not None:
            existing_entities = dict(state.get("entities", {}))

            if context.get("preferred_doctor") and not existing_entities.get("doctor_id"):
                existing_entities["doctor_id"] = context["preferred_doctor"]

            if context.get("preferred_time_slot") and not existing_entities.get("time"):
                existing_entities["time"] = context["preferred_time_slot"]

            update["entities"] = existing_entities

            logger.debug(
                f"load_session_memory_node: loaded long-term context for patient={patient_id} "
                f"preferred_doctor={context.get('preferred_doctor')} "
                f"preferred_time_slot={context.get('preferred_time_slot')}"
            )

    logger.info(
        f"load_session_memory_node: loaded {len(prior_messages)} prior message(s) "
        f"for session={session_id} patient={patient_id or 'anonymous'}"
    )

    return update


async def save_memory_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    Persist this turn's messages to Tier 2 (Redis) and Tier 3 (MySQL)
    at the end of each graph traversal.
    
    Returns
    -------
    An empty partial state update dict — save_memory_node is purely a
    side-effect node and does not change the graph state.
    """
    session_id = state["session_id"]
    patient_id = state.get("patient_id")
    is_authenticated = state.get("is_authenticated", False)
    active_agent = state.get("active_agent")
    messages = state.get("messages", [])

    try:
        from app.api.dependencies import get_redis_pool
        redis = await get_redis_pool()
    except Exception as exc:
        logger.error(f"save_memory_node: Redis unavailable for session={session_id}: {exc}")
        return {}

    last_human: Optional[BaseMessage] = None
    last_ai: Optional[BaseMessage] = None

    for message in reversed(messages):
        if last_ai is None and isinstance(message, AIMessage) and message.content:
            last_ai = message
        elif last_human is None and isinstance(message, HumanMessage):
            last_human = message
        if last_human is not None and last_ai is not None:
            break

    new_messages = [m for m in [last_human, last_ai] if m is not None]

    if new_messages:
        history = RedisMessageHistory(session_id=session_id, redis_client=redis)
        await history.aadd_messages(new_messages)

        await _archive_messages_to_mysql(
            session_id=session_id,
            patient_id=patient_id,
            messages=new_messages,
            active_agent=active_agent,
        )

        logger.info(
            f"save_memory_node: persisted {len(new_messages)} new message(s) "
            f"for session={session_id} patient={patient_id or 'anonymous'}"
        )
    else:
        logger.debug(f"save_memory_node: no new messages to persist for session={session_id}")

    if patient_id:
        last_concern = _infer_last_concern(state)
        await _upsert_patient_long_term_context(
            patient_id=patient_id,
            last_concern=last_concern,
            entities=state.get("entities", {}),
        )

    await touch_session(
        redis=redis,
        session_id=session_id,
        patient_id=patient_id,
        is_authenticated=is_authenticated,
    )

    return {}