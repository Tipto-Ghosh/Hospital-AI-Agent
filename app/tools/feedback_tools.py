from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel
from sqlalchemy import select

from app.db.base import get_session_context
from app.db.models.feedback import ComplaintTicket, Feedback
from app.logger import logging

logger = logging.getLogger(__name__)

# Mirrors app.agents.feedback.prompts - kept as local constants so
# this tools module has no dependency on the agents package.
ESCALATION_KEYWORDS: list[str] = ["unsafe", "negligent"]
ESCALATION_RATING_THRESHOLD = 2


class LogFeedbackResult(BaseModel):
    """Result of recording a feedback submission."""
    feedback_id: int
    escalated: bool
    ticket_id: Optional[str] = None


class ComplaintTicketResult(BaseModel):
    """Result of creating a complaint ticket."""
    ticket_id: str
    priority: str
    escalated: bool

class EscalationResult(BaseModel):
    """Result of escalating a ticket to a manager."""
    escalated: bool
    ticket_id: str
    error: Optional[str] = None


def _contains_escalation_keyword(text: str) -> bool:
    """Case-insensitive substring check against ESCALATION_KEYWORDS."""
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in lowered for keyword in ESCALATION_KEYWORDS)


async def _generate_ticket_id(session) -> str:
    """Generate the next sequential complaint ticket ID for today (TKT-YYYYMMDD-NNNN)."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"TKT-{today}-"

    result = await session.execute(
        select(ComplaintTicket.ticket_id)
        .where(ComplaintTicket.ticket_id.like(f"{prefix}%"))
        .order_by(ComplaintTicket.ticket_id.desc())
        .limit(1)
    )
    last_id: str | None = result.scalar_one_or_none()
    seq = int(last_id.split("-")[-1]) + 1 if last_id else 1
    return f"{prefix}{seq:04d}"


@tool
async def log_feedback(
    category: str,
    message: str,
    rating: Optional[int] = None,
    patient_id: Optional[str] = None,
) -> LogFeedbackResult:
    """
    Record patient feedback. Anonymous feedback is allowed - pass
    patient_id=None.

    Automatically escalates (creates a high-priority complaint ticket
    and calls escalate_to_manager) if rating <= 2, or if "unsafe" or
    "negligent" appears in the message.

    Parameters
    ----------
    category     One of: general, doctor, billing, facilities, staff,
                 ai_agent.
    message      Free-text feedback from the patient.
    rating       Optional 1-5 star rating.
    patient_id   The patient's PK if authenticated, else None for
                 anonymous feedback.

    Returns
    -------
    LogFeedbackResult. ticket_id is set only if escalated=true.
    """
    should_escalate = (
        (rating is not None and rating <= ESCALATION_RATING_THRESHOLD)
        or _contains_escalation_keyword(message)
    )

    ticket_id: Optional[str] = None

    async with get_session_context() as session:
        feedback = Feedback(patient_id=patient_id, category=category, message=message, rating=rating)
        session.add(feedback)
        await session.flush()

        if should_escalate:
            ticket_id = await _generate_ticket_id(session)
            ticket = ComplaintTicket(
                ticket_id=ticket_id,
                patient_id=patient_id,
                department=category,
                description=f"Auto-escalated from feedback #{feedback.feedback_id}: {message}",
                status="escalated",
                priority="high",
            )
            session.add(ticket)
            await session.flush()

        await session.commit()
        feedback_id = feedback.feedback_id

    if should_escalate and ticket_id:
        await escalate_to_manager.ainvoke({
            "ticket_id": ticket_id,
            "reason": f"Auto-escalated (rating={rating}, keyword_match={_contains_escalation_keyword(message)})",
        })

    logger.info(
        f"log_feedback(category={category!r}, rating={rating}, patient={patient_id or 'anonymous'}) "
        f"-> feedback_id={feedback_id} escalated={should_escalate}"
    )
    return LogFeedbackResult(feedback_id=feedback_id, escalated=should_escalate, ticket_id=ticket_id)


@tool
async def create_complaint_ticket(
    department: str,
    description: str,
    priority: str = "medium",
    patient_id: Optional[str] = None,
) -> ComplaintTicketResult:
    """
    Create a complaint ticket. Anonymous complaints are allowed - pass
    patient_id=None.

    Automatically raises the priority to "high" (or "critical" if it
    would otherwise be "high") if "unsafe" or "negligent" appears in
    the description, and calls escalate_to_manager.

    Parameters
    ----------
    department    The department the complaint concerns, e.g.
                  "Cardiology" or "Billing".
    description   Free-text description of the complaint.
    priority      One of: low, medium, high, critical. Default "medium".
    patient_id    The patient's PK if authenticated, else None.

    Returns
    -------
    ComplaintTicketResult.
    """
    escalation_triggered = _contains_escalation_keyword(description)
    final_priority = priority

    if escalation_triggered:
        final_priority = "critical" if priority == "high" else "high"

    async with get_session_context() as session:
        ticket_id = await _generate_ticket_id(session)
        ticket = ComplaintTicket(
            ticket_id=ticket_id,
            patient_id=patient_id,
            department=department,
            description=description,
            status="escalated" if escalation_triggered else "open",
            priority=final_priority,
        )
        session.add(ticket)
        await session.commit()

    if escalation_triggered:
        await escalate_to_manager.ainvoke({
            "ticket_id": ticket_id,
            "reason": "Auto-escalated (keyword match: 'unsafe' or 'negligent' in description)",
        })

    logger.info(
        f"create_complaint_ticket(department={department!r}, priority={final_priority!r}, "
        f"patient={patient_id or 'anonymous'}) -> ticket_id={ticket_id} escalated={escalation_triggered}"
    )
    return ComplaintTicketResult(ticket_id=ticket_id, priority=final_priority, escalated=escalation_triggered)


@tool
async def escalate_to_manager(ticket_id: str, reason: str) -> EscalationResult:
    """
    Flag a complaint ticket for priority manager review.

    Sets the ticket's status to "escalated" and records the escalation
    reason in resolution_note as a prefix. Actual manager notification
    (email/Slack) is implemented via Celery in Phase 7; this logs the
    escalation so the flow can be exercised end-to-end before Celery is
    wired up.

    Parameters
    ----------
    ticket_id   The ticket PK to escalate.
    reason      Why this ticket is being escalated.

    Returns
    -------
    EscalationResult(escalated=True) on success, or
    EscalationResult(escalated=False, error=...) if the ticket doesn't
    exist.
    """
    async with get_session_context() as session:
        result = await session.execute(select(ComplaintTicket).where(ComplaintTicket.ticket_id == ticket_id))
        ticket = result.scalar_one_or_none()

        if ticket is None:
            logger.warning(f"escalate_to_manager(ticket_id={ticket_id!r}) -> ticket not found")
            return EscalationResult(escalated=False, ticket_id=ticket_id, error="Ticket not found.")

        ticket.status = "escalated"
        note_prefix = f"[ESCALATED: {reason}]"
        ticket.resolution_note = f"{note_prefix} {ticket.resolution_note}" if ticket.resolution_note else note_prefix
        await session.commit()

    logger.warning(f"escalate_to_manager(ticket_id={ticket_id!r}, reason={reason!r}) -> escalated (stub notification)")
    return EscalationResult(escalated=True, ticket_id=ticket_id)


feedback_tools = [log_feedback, create_complaint_ticket, escalate_to_manager]