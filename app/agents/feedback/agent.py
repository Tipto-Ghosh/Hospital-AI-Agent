"""
The Feedback and complaints agent node and its tools.

Auto-escalation:
log_feedback() and create_complaint_ticket() both check the submitted
content against ESCALATION_KEYWORDS ("unsafe", "negligent" -
case-insensitive substring match) from prompt file and for feedback, the rating
against ESCALATION_RATING_THRESHOLD (<= 2). If either condition is met:
 
  - log_feedback(): a ComplaintTicket is automatically created from the
    feedback (priority="high"), in addition to the Feedback row.
  - create_complaint_ticket(): the ticket's priority is set to "high"
    (or "critical" if it would otherwise be "high") instead of the
    requested priority.
 
In both cases escalate_to_manager() is then called on the resulting
ticket.
 
Anonymity
----------
patient_id is taken from state["patient_id"] if the session is
authenticated, and is None otherwise. None is a valid value for
Feedback.patient_id and ComplaintTicket.patient_id (both nullable) -
anonymous submissions are fully supported.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any, Optional
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from sqlalchemy import select

from app.agents.feedback.prompts import ESCALATION_KEYWORDS, ESCALATION_RATING_THRESHOLD, build_feedback_prompt
from app.agents.state import HospitalAgentState
from app.config import get_settings
from app.db.base import get_session_context
from app.db.models.feedback import Feedback, ComplaintTicket
from app.llm.factory import LLMTier, get_llm
from app.logger import logging
from contextvars import ContextVar

logger = logging.getLogger(__name__)


# Holds (session_id, patient_id) for the duration of
# feedback_agent_node's tool calls. patient_id may be None
# (anonymous). Mirrors the pattern from records_agent / billing_agent.
_current_feedback_context: ContextVar[tuple[str, Optional[str]] | None] = ContextVar("_current_feedback_context", default = None)


def _contains_escalation_keyword(text: str) -> bool:
    """Case-insensitive substring check against ESCALATION_KEYWORDS."""
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in lowered for keyword in ESCALATION_KEYWORDS)

async def _generate_ticket_id(session) -> str:
    """
    Generate the next sequential complaint ticket ID for today.
 
    Format: TKT-YYYYMMDD-NNNN (e.g. TKT-20241101-0001).
    """
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
async def log_feedback(category: str, message: str, rating: Optional[int] = None) -> str:
    """
    Record patient feedback.
 
    Automatically escalates (creates a high-priority complaint ticket
    and calls escalate_to_manager) if rating <= 2, or if "unsafe" or
    "negligent" appears in the message.
 
    Parameters
    ----------
    category   One of: general, doctor, billing, facilities, staff,
               ai_agent.
    message    Free-text feedback from the patient.
    rating     Optional 1-5 star rating.
 
    Returns
    -------
    A JSON string: {"feedback_id": int, "escalated": bool,
    "ticket_id": str|null}. ticket_id is set only if escalated=true.
    """
    ctx = _current_feedback_context.get()
    session_id, patient_id = ctx if ctx else (None, None)
 
    should_escalate = (
        (rating is not None and rating <= ESCALATION_RATING_THRESHOLD)
        or _contains_escalation_keyword(message)
    )
 
    ticket_id: Optional[str] = None
 
    async with get_session_context() as session:
        feedback = Feedback(
            patient_id=patient_id,
            category=category,
            message=message,
            rating=rating,
        )
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
    return json.dumps({"feedback_id": feedback_id, "escalated": should_escalate, "ticket_id": ticket_id})
 
 
@tool
async def create_complaint_ticket(department: str, description: str, priority: str = "medium") -> str:
    """
    Create a complaint ticket.
 
    Automatically raises the priority to "high" (or "critical" if it
    would otherwise be "high") if "unsafe" or "negligent" appears in
    the description, and calls escalate_to_manager.
 
    Parameters
    ----------
    department    The department the complaint concerns, e.g.
                  "Cardiology" or "Billing".
    description   Free-text description of the complaint.
    priority      One of: low, medium, high, critical. Default
                  "medium".
 
    Returns
    -------
    A JSON string: {"ticket_id": str, "priority": str, "escalated": bool}.
    """
    ctx = _current_feedback_context.get()
    session_id, patient_id = ctx if ctx else (None, None)
 
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
    return json.dumps({"ticket_id": ticket_id, "priority": final_priority, "escalated": escalation_triggered})
 
 
@tool
async def check_ticket_status(ticket_id: str) -> str:
    """
    Check the status of an existing complaint ticket.
 
    Parameters
    ----------
    ticket_id   The ticket PK, e.g. "TKT-20241101-0001".
 
    Returns
    -------
    A JSON string: {"found": true, "ticket_id": str, "status": str,
    "priority": str, "department": str|null,
    "resolution_note": str|null} if found, else {"found": false}.
    """
    async with get_session_context() as session:
        result = await session.execute(
            select(ComplaintTicket).where(ComplaintTicket.ticket_id == ticket_id)
        )
        ticket = result.scalar_one_or_none()
 
    if ticket is None:
        logger.info(f"check_ticket_status(ticket_id={ticket_id!r}) -> not found")
        return json.dumps({"found": False})
 
    logger.info(f"check_ticket_status(ticket_id={ticket_id!r}) -> status={ticket.status}")
    return json.dumps({
        "found": True,
        "ticket_id": ticket.ticket_id,
        "status": ticket.status,
        "priority": ticket.priority,
        "department": ticket.department,
        "resolution_note": ticket.resolution_note,
    })
 
 
@tool
async def escalate_to_manager(ticket_id: str, reason: str) -> str:
    """
    Flag a complaint ticket for priority manager review.
 
    Sets the ticket's status to "escalated" (if not already) and
    records the escalation reason in resolution_note as a prefix -
    actual manager notification (email/Slack) is implemented via
    Celery in Phase 7. This logs the escalation so the flow can be
    exercised end-to-end before Celery is wired up.
 
    Parameters
    ----------
    ticket_id   The ticket PK to escalate.
    reason      Why this ticket is being escalated.
 
    Returns
    -------
    A JSON string: {"escalated": true, "ticket_id": str} on success,
    or {"escalated": false, "error": str} if the ticket doesn't exist.
    """
    async with get_session_context() as session:
        result = await session.execute(
            select(ComplaintTicket).where(ComplaintTicket.ticket_id == ticket_id)
        )
        ticket = result.scalar_one_or_none()
 
        if ticket is None:
            logger.warning(f"escalate_to_manager(ticket_id={ticket_id!r}) -> ticket not found")
            return json.dumps({"escalated": False, "error": "Ticket not found."})
 
        ticket.status = "escalated"
        note_prefix = f"[ESCALATED: {reason}]"
        ticket.resolution_note = (
            f"{note_prefix} {ticket.resolution_note}" if ticket.resolution_note else note_prefix
        )
        await session.commit()
 
    logger.warning(f"escalate_to_manager(ticket_id={ticket_id!r}, reason={reason!r}) -> escalated (stub notification)")
    return json.dumps({"escalated": True, "ticket_id": ticket_id})
 
 
feedback_tools = [log_feedback, create_complaint_ticket, check_ticket_status, escalate_to_manager]
feedback_tool_node = ToolNode(feedback_tools)
 
 
async def feedback_agent_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Feedback & Complaints Agent graph node.
 
    Flow
    ----
    1. Set the feedback context ContextVar with
       (session_id, patient_id) - patient_id is state["patient_id"] if
       authenticated, else None. Anonymous feedback is fully supported.
    2. Call the CAPABLE-tier LLM with all four tools bound, passing the
       feedback system prompt plus conversation history.
    3. If the response contains tool calls, append it and set
       next_action="feedback_tools" so feedback_tool_node executes them
       - the graph routes back to this node for a final answer.
    4. Otherwise the response is final - append it and set
       next_action="end".
 
    The ContextVar is always reset in a finally block, even on error.
 
    Returns
    -------
    A partial state update dict.
    """
    session_id = state["session_id"]
    patient_id = state.get("patient_id") if state.get("is_authenticated", False) else None
 
    token = _current_feedback_context.set((session_id, patient_id))
 
    try:
        settings = get_settings()
        system_prompt = build_feedback_prompt(settings.HOSPITAL_NAME)
 
        llm = get_llm(LLMTier.CAPABLE).bind_tools(feedback_tools)
        llm_messages: list[BaseMessage] = [SystemMessage(content=system_prompt), *state["messages"]]
 
        try:
            response: AIMessage = await llm.ainvoke(llm_messages)
        except Exception as exc:
            logger.error(f"feedback_agent LLM call failed for session={session_id}: {exc}")
            return {
                "messages": [AIMessage(content="I'm having trouble recording that right now. Please try again shortly, or visit the Patient Relations Helpdesk (Ground Floor, Block A).")],
                "active_agent": "feedback_agent",
                "next_action": "end",
                "error": "Feedback agent LLM call failed.",
            }
 
        has_tool_calls = bool(getattr(response, "tool_calls", None))
        next_action = "feedback_tools" if has_tool_calls else "end"
 
        logger.info(
            f"feedback_agent responded for session={session_id} patient={patient_id or 'anonymous'} "
            f"(tool_calls={len(response.tool_calls) if has_tool_calls else 0})"
        )
 
        return {
            "messages": [response],
            "active_agent": "feedback_agent",
            "next_action": next_action,
        }
    finally:
        _current_feedback_context.reset(token)
 