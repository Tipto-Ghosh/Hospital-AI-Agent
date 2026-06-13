"""
The Appointment Booking Agent node and its tools.

Flow:
----
1. check_slots() / get_next_missing_slot() comes from slot_filler.py to determine
   whether all four required pieces of information are present in
   state["entities"]:
       patient_identity, preferred_doctor, preferred_date, preferred_time

2. If any slot is missing, generate_slot_question() produces the next
   question and the turn ends - no tools are called.

3. Once all slots are present, this node resolves them to concrete
   values:
       - patient_identity -> patient_id (via check_patient_exists,
         creating a pre-registration if needed)
       - preferred_doctor -> doctor_id (via DoctorRepository.search)
       - preferred_date -> a date object
       - preferred_time -> a specific available slot (via check_doctor_availability)

4. If any resolution step is ambiguous or fails (doctor not found,
   no availability on that date, etc.), the agent asks a clarifying
   question and the relevant slot is marked missing again.

5. Once a single concrete slot is chosen, the agent builds
   state["pending_confirmation"] describing a create_appointment
   action, and asks the patient to confirm with yes/no.

Guardrails
----------
- 2-hour advance notice and double-booking are enforced inside
  AppointmentRepository.create() / get_available_slots() - this agent
  never offers or confirms a slot that violates those rules, because
  it only offers slots returned by get_available_slots().
- Holiday check: HOSPITAL_HOLIDAYS below is the single place to add
  hospital closure dates. If preferred_date falls on a holiday, the
  agent asks for a different date before checking availability.
- create_appointment is bound here but NOT executed by this node - the
  actual write happens in action_executor (Step 40) after the patient
  confirms. This node only ever performs READ operations.
"""

from __future__ import annotations
import json
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.agents.booking.prompts import build_booking_prompt
from app.agents.booking.slot_filler import (
    check_slots,
    generate_slot_question,
    get_next_missing_slot,
)
from app.agents.state import HospitalAgentState
from app.config import get_settings
from app.db.base import get_session_context
from app.db.repositories.appointment_repo import AppointmentRepository
from app.db.repositories.doctor_repo import DoctorRepository
from app.db.repositories.patient_repo import PatientRepository
from app.llm.factory import LLMTier, get_llm
from app.logger import logging as logger

"""
Hospital closure dates. Add ISO date strings ("YYYY-MM-DD") here for
public holidays or planned closures. Checked against preferred_date
before availability lookup - the agent will ask for a different date
if a match is found.
"""
HOSPITAL_HOLIDAYS: list[str] = []

MAX_SLOTS_TO_PRESENT = 5

_WEEKDAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]

_TIME_PERIOD_RANGES: dict[str, tuple[time, time]] = {
    "morning": (time(6, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(21, 0)),
}

_TIME_FORMATS = ["%H:%M", "%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H%M"]


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
    (is_active=False) so the booking can proceed - hospital staff
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

    This tool is NOT called by booking_agent_node directly - it is
    exported for the action_executor node (Step 40), which calls it
    only after the patient has explicitly confirmed the booking
    summary in state["pending_confirmation"].

    Parameters
    ----------
    patient_id     Patient PK.
    doctor_id      Doctor PK.
    scheduled_at   ISO datetime string, e.g. "2024-11-05T10:00:00".
    reason         Optional reason for visit.
    notes          Optional internal notes.

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

    logger.info(f"create_appointment succeeded: {appt.appointment_id} for patient={patient_id}")
    return json.dumps({
        "success": True,
        "appointment_id": appt.appointment_id,
        "scheduled_at": appt.scheduled_at.isoformat(),
        "status": appt.status,
    })


booking_tools = [check_doctor_availability, check_patient_exists, create_appointment]


def _is_holiday(target_date: date) -> bool:
    """Return True if target_date is in HOSPITAL_HOLIDAYS."""
    return target_date.isoformat() in HOSPITAL_HOLIDAYS


def _parse_date(date_str: str) -> Optional[date]:
    """
    Parse a date string into a date object.

    Accepts:
      - ISO format "YYYY-MM-DD"
      - "today" / "tomorrow"
      - Weekday names ("Monday", "friday", etc.) - resolved to the next
        occurrence of that weekday, at least 1 day in the future.

    Returns None if the string cannot be parsed - the caller should
    ask the patient to clarify in that case.
    """
    cleaned = date_str.strip().lower()

    try:
        return date.fromisoformat(date_str.strip())
    except ValueError:
        pass

    today = datetime.utcnow().date()

    if cleaned == "today":
        return today
    if cleaned == "tomorrow":
        return today + timedelta(days=1)

    if cleaned in _WEEKDAY_NAMES:
        target_weekday = _WEEKDAY_NAMES.index(cleaned)
        delta = (target_weekday - today.weekday() + 7) % 7
        delta = delta or 7  # "this Monday" means next Monday, not today
        return today + timedelta(days=delta)

    return None


def _parse_time_of_day(time_str: str) -> tuple[Optional[time], Optional[str]]:
    """
    Parse a time string into either a specific time or a period name.

    Returns
    -------
    (specific_time, period) - exactly one of these is non-None, or both
    are None if the string could not be parsed at all.

    "morning" / "afternoon" / "evening" -> (None, period)
    "10:00", "10 AM", "2:30pm", etc.    -> (time_obj, None)
    """
    cleaned = time_str.strip().lower()

    if cleaned in _TIME_PERIOD_RANGES:
        return None, cleaned

    for fmt in _TIME_FORMATS:
        try:
            parsed = datetime.strptime(time_str.strip(), fmt)
            return parsed.time(), None
        except ValueError:
            continue

    return None, None


async def _resolve_doctor(entities: dict[str, Any]) -> tuple[Optional[int], Optional[list[dict]], Optional[str]]:
    """
    Resolve preferred_doctor entities to a single doctor_id.

    Returns
    -------
    (doctor_id, candidates, error)

    Exactly one of the following holds:
      - doctor_id is set, candidates and error are None: a single
        unambiguous doctor was found.
      - candidates is a list (possibly empty), doctor_id and error are
        None: zero or multiple matches were found - the caller should
        present `candidates` (if non-empty) or ask for clarification
        (if empty).
      - error is set: an unexpected failure occurred.
    """
    if entities.get("doctor_id"):
        try:
            return int(entities["doctor_id"]), None, None
        except (TypeError, ValueError):
            pass

    name = entities.get("doctor_name")
    specialization = entities.get("specialization")

    if not name and not specialization:
        return None, [], None

    try:
        async with get_session_context() as session:
            repo = DoctorRepository(session)
            doctors = await repo.search(name=name, specialization=specialization)
    except Exception as exc:
        logger.error(f"_resolve_doctor lookup failed: {exc}")
        return None, None, "I'm having trouble looking up doctors right now."

    if len(doctors) == 1:
        return doctors[0].doctor_id, None, None

    candidates = [
        {
            "doctor_id": d.doctor_id,
            "full_name": d.full_name,
            "specialization": d.specialization,
        }
        for d in doctors[:MAX_SLOTS_TO_PRESENT]
    ]
    return None, candidates, None


async def _resolve_patient_id(state: HospitalAgentState, entities: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """
    Resolve patient_identity entities to a patient_id.

    Returns
    -------
    (patient_id, error) - error is None on success.

    Resolution order:
      1. Already-authenticated session (state["patient_id"]).
      2. entities["patient_id"] if provided.
      3. entities["phone"] / entities["patient_phone"] via
         check_patient_exists (creates a pre-registration if needed).
    """
    if state.get("patient_id"):
        return state["patient_id"], None

    if entities.get("patient_id"):
        return str(entities["patient_id"]), None

    phone = entities.get("phone") or entities.get("patient_phone")
    if not phone:
        return None, "I still need a phone number or patient ID to continue."

    try:
        result = await check_patient_exists.ainvoke({"phone": phone})
        data = json.loads(result)
        return data["patient_id"], None
    except Exception as exc:
        logger.error(f"_resolve_patient_id failed for phone={phone}: {exc}")
        return None, "I'm having trouble looking up your account right now."


def _format_summary(
    doctor_name: str,
    specialization: str,
    scheduled_at: datetime,
    consultation_fee: Optional[float],
    reason: Optional[str],
) -> str:
    """Build a deterministic, template-based booking summary as a fallback."""
    lines = [
        "Here's a summary of your appointment:",
        f"- Doctor: {doctor_name} ({specialization})",
        f"- Date and time: {scheduled_at.strftime('%A, %d %B %Y at %I:%M %p')}",
    ]
    if consultation_fee is not None:
        lines.append(f"- Consultation fee: {consultation_fee:.2f}")
    if reason:
        lines.append(f"- Reason for visit: {reason}")
    lines.append("Shall I go ahead and book this for you? (yes/no)")
    return "\n".join(lines)


async def booking_agent_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Appointment Booking Agent graph node.

    See module docstring for the full flow. This node never performs a
    write - it only reads availability/patient data and sets
    state["pending_confirmation"] for action_executor (Step 40).

    Returns
    -------
    A partial state update dict.
    """
    entities = dict(state.get("entities", {}))
    session_id = state["session_id"]

    slot_status = check_slots(state)
    missing = get_next_missing_slot(slot_status)

    if missing:
        question = generate_slot_question(missing, entities)
        logger.info(f"booking_agent: session={session_id} missing slot={missing}")
        return {
            "messages": [AIMessage(content=question)],
            "active_agent": "booking_agent",
            "next_action": "end",
            "slot_fill_status": slot_status,
            "entities": entities,
        }

    # All four slots are present - resolve them to concrete values.

    patient_id, patient_error = await _resolve_patient_id(state, entities)
    if patient_error:
        return {
            "messages": [AIMessage(content=patient_error)],
            "active_agent": "booking_agent",
            "next_action": "end",
            "slot_fill_status": {**slot_status, "patient_identity": False},
            "entities": entities,
        }
    entities["patient_id"] = patient_id

    doctor_id, doctor_candidates, doctor_error = await _resolve_doctor(entities)
    if doctor_error:
        return {
            "messages": [AIMessage(content=doctor_error)],
            "active_agent": "booking_agent",
            "next_action": "end",
            "entities": entities,
        }
    if doctor_id is None:
        if doctor_candidates:
            options = "\n".join(
                f"- Dr. {c['full_name']} ({c['specialization']})" for c in doctor_candidates
            )
            message = (
                f"I found a few doctors matching that. Could you let me know "
                f"which one you'd like?\n{options}"
            )
        else:
            message = (
                "I couldn't find a doctor matching that. Could you give me "
                "a doctor's name or a specialization, like 'cardiologist'?"
            )
        return {
            "messages": [AIMessage(content=message)],
            "active_agent": "booking_agent",
            "next_action": "end",
            "slot_fill_status": {**slot_status, "preferred_doctor": False},
            "entities": entities,
        }
    entities["doctor_id"] = doctor_id

    target_date = _parse_date(str(entities.get("date", "")))
    if target_date is None:
        return {
            "messages": [AIMessage(content="I couldn't understand that date. Could you give me a specific date, like '2024-11-05', or a day of the week?")],
            "active_agent": "booking_agent",
            "next_action": "end",
            "slot_fill_status": {**slot_status, "preferred_date": False},
            "entities": entities,
        }

    if _is_holiday(target_date):
        return {
            "messages": [AIMessage(content=f"{target_date.strftime('%A, %d %B %Y')} is a hospital holiday. Could you choose a different date?")],
            "active_agent": "booking_agent",
            "next_action": "end",
            "slot_fill_status": {**slot_status, "preferred_date": False},
            "entities": entities,
        }

    availability_raw = await check_doctor_availability.ainvoke({
        "doctor_id": doctor_id,
        "target_date": target_date.isoformat(),
    })
    available_slots = json.loads(availability_raw)

    if not available_slots:
        return {
            "messages": [AIMessage(content=f"Unfortunately there are no available slots on {target_date.strftime('%A, %d %B %Y')}. Could you try a different date?")],
            "active_agent": "booking_agent",
            "next_action": "end",
            "slot_fill_status": {**slot_status, "preferred_date": False},
            "entities": entities,
        }

    specific_time, period = _parse_time_of_day(str(entities.get("time", "")))

    chosen_slot: Optional[dict] = None

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
                "messages": [AIMessage(content=f"That exact time isn't available. Here are some open times on {target_date.strftime('%A, %d %B %Y')}: {times}. Which would you like?")],
                "active_agent": "booking_agent",
                "next_action": "end",
                "slot_fill_status": {**slot_status, "preferred_time": False},
                "entities": entities,
            }
    elif period is not None:
        start, end = _TIME_PERIOD_RANGES[period]
        matching = [
            s for s in available_slots
            if start <= datetime.fromisoformat(s["starts_at"]).time() < end
        ]
        if not matching:
            return {
                "messages": [AIMessage(content=f"There are no {period} slots available on {target_date.strftime('%A, %d %B %Y')}. Would another date or time of day work?")],
                "active_agent": "booking_agent",
                "next_action": "end",
                "slot_fill_status": {**slot_status, "preferred_time": False},
                "entities": entities,
            }
        if len(matching) == 1:
            chosen_slot = matching[0]
        else:
            options = matching[:MAX_SLOTS_TO_PRESENT]
            times = ", ".join(
                datetime.fromisoformat(s["starts_at"]).strftime("%I:%M %p") for s in options
            )
            return {
                "messages": [AIMessage(content=f"Here are the available {period} times on {target_date.strftime('%A, %d %B %Y')}: {times}. Which one would you like?")],
                "active_agent": "booking_agent",
                "next_action": "end",
                "slot_fill_status": {**slot_status, "preferred_time": False},
                "entities": entities,
            }
    else:
        options = available_slots[:MAX_SLOTS_TO_PRESENT]
        times = ", ".join(
            datetime.fromisoformat(s["starts_at"]).strftime("%I:%M %p") for s in options
        )
        return {
            "messages": [AIMessage(content=f"I didn't quite catch a time. Here are some options on {target_date.strftime('%A, %d %B %Y')}: {times}. Which would you like?")],
            "active_agent": "booking_agent",
            "next_action": "end",
            "slot_fill_status": {**slot_status, "preferred_time": False},
            "entities": entities,
        }

    scheduled_at = datetime.fromisoformat(chosen_slot["starts_at"])

    async with get_session_context() as session:
        doctor_repo = DoctorRepository(session)
        doctor = await doctor_repo.get_by_id(doctor_id, load_department=True)

    doctor_name = doctor.full_name if doctor else f"Doctor #{doctor_id}"
    specialization_name = doctor.specialization if doctor else ""
    consultation_fee = float(doctor.consultation_fee) if doctor and doctor.consultation_fee is not None else None
    reason = entities.get("reason_for_visit") or entities.get("reason")

    pending_confirmation = {
        "action": "create_appointment",
        "summary": (
            f"Book {doctor_name} ({specialization_name}) on "
            f"{scheduled_at.strftime('%A, %d %B %Y at %I:%M %p')}"
        ),
        "params": {
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "scheduled_at": scheduled_at.isoformat(),
            "reason": reason,
            "notes": None,
        },
    }

    fallback_summary = _format_summary(
        doctor_name=doctor_name,
        specialization=specialization_name,
        scheduled_at=scheduled_at,
        consultation_fee=consultation_fee,
        reason=reason,
    )

    summary_text = fallback_summary
    try:
        settings = get_settings()
        llm = get_llm(LLMTier.CAPABLE)
        system_prompt = build_booking_prompt(settings.HOSPITAL_NAME)
        context = (
            "Present this booking summary to the patient and ask them to "
            f"confirm with yes or no:\n{fallback_summary}"
        )
        llm_messages: list[BaseMessage] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=context),
        ]
        response = await llm.ainvoke(llm_messages)
        response_text = response.content if isinstance(response.content, str) else str(response.content)
        if response_text.strip():
            summary_text = response_text
    except Exception as exc:
        logger.error(f"booking_agent: LLM summary generation failed, using template ({exc})")

    logger.info(f"booking_agent: session={session_id} pending_confirmation set for patient={patient_id}")

    return {
        "messages": [AIMessage(content=summary_text)],
        "active_agent": "booking_agent",
        "next_action": "end",
        "pending_confirmation": pending_confirmation,
        "slot_fill_status": slot_status,
        "entities": entities,
    }