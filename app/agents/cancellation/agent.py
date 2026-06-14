""" 
The Appointment Cancellation Agent, responsible for handling user requests to cancel appointments.

Authentication gate:
Cancelling an appointment is a write operation on a specific patient's
record, so this node checks state["is_authenticated"] BEFORE doing
anything else. If the session is not authenticated, the node redirects
to the auth flow (next_action="auth_agent") and does not look up or
reveal any appointment details.

Flow once authenticated:
1. lookup_appointment() finds the appointment by appointment_id (or by
   patient_id + date if no appointment_id was given).
2. Ownership is checked: the appointment must belong to
   state["patient_id"].
3. is_cancellable() (24-hour notice rule, not already
   cancelled/completed/no_show) is checked.
4. If cancellable, state["pending_confirmation"] is set describing a
   cancel_appointment action, and the patient is asked to confirm.
5. The actual cancel_appointment / free_doctor_slot /
   send_cancellation_notice calls happen in action_executor (Step 40)
   after confirmation - this node only performs READ operations.

Free doctor slot:
AppointmentRepository.cancel() sets status='cancelled' and
get_available_slots() / get_by_doctor_and_date() already exclude
cancelled appointments. 
The doctor's slot is therefore freed automatically as a side effect of cancellation - free_doctor_slot is a
documented no-op tool kept for tool-registry completeness and explicit
audit-trail logging.

send_cancellation_notice:
SMS/email notification delivery is implemented via Celery.
"""

from __future__ import annotations
import json
from datetime import datetime as date_type
from typing import Optional, Any

from langchain_core.tools import tool
from langchain_core.messages import AIMessage

from app.agents.state import HospitalAgentState
from app.db.base import get_session_context
from app.db.repositories.appointment_repo import AppointmentRepository
from app.db.repositories.doctor_repo import DoctorRepository
from app.db.repositories.patient_repo import PatientRepository
from app.logger import logging
 
logger = logging.getLogger(__name__)

@tool
async def lookup_appointment(
    appointment_id: str = "",
    patient_id: str = "",
    target_date: str = "",
) -> str:
    """
    Find an appointment by appointment_id, or by patient_id and an
    optional date.
 
    Parameters
    ----------
    appointment_id   Exact appointment PK, e.g. "APT-20241105-0001".
                      If provided, this takes priority and the other
                      parameters are ignored.
    patient_id       Patient PK. Used with target_date to search a
                      patient's upcoming appointments when no
                      appointment_id is known.
    target_date      ISO date string, e.g. "2024-11-05". Filters
                      patient_id's appointments to this date.
 
    Returns
    -------
    A JSON string: {"found": true, "appointments": [...]} where each
    appointment includes appointment_id, doctor_id, scheduled_at,
    status, patient_id, and is_cancellable. If nothing is found,
    {"found": false, "appointments": []}.
    """
    async with get_session_context() as session:
        repo = AppointmentRepository(session)
 
        if appointment_id:
            appt = await repo.get_by_id(appointment_id)
            appointments = [appt] if appt else []
        else:
            appointments = await repo.get_by_patient(patient_id, upcoming_only=True)
            if target_date:
                parsed = date_type.fromisoformat(target_date)
                appointments = [a for a in appointments if a.scheduled_at.date() == parsed]
 
    results = [
        {
            "appointment_id": a.appointment_id,
            "patient_id": a.patient_id,
            "doctor_id": a.doctor_id,
            "scheduled_at": a.scheduled_at.isoformat(),
            "status": a.status,
            "is_cancellable": a.is_cancellable(),
        }
        for a in appointments
    ]
 
    logger.info(
        f"lookup_appointment(appointment_id={appointment_id!r}, "
        f"patient_id={patient_id!r}, target_date={target_date!r}) "
        f"-> {len(results)} result(s)"
    )
    return json.dumps({"found": bool(results), "appointments": results})
 
 
@tool
async def verify_patient_identity(patient_id: str, date_of_birth: str, phone_last4: str) -> str:
    """
    Verify a patient's identity using three factors.
 
    Parameters
    ----------
    patient_id      Patient PK as claimed, e.g. "P-2024-00001".
    date_of_birth   ISO date string, e.g. "1990-05-15".
    phone_last4     Last 4 digits of the registered phone number.
 
    Returns
    -------
    A JSON string: {"verified": true|false}. Gives no detail about
    which factor failed.
    """
    parsed_dob = date_type.fromisoformat(date_of_birth)
 
    async with get_session_context() as session:
        repo = PatientRepository(session)
        verified = await repo.verify_identity(patient_id, parsed_dob, phone_last4)
 
    logger.info(f"verify_patient_identity(patient_id={patient_id!r}) -> verified={verified}")
    return json.dumps({"verified": verified})
 
 
@tool
async def cancel_appointment(appointment_id: str, reason: Optional[str] = None) -> str:
    """
    Cancel an appointment (soft-delete: status -> 'cancelled').
 
    This tool is NOT called by cancel_agent_node directly - it is
    exported for the action_executor node (Step 40), which calls it
    only after the patient has explicitly confirmed the cancellation
    summary in state["pending_confirmation"].
 
    Parameters
    ----------
    appointment_id   The appointment to cancel.
    reason           Optional patient-provided reason.
 
    Returns
    -------
    A JSON string: on success, {"success": true, "appointment_id": str,
    "status": "cancelled"}. On failure (not found, or cancellation
    policy violated - e.g. within 24 hours of the appointment),
    {"success": false, "error": str}.
    """
    async with get_session_context() as session:
        repo = AppointmentRepository(session)
        try:
            appt = await repo.cancel(appointment_id, reason=reason)
        except ValueError as exc:
            logger.warning(f"cancel_appointment failed for {appointment_id}: {exc}")
            return json.dumps({"success": False, "error": str(exc)})
 
    logger.info(f"cancel_appointment succeeded: {appointment_id}")
    return json.dumps({"success": True, "appointment_id": appt.appointment_id, "status": appt.status})
 
 
@tool
async def free_doctor_slot(doctor_id: int, scheduled_at: str) -> str:
    """
    Confirm that a doctor's slot has been freed after cancellation.
 
    AppointmentRepository.cancel() already excludes cancelled
    appointments from availability calculations - the slot is freed as
    a direct side effect of the status change. This tool exists for
    tool-registry completeness and audit-trail clarity; it performs no
    database write of its own.
 
    Parameters
    ----------
    doctor_id      The doctor whose slot was freed.
    scheduled_at   ISO datetime string of the freed slot.
 
    Returns
    -------
    A JSON string: {"freed": true, "doctor_id": int, "scheduled_at": str}.
    """
    logger.info(f"free_doctor_slot: doctor_id={doctor_id} scheduled_at={scheduled_at} (no-op, freed via cancel)")
    return json.dumps({"freed": True, "doctor_id": doctor_id, "scheduled_at": scheduled_at})
 
 
@tool
async def send_cancellation_notice(patient_contact: str, appointment_details: str) -> str:
    """
    Send a cancellation confirmation notice to the patient.
 
    Stub implementation - actual SMS/email delivery is implemented via
    Celery in Phase 7. This logs the notification intent so the
    cancellation flow can be exercised end-to-end before Celery is
    wired up.
 
    Parameters
    ----------
    patient_contact       Phone number or email to notify.
    appointment_details   Short human-readable summary of the
                            cancelled appointment.
 
    Returns
    -------
    A JSON string: {"queued": true, "contact": str}.
    """
    logger.info(f"send_cancellation_notice (stub): contact={patient_contact} details={appointment_details}")
    return json.dumps({"queued": True, "contact": patient_contact})
 
 
cancellation_tools = [
    lookup_appointment,
    verify_patient_identity,
    cancel_appointment,
    free_doctor_slot,
    send_cancellation_notice,
]
 
 
async def cancel_agent_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Appointment Cancellation Agent graph node.
 
    Flow
    ----
    1. If the session is not authenticated, redirect to auth_agent -
       no appointment details are looked up or revealed.
    2. lookup_appointment() by appointment_id (preferred) or by
       patient_id + date.
    3. Ownership check: the appointment must belong to
       state["patient_id"].
    4. is_cancellable() check (24-hour notice rule).
    5. If cancellable, set state["pending_confirmation"] with action
       "cancel_appointment" and ask the patient to confirm.
 
    Returns
    -------
    A partial state update dict.
    """
    session_id = state["session_id"]
    entities = dict(state.get("entities", {}))
 
    if not state.get("is_authenticated", False):
        logger.info(f"cancel_agent: session={session_id} not authenticated, redirecting to auth_agent")
        return {
            "messages": [AIMessage(content="To cancel an appointment, I first need to verify your identity. Could you provide your patient ID, date of birth, and the last 4 digits of your registered phone number?")],
            "active_agent": "auth_agent",
            "next_action": "auth_agent",
        }
 
    patient_id = state["patient_id"]
    appointment_id = entities.get("appointment_id", "")
    target_date = entities.get("date", "")
 
    lookup_raw = await lookup_appointment.ainvoke({
        "appointment_id": appointment_id,
        "patient_id": patient_id if not appointment_id else "",
        "target_date": target_date if not appointment_id else "",
    })
    lookup_result = json.loads(lookup_raw)
    appointments = lookup_result.get("appointments", [])
 
    if not appointments:
        logger.info(f"cancel_agent: session={session_id} no appointment found")
        return {
            "messages": [AIMessage(content="I couldn't find an appointment matching that. Could you give me the appointment ID, or the date of the appointment you'd like to cancel?")],
            "active_agent": "cancel_agent",
            "next_action": "end",
            "entities": entities,
        }
 
    if len(appointments) > 1:
        options = "\n".join(
            f"- {a['appointment_id']} on {a['scheduled_at']}" for a in appointments[:5]
        )
        return {
            "messages": [AIMessage(content=f"I found a few upcoming appointments. Which one would you like to cancel?\n{options}")],
            "active_agent": "cancel_agent",
            "next_action": "end",
            "entities": entities,
        }
 
    appt = appointments[0]
 
    if appt["patient_id"] != patient_id:
        logger.warning(
            f"cancel_agent: session={session_id} ownership mismatch - "
            f"appointment belongs to a different patient"
        )
        return {
            "messages": [AIMessage(content="I couldn't find an appointment matching that.")],
            "active_agent": "cancel_agent",
            "next_action": "end",
            "entities": entities,
        }
 
    if not appt["is_cancellable"]:
        return {
            "messages": [AIMessage(content=f"Appointment {appt['appointment_id']} can't be cancelled - it may already be cancelled or completed, or it's less than 24 hours away. Please contact reception at 16700 for help.")],
            "active_agent": "cancel_agent",
            "next_action": "end",
            "entities": entities,
        }
 
    async with get_session_context() as session:
        doctor_repo = DoctorRepository(session)
        doctor = await doctor_repo.get_by_id(appt["doctor_id"], load_department=True)
 
    doctor_name = doctor.full_name if doctor else f"Doctor #{appt['doctor_id']}"
    specialization_name = doctor.specialization if doctor else ""
    from datetime import datetime as _datetime
    scheduled_at = _datetime.fromisoformat(appt["scheduled_at"])
 
    pending_confirmation = {
        "action": "cancel_appointment",
        "summary": (
            f"Cancel appointment {appt['appointment_id']} with "
            f"{doctor_name} on {scheduled_at.strftime('%A, %d %B %Y at %I:%M %p')}"
        ),
        "params": {
            "appointment_id": appt["appointment_id"],
            "reason": entities.get("cancellation_reason"),
        },
    }
 
    summary_message = (
        "Here's the appointment I found:\n"
        f"- Appointment ID: {appt['appointment_id']}\n"
        f"- Doctor: {doctor_name} ({specialization_name})\n"
        f"- Date and time: {scheduled_at.strftime('%A, %d %B %Y at %I:%M %p')}\n"
        "Cancellations within 24 hours of the appointment time are not "
        "permitted - this appointment is still eligible.\n"
        "Shall I go ahead and cancel this? (yes/no)"
    )
 
    logger.info(f"cancel_agent: session={session_id} pending_confirmation set for {appt['appointment_id']}")
 
    return {
        "messages": [AIMessage(content=summary_message)],
        "active_agent": "cancel_agent",
        "next_action": "end",
        "pending_confirmation": pending_confirmation,
        "entities": entities,
    }