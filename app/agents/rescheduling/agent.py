from __future__ import annotations
import json
from datetime import datetime
from typing import Any
from langchain_core.tools import tool
from langchain_core.messages import AIMessage
from app.agents.booking.agent import (
    MAX_SLOTS_TO_PRESENT,
    _TIME_PERIOD_RANGES,
    _is_holiday,
    _parse_date,
    _parse_time_of_day,
    check_doctor_availability,
)
from app.agents.cancellation.agent import lookup_appointment
from app.agents.state import HospitalAgentState
from app.db.base import get_session_context
from app.db.repositories.appointment_repo import AppointmentRepository
from app.db.repositories.doctor_repo import DoctorRepository
from app.logger import logging

logger = logging.getLogger(__name__)


@tool
async def reschedule_appointment(appointment_id: str, new_datetime: str, reason: str | None = None) -> str:
    """
    Reschedule an appointment to a new date/time.

    This tool is NOT called by reschedule_agent_node directly - it is
    exported for the action_executor node, which calls it
    only after the patient has explicitly confirmed the "from"/"to"
    summary in state["pending_confirmation"].

    Parameters
    ----------
    appointment_id   The existing appointment to reschedule.
    new_datetime     ISO datetime string for the new slot, e.g.
                      "2024-11-08T10:00:00".
    reason           Optional reason for rescheduling.

    Returns
    -------
    A JSON string. On success: {"success": true, "old_appointment_id":
    str, "new_appointment_id": str, "scheduled_at": str, "status": str}.
    On failure (original not cancellable, or new slot unavailable):
    {"success": false, "error": str}. On failure, the original
    appointment is guaranteed unchanged - AppointmentRepository.reschedule()
    performs the cancel+create atomically and rolls back on error.
    """
    parsed_dt = datetime.fromisoformat(new_datetime)

    async with get_session_context() as session:
        repo = AppointmentRepository(session)
        try:
            new_appt = await repo.reschedule(appointment_id, parsed_dt, reason=reason)
        except ValueError as exc:
            logger.warning(f"reschedule_appointment failed for {appointment_id}: {exc}")
            return json.dumps({"success": False, "error": str(exc)})

    logger.info(f"reschedule_appointment succeeded: {appointment_id} -> {new_appt.appointment_id}")
    return json.dumps({
        "success": True,
        "old_appointment_id": appointment_id,
        "new_appointment_id": new_appt.appointment_id,
        "scheduled_at": new_appt.scheduled_at.isoformat(),
        "status": new_appt.status,
    })


rescheduling_tools = [lookup_appointment, check_doctor_availability, reschedule_appointment]


async def reschedule_agent_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Appointment Rescheduling Agent graph node.

    See module docstring for the full flow. This node never performs a
    write - it only reads the existing appointment and new-slot
    availability, then sets state["pending_confirmation"] for
    action_executor (Step 40).

    Returns
    -------
    A partial state update dict.
    """
    session_id = state["session_id"]
    entities = dict(state.get("entities", {}))

    if not state.get("is_authenticated", False):
        logger.info(f"reschedule_agent: session={session_id} not authenticated, redirecting to auth_agent")
        return {
            "messages": [AIMessage(content="To reschedule an appointment, I first need to verify your identity. Could you provide your patient ID, date of birth, and the last 4 digits of your registered phone number?")],
            "active_agent": "auth_agent",
            "next_action": "auth_agent",
        }

    patient_id = state["patient_id"]
    appointment_id = entities.get("appointment_id", "")
    existing_date = entities.get("date", "")

    lookup_raw = await lookup_appointment.ainvoke({
        "appointment_id": appointment_id,
        "patient_id": patient_id if not appointment_id else "",
        "target_date": existing_date if not appointment_id else "",
    })
    lookup_result = json.loads(lookup_raw)
    appointments = lookup_result.get("appointments", [])

    if not appointments:
        logger.info(f"reschedule_agent: session={session_id} no appointment found")
        return {
            "messages": [AIMessage(content="I couldn't find an appointment matching that. Could you give me the appointment ID, or the date of the appointment you'd like to reschedule?")],
            "active_agent": "reschedule_agent",
            "next_action": "end",
            "entities": entities,
        }

    if len(appointments) > 1:
        options = "\n".join(
            f"- {a['appointment_id']} on {a['scheduled_at']}" for a in appointments[:5]
        )
        return {
            "messages": [AIMessage(content=f"I found a few upcoming appointments. Which one would you like to reschedule?\n{options}")],
            "active_agent": "reschedule_agent",
            "next_action": "end",
            "entities": entities,
        }

    appt = appointments[0]

    if appt["patient_id"] != patient_id:
        logger.warning(f"reschedule_agent: session={session_id} ownership mismatch")
        return {
            "messages": [AIMessage(content="I couldn't find an appointment matching that.")],
            "active_agent": "reschedule_agent",
            "next_action": "end",
            "entities": entities,
        }

    if not appt["is_cancellable"]:
        return {
            "messages": [AIMessage(content=f"Appointment {appt['appointment_id']} can't be rescheduled - it may already be cancelled or completed, or it's less than 24 hours away. Please contact reception at 16700 for help.")],
            "active_agent": "reschedule_agent",
            "next_action": "end",
            "entities": entities,
        }

    doctor_id = appt["doctor_id"]

    async with get_session_context() as session:
        doctor_repo = DoctorRepository(session)
        doctor = await doctor_repo.get_by_id(doctor_id, load_department=True)

    doctor_name = doctor.full_name if doctor else f"Doctor #{doctor_id}"
    specialization_name = doctor.specialization if doctor else ""
    old_scheduled_at = datetime.fromisoformat(appt["scheduled_at"])

    if not entities.get("new_date"):
        return {
            "messages": [AIMessage(content=f"Sure, I can help reschedule your appointment with {doctor_name} (currently {old_scheduled_at.strftime('%A, %d %B %Y at %I:%M %p')}). What new date would you like?")],
            "active_agent": "reschedule_agent",
            "next_action": "end",
            "entities": entities,
        }

    new_date = _parse_date(str(entities["new_date"]))
    if new_date is None:
        return {
            "messages": [AIMessage(content="I couldn't understand that date. Could you give me a specific date, like '2024-11-08', or a day of the week?")],
            "active_agent": "reschedule_agent",
            "next_action": "end",
            "entities": entities,
        }

    if _is_holiday(new_date):
        return {
            "messages": [AIMessage(content=f"{new_date.strftime('%A, %d %B %Y')} is a hospital holiday. Could you choose a different date?")],
            "active_agent": "reschedule_agent",
            "next_action": "end",
            "entities": entities,
        }

    if not entities.get("new_time"):
        return {
            "messages": [AIMessage(content=f"And what time on {new_date.strftime('%A, %d %B %Y')} works for you? You can also just say morning, afternoon, or evening.")],
            "active_agent": "reschedule_agent",
            "next_action": "end",
            "entities": entities,
        }

    availability_raw = await check_doctor_availability.ainvoke({
        "doctor_id": doctor_id,
        "target_date": new_date.isoformat(),
    })
    available_slots = json.loads(availability_raw)

    if not available_slots:
        return {
            "messages": [AIMessage(content=f"Unfortunately {doctor_name} has no available slots on {new_date.strftime('%A, %d %B %Y')}. Your current appointment is unchanged - could you try a different date?")],
            "active_agent": "reschedule_agent",
            "next_action": "end",
            "entities": {**entities, "new_date": None, "new_time": None},
        }

    specific_time, period = _parse_time_of_day(str(entities["new_time"]))

    chosen_slot = None

    if specific_time is not None:
        for slot in available_slots:
            slot_dt = datetime.fromisoformat(slot["starts_at"])
            if slot_dt.time() == specific_time:
                chosen_slot = slot
                break
        if chosen_slot is None:
            options = available_slots[:MAX_SLOTS_TO_PRESENT]
            times = ", ".join(
                datetime.fromisoformat(s["starts_at"]).strftime("%I:%M %p") for s in options
            )
            return {
                "messages": [AIMessage(content=f"That exact time isn't available on {new_date.strftime('%A, %d %B %Y')}. Open times: {times}. Your current appointment is unchanged - which would you like?")],
                "active_agent": "reschedule_agent",
                "next_action": "end",
                "entities": {**entities, "new_time": None},
            }
    elif period is not None:
        start, end = _TIME_PERIOD_RANGES[period]
        matching = [
            s for s in available_slots
            if start <= datetime.fromisoformat(s["starts_at"]).time() < end
        ]
        if not matching:
            return {
                "messages": [AIMessage(content=f"There are no {period} slots available on {new_date.strftime('%A, %d %B %Y')}. Your current appointment is unchanged - would another date or time of day work?")],
                "active_agent": "reschedule_agent",
                "next_action": "end",
                "entities": {**entities, "new_time": None},
            }
        if len(matching) == 1:
            chosen_slot = matching[0]
        else:
            options = matching[:MAX_SLOTS_TO_PRESENT]
            times = ", ".join(
                datetime.fromisoformat(s["starts_at"]).strftime("%I:%M %p") for s in options
            )
            return {
                "messages": [AIMessage(content=f"Available {period} times on {new_date.strftime('%A, %d %B %Y')}: {times}. Which would you like?")],
                "active_agent": "reschedule_agent",
                "next_action": "end",
                "entities": {**entities, "new_time": None},
            }
    else:
        options = available_slots[:MAX_SLOTS_TO_PRESENT]
        times = ", ".join(
            datetime.fromisoformat(s["starts_at"]).strftime("%I:%M %p") for s in options
        )
        return {
            "messages": [AIMessage(content=f"I didn't quite catch a time. Options on {new_date.strftime('%A, %d %B %Y')}: {times}. Which would you like?")],
            "active_agent": "reschedule_agent",
            "next_action": "end",
            "entities": {**entities, "new_time": None},
        }

    new_scheduled_at = datetime.fromisoformat(chosen_slot["starts_at"])

    pending_confirmation = {
        "action": "reschedule_appointment",
        "summary": (
            f"Reschedule {appt['appointment_id']} with {doctor_name} from "
            f"{old_scheduled_at.strftime('%A, %d %B %Y at %I:%M %p')} to "
            f"{new_scheduled_at.strftime('%A, %d %B %Y at %I:%M %p')}"
        ),
        "params": {
            "appointment_id": appt["appointment_id"],
            "new_datetime": new_scheduled_at.isoformat(),
            "reason": entities.get("reschedule_reason"),
        },
    }

    summary_message = (
        "Here's the change I'm about to make:\n"
        f"- Doctor: {doctor_name} ({specialization_name})\n"
        f"- From: {old_scheduled_at.strftime('%A, %d %B %Y at %I:%M %p')}\n"
        f"- To: {new_scheduled_at.strftime('%A, %d %B %Y at %I:%M %p')}\n"
        "If the new time becomes unavailable before I confirm, your "
        "current appointment will remain unchanged.\n"
        "Shall I go ahead with this change? (yes/no)"
    )

    logger.info(f"reschedule_agent: session={session_id} pending_confirmation set for {appt['appointment_id']}")

    return {
        "messages": [AIMessage(content=summary_message)],
        "active_agent": "reschedule_agent",
        "next_action": "end",
        "pending_confirmation": pending_confirmation,
        "entities": entities,
    }