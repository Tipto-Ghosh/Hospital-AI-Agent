from __future__ import annotations
import re 
from datetime import date 
from typing import Any, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from app.agents.state import HospitalAgentState
from app.db.base import get_session_context
from app.db.repositories.patient_repo import PatientRepository
from app.logger import logging

logger = logging.getLogger(__name__)

MAX_AUTH_ATTEMPTS = 2  # "allows 2 retries" -> 2 retries after the first attempt = 3 total

AUTH_SLOT_KEYS = {
    "patient_id": "auth_patient_id",
    "date_of_birth": "auth_dob",
    "phone_last4": "auth_phone_last4",
}
 
_PATIENT_ID_PATTERN = re.compile(r"P-\d{4}-\d{4,6}", re.IGNORECASE)
_DOB_ISO_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_PHONE_LAST4_PATTERN = re.compile(r"\b\d{4}\b")

def _latest_human_text(messages: list[BaseMessage]) -> str:
    """Return the content of the most recent HumanMessage, or ''."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""

def _try_extract_auth_fields(text: str, entities: dict[str, Any]) -> dict[str, Any]:
    """
    Attempt to extract patient_id, date_of_birth, and phone_last4 from
    free-text patient input using simple pattern matching.
 
    This is a lightweight, regex-based extractor - it does not call an
    LLM. It only fills in slots that are CURRENTLY MISSING from
    entities, so previously-confirmed values are never overwritten by
    a later, possibly-ambiguous message.
 
    Parameters
    ----------
    text: The latest human message.
    entities: state["entities"] (read-only here - the caller merges the returned dict).
 
    Returns
    -------
    A dict containing only the newly-extracted auth_* keys (possibly
    empty).
    """
    extracted: dict[str, Any] = {}
 
    if not entities.get(AUTH_SLOT_KEYS["patient_id"]):
        match = _PATIENT_ID_PATTERN.search(text)
        if match:
            extracted[AUTH_SLOT_KEYS["patient_id"]] = match.group(0).upper()
 
    if not entities.get(AUTH_SLOT_KEYS["date_of_birth"]):
        match = _DOB_ISO_PATTERN.search(text)
        if match:
            try:
                date.fromisoformat(match.group(0))
                extracted[AUTH_SLOT_KEYS["date_of_birth"]] = match.group(0)
            except ValueError:
                pass
 
    if not entities.get(AUTH_SLOT_KEYS["phone_last4"]):
        # Only look for a 4-digit number if a DOB-like date isn't what
        # we just matched - avoids accidentally grabbing part of a date.
        candidates = _PHONE_LAST4_PATTERN.findall(text)
        dob_value = entities.get(AUTH_SLOT_KEYS["date_of_birth"]) or extracted.get(AUTH_SLOT_KEYS["date_of_birth"])
        for candidate in candidates:
            if dob_value and candidate in dob_value:
                continue
            extracted[AUTH_SLOT_KEYS["phone_last4"]] = candidate
            break
 
    return extracted
 
 
def _next_missing_auth_slot(entities: dict[str, Any]) -> Optional[str]:
    """Return the name of the first missing auth_* slot, or None if all are present."""
    for slot_key in AUTH_SLOT_KEYS.values():
        if not entities.get(slot_key):
            return slot_key
    return None
 
 
def _question_for_slot(slot_key: str) -> str:
    """Return the question to ask for a given auth_* slot."""
    if slot_key == AUTH_SLOT_KEYS["patient_id"]:
        return "Could you tell me your patient ID? It looks like 'P-2024-00001'."
    if slot_key == AUTH_SLOT_KEYS["date_of_birth"]:
        return "And what is your date of birth? Please use the format YYYY-MM-DD, for example 1990-05-15."
    if slot_key == AUTH_SLOT_KEYS["phone_last4"]:
        return "Lastly, what are the last 4 digits of the phone number registered with us?"
    raise ValueError(f"Unknown auth slot: {slot_key!r}")
 
 
def _clear_auth_entities(entities: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of entities with all auth_* scratch keys removed."""
    cleaned = dict(entities)
    for key in (*AUTH_SLOT_KEYS.values(), "auth_attempts"):
        cleaned.pop(key, None)
    return cleaned
 
 
async def auth_agent_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The shared inline authentication flow graph node.
    Returns
    -------
    A partial state update dict.
    """
    session_id = state["session_id"]
    entities = dict(state.get("entities", {}))
 
    latest_text = _latest_human_text(state["messages"])
    extracted = _try_extract_auth_fields(latest_text, entities)
    entities.update(extracted)
 
    missing_slot = _next_missing_auth_slot(entities)
 
    if missing_slot:
        question = _question_for_slot(missing_slot)
        logger.info(f"auth_agent: session={session_id} missing slot={missing_slot}")
        return {
            "messages": [AIMessage(content=question)],
            "active_agent": "auth_agent",
            "next_action": "end",
            "entities": entities,
        }
 
    claimed_patient_id = entities[AUTH_SLOT_KEYS["patient_id"]]
    dob_str = entities[AUTH_SLOT_KEYS["date_of_birth"]]
    phone_last4 = entities[AUTH_SLOT_KEYS["phone_last4"]]
 
    try:
        parsed_dob = date.fromisoformat(dob_str)
    except ValueError:
        logger.warning(f"auth_agent: session={session_id} invalid dob format {dob_str!r}")
        entities.pop(AUTH_SLOT_KEYS["date_of_birth"], None)
        return {
            "messages": [AIMessage(content="That date doesn't look quite right. Could you give your date of birth in YYYY-MM-DD format, for example 1990-05-15?")],
            "active_agent": "auth_agent",
            "next_action": "end",
            "entities": entities,
        }
 
    async with get_session_context() as session:
        repo = PatientRepository(session)
        verified = await repo.verify_identity(claimed_patient_id, parsed_dob, phone_last4)
 
    if verified:
        logger.info(f"auth_agent: session={session_id} verification succeeded for patient={claimed_patient_id}")
        cleaned_entities = _clear_auth_entities(entities)
        return {
            "messages": [AIMessage(content="Thanks, your identity has been verified.")],
            "is_authenticated": True,
            "patient_id": claimed_patient_id,
            "active_agent": "auth_agent",
            "next_action": "supervisor",
            "entities": cleaned_entities,
        }
 
    attempts = int(entities.get("auth_attempts", 0)) + 1
    entities["auth_attempts"] = attempts
 
    if attempts > MAX_AUTH_ATTEMPTS:
        logger.warning(f"auth_agent: session={session_id} verification failed after {attempts} attempts, giving up")
        cleaned_entities = _clear_auth_entities(entities)
        return {
            "messages": [AIMessage(content="I'm sorry, I wasn't able to verify your identity. Authentication failed, please contact reception at 16700 for assistance.")],
            "active_agent": "auth_agent",
            "next_action": "end",
            "entities": cleaned_entities,
        }
 
    logger.info(f"auth_agent: session={session_id} verification failed, attempt {attempts}/{MAX_AUTH_ATTEMPTS + 1}")
    entities.pop(AUTH_SLOT_KEYS["phone_last4"], None)
    return {
        "messages": [AIMessage(content="I couldn't verify those details. Let's try again - what are the last 4 digits of your registered phone number?")],
        "active_agent": "auth_agent",
        "next_action": "end",
        "entities": entities,
    }