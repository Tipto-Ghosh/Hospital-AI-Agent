""" 
Slot filtering helper for appointment booking agent.

The booking flow requires four pieces of information before a
create_appointment call can be confirmed:
 
  - patient_identity: who is booking (phone, patient_id, or an already-authenticated session)
  - preferred_doctor: a doctor_id, doctor name, or specialization
  - preferred_date: the calendar date the patient wants
  - preferred_time: a specific time, or a time-of-day preference (morning / afternoon / evening)
 
These helpers are pure functions operating on state["entities"] and
state["slot_fill_status"] - they do not touch the database or the LLM.
booking_agent_node calls them on every turn to decide whether to ask a
follow-up question or proceed to availability checking.
"""
from __future__ import annotations
from typing import Optional
from app.agents.state import HospitalAgentState

REQUIRED_SLOTS: list[str] = [
    "patient_identity",
    "preferred_doctor",
    "preferred_date",
    "preferred_time",
]

# order in which slots are asked about, matching REQUIRED_SLOTS
SLOT_ORDER: list[str] = list(REQUIRED_SLOTS)

def check_slots(state: HospitalAgentState) -> dict[str, bool]:
    """
    Determine which required booking slots are currently filled.
 
    A slot is considered filled if state["entities"] (or, for
    patient_identity, state itself) contains a usable value for it.
 
    Parameters
    ----------
    state: The current HospitalAgentState.
 
    Returns
    -------
    A dict mapping each name in REQUIRED_SLOTS to True (filled) or
    False (missing). This is the value booking_agent_node stores in
    state["slot_fill_status"].
 
    Slot resolution rules
    ----------------------
    patient_identity
        Filled if state["patient_id"] is set (already authenticated),
        or entities contains "patient_id" or "phone"/"patient_phone".
 
    preferred_doctor
        Filled if entities contains "doctor_id", "doctor_name", or
        "specialization".
 
    preferred_date
        Filled if entities contains a non-empty "date".
 
    preferred_time
        Filled if entities contains a non-empty "time" (this includes
        time-of-day preferences like "morning" - resolving that to an
        actual slot happens later in booking_agent_node).
    """
    entities = state.get("entities", {})
 
    patient_identity_filled = bool(
        state.get("patient_id")
        or entities.get("patient_id")
        or entities.get("phone")
        or entities.get("patient_phone")
    )
 
    preferred_doctor_filled = bool(
        entities.get("doctor_id")
        or entities.get("doctor_name")
        or entities.get("specialization")
    )
 
    preferred_date_filled = bool(entities.get("date"))
 
    preferred_time_filled = bool(entities.get("time"))
 
    return {
        "patient_identity": patient_identity_filled,
        "preferred_doctor": preferred_doctor_filled,
        "preferred_date": preferred_date_filled,
        "preferred_time": preferred_time_filled,
    }
    
def get_next_missing_slot(slot_status: dict[str, bool]) -> Optional[str]:
    """
    Return the name of the first unfilled required slot, in SLOT_ORDER.
 
    Parameters
    ----------
    slot_status   The dict returned by check_slots().
 
    Returns
    -------
    The first slot name in SLOT_ORDER for which slot_status is False,
    or None if every required slot is filled.
    """
    for slot_name in SLOT_ORDER:
        if not slot_status.get(slot_name, False):
            return slot_name
    return None

def generate_slot_question(slot_name: str, entities: dict) -> str:
    """
    Generate a natural-language question for the given missing slot.
 
    Parameters
    ----------
    slot_name: One of REQUIRED_SLOTS - the slot to ask about.
    entities: state["entities"], used to personalise the question
            where helpful (e.g. mentioning a specialization already given).
 
    Returns
    -------
    A single, friendly question the booking agent can send to the
    patient as-is.
 
    Raises
    ------
    ValueError  if slot_name is not one of REQUIRED_SLOTS.
    """
    if slot_name == "patient_identity":
        return (
            "Could you share your patient ID or the phone number "
            "registered with us, so I can look up your account?"
        )
 
    if slot_name == "preferred_doctor":
        return (
            "Which doctor would you like to see, or what type of "
            "specialist are you looking for (for example, a "
            "cardiologist or a pediatrician)?"
        )
 
    if slot_name == "preferred_date":
        specialization = entities.get("specialization") or entities.get("doctor_name")
        if specialization:
            return f"What date would you like to see {specialization}?"
        return "What date would you like to come in for your appointment?"
 
    if slot_name == "preferred_time":
        date = entities.get("date")
        if date:
            return (
                f"What time on {date} works best for you? "
                "You can also just say morning, afternoon, or evening."
            )
        return (
            "What time works best for you? "
            "You can also just say morning, afternoon, or evening."
        )
 
    raise ValueError(f"Unknown slot_name: {slot_name!r}. Expected one of {REQUIRED_SLOTS}.")