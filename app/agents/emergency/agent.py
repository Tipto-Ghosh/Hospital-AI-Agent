from __future__ import annotations
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from sqlalchemy import select
from app.logger import logging as logger
from app.agents.emergency.prompts import (
    FALLBACK_EMERGENCY_CONTACTS,
    build_emergency_prompt,
    get_first_aid_guidance_for_text,
)
from app.agents.state import HospitalAgentState
from app.config import get_settings
from app.db.base import get_session_context
from app.db.models.medication import HospitalInfo
from app.db.repositories.audit_repo import AuditRepository
from app.llm.factory import LLMTier, get_llm



async def get_emergency_contacts() -> str:
    """
    Fetch emergency contact information from hospital_info.

    Looks up the row with category='contact' and topic containing
    'Emergency' (seeded as topic='Emergency Contacts' in
    data/seed/hospital_info.sql).

    Returns
    -------
    The content string from hospital_info, or FALLBACK_EMERGENCY_CONTACTS
    if the table is empty, the row is missing, or the database is
    unreachable.

    This function NEVER raises - emergency contact numbers must always
    be returned, even if the database is down.
    """
    try:
        async with get_session_context() as session:
            result = await session.execute(
                select(HospitalInfo).where(
                    HospitalInfo.category == "contact",
                    HospitalInfo.topic.ilike("%emergency%"),
                )
            )
            row = result.scalars().first()
            if row is not None and row.content:
                return row.content
    except Exception as exc:
        logger.error(f"get_emergency_contacts: database lookup failed, using fallback ({exc})")

    return FALLBACK_EMERGENCY_CONTACTS


async def log_emergency_interaction(
    session_id: str,
    patient_id: str | None,
    message_text: str,
    is_authenticated: bool,
) -> None:
    """
    Write a mandatory audit log entry for this emergency interaction.

    Called for EVERY emergency, regardless of authentication status -
    per Section 3.8 of the plan: "Logs every interaction regardless of
    authentication status."

    Parameters
    session_id: Current session ID.
    patient_id: Patient PK if known, else None.
    message_text: The patient's message that triggered emergency routing.
    is_authenticated: Whether the session was authenticated at the time of this emergency.

    This function logs errors but does NOT raise - a logging failure
    must never prevent the emergency response from being delivered to
    the patient.
    """
    preview_len = 60
    preview = message_text[:preview_len]
    if len(message_text) > preview_len:
        preview = f"{preview}..."

    try:
        async with get_session_context() as session:
            audit_repo = AuditRepository(session)
            await audit_repo.log(
                agent_name="emergency_agent",
                action="emergency_interaction",
                session_id=session_id,
                patient_id=patient_id,
                resource_type="conversation",
                resource_id=session_id,
                payload_summary=(
                    f"Emergency routing triggered (authenticated={is_authenticated}). "
                    f"Message preview: {preview!r}"
                ),
            )
    except Exception as exc:
        logger.error(
            f"log_emergency_interaction failed for session={session_id} "
            f"patient={patient_id}: {exc}"
        )


def _latest_human_text(messages: list[BaseMessage]) -> str:
    """Return the content of the most recent HumanMessage, or ''."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


async def emergency_agent_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Emergency Triage graph node.

    Flow:
    1. Fetch emergency contacts immediately (DB lookup with hardcoded fallback, no LLM gating).
    2. Look up curated first-aid guidance matching the patient's message.
    3. Call the LLM with the emergency prompt to produce a calm,
       compassionate response. On any LLM failure, fall back to a
       hardcoded safe response containing the contact numbers.
    4. Append the response as an AIMessage to state["messages"].
    5. Log the interaction to the audit trail - mandatory, regardless
       of authentication status.
    6. Set next_action="end" - no further routing after an emergency
       response.
    """
    session_id = state["session_id"]
    patient_id = state.get("patient_id")
    is_authenticated = state.get("is_authenticated", False)

    latest_text = _latest_human_text(state["messages"])

    logger.warning(
        f"Emergency agent activated for session={session_id} "
        f"patient={patient_id or 'anonymous'}"
    )

    # Step 1: emergency contacts - never gated on the LLM.
    emergency_contacts = await get_emergency_contacts()

    # Step 2: curated first-aid guidance for this situation.
    first_aid_guidance = get_first_aid_guidance_for_text(latest_text)

    # Step 3: LLM response, with a hardcoded fallback on failure.
    settings = get_settings()
    system_prompt = build_emergency_prompt(
        hospital_name=settings.HOSPITAL_NAME,
        emergency_contacts=emergency_contacts,
        first_aid_guidance=first_aid_guidance,
    )

    response_text: str
    try:
        llm = get_llm(LLMTier.FAST)
        llm_messages: list[BaseMessage] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=latest_text),
        ]
        response = await llm.ainvoke(llm_messages)
        response_text = (
            response.content if isinstance(response.content, str) else str(response.content)
        )
        if not response_text.strip():
            raise ValueError("Empty response from LLM")
    except Exception as exc:
        logger.error(
            f"Emergency LLM call failed for session={session_id}, "
            f"using hardcoded fallback response ({exc})"
        )
        response_text = (
            f"This may be a medical emergency. Please call now: "
            f"{emergency_contacts.splitlines()[0]} "
            "or go to the Emergency entrance (Ground Floor, Block A) "
            "immediately. Stay on the line with emergency services and "
            "follow their instructions."
        )

    # Step 4: append the response to the conversation.
    new_message = AIMessage(content=response_text)

    # Step 5: mandatory audit log, regardless of auth status.
    await log_emergency_interaction(
        session_id=session_id,
        patient_id=patient_id,
        message_text=latest_text,
        is_authenticated=is_authenticated,
    )

    logger.info(f"Emergency response delivered for session={session_id}")

    return {
        "messages": [new_message],
        "active_agent": "emergency_agent",
        "next_action": "end",
    }