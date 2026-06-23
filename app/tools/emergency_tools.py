from __future__ import annotations
from typing import Optional
from langchain_core.tools import tool
from pydantic import BaseModel
from sqlalchemy import select

from app.db.base import get_session_context
from app.db.models.medication import HospitalInfo
from app.db.repositories.audit_repo import AuditRepository
from app.logger import logging

logger = logging.getLogger(__name__)


# Mirrors app.agents.emergency.prompts.FALLBACK_EMERGENCY_CONTACTS -
# kept as a local constant so this tools module has no dependency on
# the agents package (tools/ should not import from agents/).
FALLBACK_EMERGENCY_CONTACTS = (
    "Hospital Emergency Hotline (24/7): 109\n"
    "Ambulance Dispatch: 01711-AMBU (01711-2628)\n"
    "National Emergency: 999"
)

class EmergencyContactsResult(BaseModel):
    """Emergency contact information."""
    contacts: str
    source: str  # "database" or "fallback"

class EmergencyLogResult(BaseModel):
    """Result of logging an emergency interaction to the audit trail."""
    logged: bool


@tool
async def get_emergency_contacts() -> EmergencyContactsResult:
    """
    Get the hospital's emergency contact numbers.

    Reads from hospital_info (category='contact', topic containing
    'Emergency'). This tool NEVER fails - if the database is
    unreachable or no matching row exists, a hardcoded fallback contact
    list is returned instead.

    Returns
    -------
    EmergencyContactsResult with the contacts text and a source field
    indicating whether it came from the database or the fallback.
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
                logger.info("get_emergency_contacts -> found in database")
                return EmergencyContactsResult(contacts=row.content, source="database")
    except Exception as exc:
        logger.error(f"get_emergency_contacts: database lookup failed, using fallback ({exc})")

    return EmergencyContactsResult(contacts=FALLBACK_EMERGENCY_CONTACTS, source="fallback")


@tool
async def log_emergency_interaction(
    session_id: str,
    message_preview: str,
    patient_id: Optional[str] = None,
    is_authenticated: bool = False,
) -> EmergencyLogResult:
    """
    Write a mandatory audit log entry for an emergency interaction.

    Must be called for EVERY emergency, regardless of authentication
    status. This tool NEVER raises - a logging failure must never
    prevent the emergency response from being delivered to the patient.

    Parameters
    ----------
    session_id: Current session ID.
    message_preview: A short (already-truncated, non-PHI) preview
                    of the patient's message that triggered
                    emergency routing.
    patient_id: Patient PK if known, else None.
    is_authenticated :Whether the session was authenticated at the time of this emergency.

    Returns
    -------
    EmergencyLogResult(logged=True) on success, or
    EmergencyLogResult(logged=False) if the write failed (the failure
    itself is logged via the application logger, not raised).
    """
    try:
        async with get_session_context() as session:
            audit_repo = AuditRepository(session)
            await audit_repo.log(
                agent_name="emergency_tools",
                action="emergency_interaction",
                session_id=session_id,
                patient_id=patient_id,
                resource_type="conversation",
                resource_id=session_id,
                payload_summary=(
                    f"Emergency routing triggered (authenticated={is_authenticated}). "
                    f"Message preview: {message_preview!r}"
                ),
            )
        logger.info(f"log_emergency_interaction: logged for session={session_id}")
        return EmergencyLogResult(logged=True)
    except Exception as exc:
        logger.error(f"log_emergency_interaction failed for session={session_id}: {exc}")
        return EmergencyLogResult(logged=False)


emergency_tools = [get_emergency_contacts, log_emergency_interaction]