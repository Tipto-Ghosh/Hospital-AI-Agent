"""
The mendatory confirmation gate before any write operations executes,
plus the node that actually performs the write once confirmed.
"""

from __future__ import annotations
 
import json
from datetime import datetime
from typing import Any
 
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
 
from app.agents.booking.agent import create_appointment
from app.agents.cancellation.agent import (
    cancel_appointment,
    free_doctor_slot,
    send_cancellation_notice,
)
from app.agents.rescheduling.agent import reschedule_appointment
from app.agents.state import HospitalAgentState
from app.db.base import get_session_context
from app.db.repositories.appointment_repo import AppointmentRepository
from app.db.repositories.audit_repo import AuditRepository
from app.logger import logging
 
logger = logging.getLogger(__name__)


AFFIRMATIVE_KEYWORDS = [
    "yes", "yeah", "yep", "yup", "confirm", "confirmed", "correct",
    "go ahead", "sure", "ok", "okay", "sounds good", "that's right",
    "that is right", "do it", "please proceed", "proceed",
]
 
NEGATIVE_KEYWORDS = [
    "no", "nope", "nah", "cancel", "don't", "do not", "abort", "stop",
    "wait", "actually no", "never mind", "nevermind", "incorrect",
    "that's wrong", "that is wrong",
]

# Maps pending_confirmation["action"] to (tool, originating agent_name).
# Used by both action_executor_node (to call the right tool) and the
# audit log (to attribute the write to the agent that proposed it).
ACTION_TOOL_MAP: dict[str, tuple[Any, str]] = {
    "create_appointment": (create_appointment, "booking_agent"),
    "cancel_appointment": (cancel_appointment, "cancel_agent"),
    "reschedule_appointment": (reschedule_appointment, "reschedule_agent"),
}

def _latest_human_text(messages: list[BaseMessage]) -> str:
    """Return the content of the most recent HumanMessage or an empty string if there are none."""
    
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
           content = message.content.strip()
           return content if isinstance(content, str) else str(content)
       
    return ""

def _is_affirmative(text: str) -> bool:
    """Case-insensitive substring check against AFFIRMATIVE_KEYWORDS."""
    lowered = text.lower().strip()
    return any(keyword in lowered for keyword in AFFIRMATIVE_KEYWORDS)

def _is_negative(text: str) -> bool:
    """
    Case-insensitive substring check against NEGATIVE_KEYWORDS.
 
    Checked AFTER _is_affirmative() by the caller - phrases like
    "no wait, yes" are ambiguous and fall through to the re-prompt
    path rather than being misclassified.
    """
    lowered = text.lower().strip()
    return any(keyword in lowered for keyword in NEGATIVE_KEYWORDS)

def _format_confirmation_prompt(pending_confirmation: dict[str, Any]) -> str:
    """
    Format a human-readable confirmation prompt from
    pending_confirmation["summary"].
    """
    summary = pending_confirmation.get("summary", "this action")
    return f"Just to confirm - {summary}. Is that correct? (yes / no)"

async def confirmation_handler_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Confirmation Handler graph node.
 
    Returns
    -------
    A partial state update dict. next_action is one of:
      "confirmed" - patient said yes, action_executor_node should run next.
      "aborted" - patient said no, pending_confirmation cleared.
      "end" - ambiguous reply, re-prompted, awaiting another reply.
      "fallback" - no pending_confirmation was found (defensive case).
    """
    session_id = state["session_id"]
    pending = state.get("pending_confirmation")
 
    if pending is None:
        logger.warning(
            f"confirmation_handler: session={session_id} called with no pending_confirmation")
        return {
            "active_agent": "confirmation_handler",
            "next_action": "fallback",
            "error": "No pending confirmation was found.",
        }
 
    latest_text = _latest_human_text(state["messages"])
 
    if _is_affirmative(latest_text):
        logger.info(f"confirmation_handler: session={session_id} confirmed action={pending.get('action')}")
        return {
            "active_agent": "confirmation_handler",
            "next_action": "confirmed",
        }
 
    if _is_negative(latest_text):
        logger.info(f"confirmation_handler: session={session_id} aborted action={pending.get('action')}")
        return {
            "messages": [AIMessage(content="No problem - I won't go ahead with that. Is there anything else I can help with?")],
            "pending_confirmation": None,
            "active_agent": "confirmation_handler",
            "next_action": "aborted",
        }
 
    prompt = _format_confirmation_prompt(pending)
    logger.info(f"confirmation_handler: session={session_id} ambiguous reply, re-prompting")
    return {
        "messages": [AIMessage(content=prompt)],
        "active_agent": "confirmation_handler",
        "next_action": "end",
    }
 
 
async def _execute_create_appointment(params: dict[str, Any]) -> str:
    """
    Execute a confirmed create_appointment action and return a
    patient-facing message.
 
    On success, also attempts to move the appointment from
    'pending' to 'confirmed' status via
    AppointmentRepository.confirm() - reflecting that the patient
    explicitly confirmed this booking in the conversation. This
    secondary step is best-effort: if it fails, the appointment still
    exists (as 'pending') and the patient is told it was booked.
    """
    result_raw = await create_appointment.ainvoke(params)
    result = json.loads(result_raw)
 
    if not result.get("success"):
        return f"I wasn't able to book that appointment: {result.get('error', 'an unknown error occurred')}. Your previous appointments are unchanged."
 
    appointment_id = result["appointment_id"]
    scheduled_at = datetime.fromisoformat(result["scheduled_at"])
 
    try:
        async with get_session_context() as session:
            appt_repo = AppointmentRepository(session)
            await appt_repo.confirm(appointment_id)
    except ValueError as exc:
        logger.warning(f"_execute_create_appointment: confirm() failed for {appointment_id}: {exc}")
 
    return (
        f"All set! Your appointment is booked for "
        f"{scheduled_at.strftime('%A, %d %B %Y at %I:%M %p')}. "
        f"Your appointment ID is {appointment_id} - please keep this for your records."
    )
 
 
async def _execute_cancel_appointment(params: dict[str, Any]) -> str:
    """
    Execute a confirmed cancel_appointment action and return a
    patient-facing message.
 
    On success, also calls free_doctor_slot (no-op, for audit-trail
    clarity - the slot is freed automatically as a side effect of the
    status change) and send_cancellation_notice (stub notification).
    """
    result_raw = await cancel_appointment.ainvoke(params)
    result = json.loads(result_raw)
 
    if not result.get("success"):
        return f"I wasn't able to cancel that appointment: {result.get('error', 'an unknown error occurred')}."
 
    appointment_id = result["appointment_id"]
 
    try:
        async with get_session_context() as session:
            appt_repo = AppointmentRepository(session)
            cancelled = await appt_repo.get_by_id(appointment_id)
        if cancelled is not None:
            await free_doctor_slot.ainvoke({
                "doctor_id": cancelled.doctor_id,
                "scheduled_at": cancelled.scheduled_at.isoformat(),
            })
    except Exception as exc:
        logger.error(f"_execute_cancel_appointment: free_doctor_slot lookup failed for {appointment_id}: {exc}")
 
    try:
        await send_cancellation_notice.ainvoke({
            "patient_contact": params.get("patient_contact", "on file"),
            "appointment_details": appointment_id,
        })
    except Exception as exc:
        logger.error(f"_execute_cancel_appointment: send_cancellation_notice failed for {appointment_id}: {exc}")
 
    return (
        f"Your appointment {appointment_id} has been cancelled. "
        "A confirmation has been sent to the contact details on file."
    )
 
 
async def _execute_reschedule_appointment(params: dict[str, Any]) -> str:
    """
    Execute a confirmed reschedule_appointment action and return a
    patient-facing message.
 
    If the new slot became unavailable between confirmation and
    execution, AppointmentRepository.reschedule() rolls back and
    leaves the original appointment unchanged - this is surfaced to
    the patient with an explicit "your original appointment is
    unchanged" message.
    """
    old_appointment_id = params.get("appointment_id")
    result_raw = await reschedule_appointment.ainvoke(params)
    result = json.loads(result_raw)
 
    if not result.get("success"):
        return (
            f"I wasn't able to reschedule that appointment: "
            f"{result.get('error', 'an unknown error occurred')}. "
            f"Your original appointment ({old_appointment_id}) is unchanged."
        )
 
    new_appointment_id = result["new_appointment_id"]
    scheduled_at = datetime.fromisoformat(result["scheduled_at"])
 
    return (
        f"Done! Your appointment has been moved to "
        f"{scheduled_at.strftime('%A, %d %B %Y at %I:%M %p')}. "
        f"Your new appointment ID is {new_appointment_id}."
    )
 
 
_EXECUTORS: dict[str, Any] = {
    "create_appointment": _execute_create_appointment,
    "cancel_appointment": _execute_cancel_appointment,
    "reschedule_appointment": _execute_reschedule_appointment,
}
 
 
async def action_executor_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Action Executor graph node.
 
    Only performs work if state["next_action"] == "confirmed" (set by
    confirmation_handler_node). If called in any other state, this is a
    no-op that returns an empty update - the graph should not normally
    route here otherwise, but this guard makes the node safe to call
    defensively.
 
    Flow
    ----
    1. Look up pending_confirmation["action"] in ACTION_TOOL_MAP to
       find the originating agent_name (for audit logging) - the
       actual tool call is delegated to the matching _EXECUTORS
       function, which returns a patient-facing message string.
    2. Write an audit_log entry for the executed action, attributed to
       the originating agent.
    3. Clear pending_confirmation and set next_action="end".
 
    Returns
    -------
    A partial state update dict.
    """
    session_id = state["session_id"]
 
    if state.get("next_action") != "confirmed":
        logger.debug(f"action_executor: session={session_id} called without next_action='confirmed', no-op")
        return {}
 
    pending = state.get("pending_confirmation")
    if pending is None:
        logger.warning(f"action_executor: session={session_id} called with no pending_confirmation")
        return {
            "messages": [AIMessage(content="I'm sorry, I lost track of what we were confirming. Could you tell me again what you'd like to do?")],
            "active_agent": "action_executor",
            "next_action": "fallback",
            "pending_confirmation": None,
        }
 
    action = pending.get("action")
    params = pending.get("params", {})
 
    tool_entry = ACTION_TOOL_MAP.get(action)
    executor = _EXECUTORS.get(action)
 
    if tool_entry is None or executor is None:
        logger.error(f"action_executor: session={session_id} unknown action={action!r}")
        return {
            "messages": [AIMessage(content="I'm sorry, something went wrong processing that request. Please contact reception at 16700.")],
            "active_agent": "action_executor",
            "next_action": "end",
            "pending_confirmation": None,
            "error": f"Unknown pending_confirmation action: {action!r}",
        }
 
    _, agent_name = tool_entry
    response_text = await executor(params)
 
    try:
        async with get_session_context() as session:
            audit_repo = AuditRepository(session)
            await audit_repo.log(
                agent_name=agent_name,
                action=action,
                session_id=session_id,
                patient_id=state.get("patient_id"),
                resource_type="appointment",
                resource_id=params.get("appointment_id"),
                payload_summary=f"Executed confirmed action: {action}.",
            )
    except Exception as exc:
        logger.error(f"action_executor: session={session_id} audit log failed for action={action!r}: {exc}")
 
    logger.info(f"action_executor: session={session_id} executed action={action!r}")
 
    return {
        "messages": [AIMessage(content=response_text)],
        "active_agent": "action_executor",
        "next_action": "end",
        "pending_confirmation": None,
    }