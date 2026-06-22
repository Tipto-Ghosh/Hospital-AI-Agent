""" 
The canonical @tool implementations for appointment operations:
check_doctor_availability, check_patient_exists, create_appointment,
cancel_appointment, and get_appointment_details.
 
check_doctor_availability, check_patient_exists, and create_appointment
were originally defined inline inside app/agents/booking/agent.py. 
cancel_appointment was originally defined inline inside
app/agents/cancellation/agent.py. They are consolidated here
as the single source of truth - app/agents/booking/agent.py and
app/agents/cancellation/agent.py now import these tools from this
module instead of redefining them, and app/agents/rescheduling/agent.py
and app/agents/shared/confirmation_handler.py also import from here.
 
get_appointment_details is new in this step - a read-only tool that
returns a formatted appointment summary, useful for any agent that
needs to describe an appointment without going through the
cancellation-specific lookup_appointment tool.
 
Audit logging
--------------
create_appointment and cancel_appointment both auto-log to audit_log
after a successful write, in addition to whatever the calling agent
or action_executor_node logs - this guarantees every appointment
mutation is recorded regardless of which code path triggered it.
"""

from __future__ import annotations
 
import json
from datetime import date, datetime
from typing import Optional
 
from langchain_core.tools import tool
 
from app.db.base import get_session_context
from app.db.repositories.appointment_repo import AppointmentRepository
from app.db.repositories.audit_repo import AuditRepository
from app.db.repositories.doctor_repo import DoctorRepository
from app.db.repositories.patient_repo import PatientRepository
from app.logger import logging
 
logger = logging.getLogger(__name__)


@tool
async def check_doctor_availability(doctor_id: int, target_date: str) -> str:
    """
    Get available appointment slots for a doctor on a given date.
 
    Parameters
    ----------
    doctor_id     The doctor's PK.
    target_date   ISO date string, e.g. "2024-11-05".
 
    Returns
    -------
    A JSON string containing a list of available slots, each with
    starts_at, ends_at (ISO datetimes), and duration_minutes. Returns
    an empty list if the doctor doesn't work that day or is fully
    booked.
    """
    parsed_date = date.fromisoformat(target_date)
 
    async with get_session_context() as session:
        repo = AppointmentRepository(session)
        slots = await repo.get_available_slots(doctor_id, parsed_date)
 
    results = [
        {
            "starts_at": s.starts_at.isoformat(),
            "ends_at": s.ends_at.isoformat(),
            "duration_minutes": s.slot_minutes,
        }
        for s in slots
    ]
 
    logger.info(
        f"check_doctor_availability(doctor_id={doctor_id}, date={target_date}) "
        f"-> {len(results)} slot(s)"
    )
    return json.dumps(results)


@tool
async def check_patient_exists(phone: str) -> str:
    """
    Check whether a patient with the given phone number is registered.
 
    If no patient exists, a minimal pre-registration record is created
    (is_active=False) so a booking can proceed - hospital staff
    complete full registration later.
 
    Parameters
    ----------
    phone   Phone number as provided by the patient.
 
    Returns
    -------
    A JSON string: {"patient_id": str, "full_name": str,
    "is_active": bool, "created": bool}.
    """
    async with get_session_context() as session:
        repo = PatientRepository(session)
        patient, created = await repo.get_or_create_anonymous(phone)
 
    result = {
        "patient_id": patient.patient_id,
        "full_name": patient.full_name,
        "is_active": patient.is_active,
        "created": created,
    }
 
    logger.info(f"check_patient_exists(phone={phone}) -> patient_id={patient.patient_id} created={created}")
    return json.dumps(result)


@tool
async def create_appointment(
    patient_id: str,
    doctor_id: int,
    scheduled_at: str,
    reason: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Create a new appointment.
 
    This tool is exported for action_executor_node, which calls it only
    after the patient has explicitly confirmed the booking summary in
    state["pending_confirmation"].
 
    Parameters
    ----------
    patient_id: Patient PK.
    doctor_id : Doctor PK.
    scheduled_at : ISO datetime string, e.g. "2024-11-05T10:00:00".
    reason : Optional reason for visit.
    notes : Optional internal notes.
 
    Returns
    -------
    A JSON string: on success, {"success": true, "appointment_id": str,
    "scheduled_at": str, "status": str}. On failure (slot taken, too
    soon, duplicate active appointment),
    {"success": false, "error": str}.
 
    Guardrails enforced by AppointmentRepository.create():
      - Minimum 2-hour advance notice.
      - No double-booking of the same doctor/slot.
      - Max one active appointment per patient per doctor.
 
    On success, this tool also writes an audit_log entry
    (action="create_appointment") so the mutation is recorded
    regardless of which agent or graph node invoked it.
    """
    parsed_dt = datetime.fromisoformat(scheduled_at)
 
    async with get_session_context() as session:
        repo = AppointmentRepository(session)
        try:
            appt = await repo.create(
                patient_id=patient_id,
                doctor_id=doctor_id,
                scheduled_at=parsed_dt,
                reason=reason,
                notes=notes,
                booked_via="ai_agent",
            )
        except ValueError as exc:
            logger.warning(f"create_appointment failed for patient={patient_id}: {exc}")
            return json.dumps({"success": False, "error": str(exc)})
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="appointment_tools",
            action="create_appointment",
            patient_id=patient_id,
            resource_type="appointment",
            resource_id=appt.appointment_id,
            payload_summary=f"Created appointment with doctor {doctor_id}.",
        )
 
    logger.info(f"create_appointment succeeded: {appt.appointment_id} for patient={patient_id}")
    return json.dumps({
        "success": True,
        "appointment_id": appt.appointment_id,
        "scheduled_at": appt.scheduled_at.isoformat(),
        "status": appt.status,
    })


@tool
async def cancel_appointment(appointment_id: str, reason: Optional[str] = None) -> str:
    """
    Cancel an appointment (soft-delete: status -> 'cancelled').
 
    This tool is exported for action_executor_node
    (app/agents/shared/confirmation_handler.py), which calls it only
    after the patient has explicitly confirmed the cancellation
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
 
    On success, this tool also writes an audit_log entry
    (action="cancel_appointment") so the mutation is recorded
    regardless of which agent or graph node invoked it.
    """
    async with get_session_context() as session:
        repo = AppointmentRepository(session)
        try:
            appt = await repo.cancel(appointment_id, reason=reason)
        except ValueError as exc:
            logger.warning(f"cancel_appointment failed for {appointment_id}: {exc}")
            return json.dumps({"success": False, "error": str(exc)})
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="appointment_tools",
            action="cancel_appointment",
            patient_id=appt.patient_id,
            resource_type="appointment",
            resource_id=appointment_id,
            payload_summary="Appointment cancelled.",
        )
 
    logger.info(f"cancel_appointment succeeded: {appointment_id}")
    return json.dumps({"success": True, "appointment_id": appt.appointment_id, "status": appt.status})


@tool
async def get_appointment_details(appointment_id: str) -> str:
    """
    Get a formatted summary of a single appointment by ID.
 
    Parameters
    ----------
    appointment_id   The appointment PK, e.g. "APT-20241105-0001".
 
    Returns
    -------
    A JSON string. If not found: {"found": false}. Otherwise:
    {"found": true, "appointment_id": str, "patient_id": str,
    "doctor_id": int, "doctor_name": str, "specialization": str,
    "scheduled_at": str, "duration_min": int, "status": str,
    "reason_for_visit": str|null, "is_cancellable": bool}.
    """
    async with get_session_context() as session:
        appt_repo = AppointmentRepository(session)
        appt = await appt_repo.get_by_id(appointment_id)
 
        if appt is None:
            logger.info(f"get_appointment_details(appointment_id={appointment_id!r}) -> not found")
            return json.dumps({"found": False})
 
        doctor_repo = DoctorRepository(session)
        doctor = await doctor_repo.get_by_id(appt.doctor_id, load_department=True)
 
    result = {
        "found": True,
        "appointment_id": appt.appointment_id,
        "patient_id": appt.patient_id,
        "doctor_id": appt.doctor_id,
        "doctor_name": doctor.full_name if doctor else f"Doctor #{appt.doctor_id}",
        "specialization": doctor.specialization if doctor else None,
        "scheduled_at": appt.scheduled_at.isoformat(),
        "duration_min": appt.duration_min,
        "status": appt.status,
        "reason_for_visit": appt.reason_for_visit,
        "is_cancellable": appt.is_cancellable(),
    }
 
    logger.info(f"get_appointment_details(appointment_id={appointment_id!r}) -> found, status={appt.status}")
    return json.dumps(result)

appointment_tools = [
    check_doctor_availability,
    check_patient_exists,
    create_appointment,
    cancel_appointment,
    get_appointment_details,
]