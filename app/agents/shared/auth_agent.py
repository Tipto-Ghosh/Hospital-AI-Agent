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

OTP_TTL_SECONDS = 5 * 60  # 5 minutes
OTP_LENGTH = 6  # 6-digit numeric OTP

AUTH_SLOT_KEYS = {
    "patient_id": "auth_patient_id",
    "date_of_birth": "auth_dob",
    "phone_last4": "auth_phone_last4",
}

OTP_VERIFIED_FLAG = "auth_otp_verified"
OTP_PHONE_KEY = "auth_otp_phone"
 
_PATIENT_ID_PATTERN = re.compile(r"P-\d{4}-\d{4,6}", re.IGNORECASE)
_DOB_ISO_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_PHONE_LAST4_PATTERN = re.compile(r"\b\d{4}\b")
_OTP_PATTERN = re.compile(r"\b\d{6}\b")

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
 
def _generate_otp() -> str:
    """Generate a random numeric OTP of length OTP_LENGTH."""
    from random import randint
    return f"{randint(0, 10**OTP_LENGTH - 1):0{OTP_LENGTH}d}"

def _otp_redis_key(patient_id: str)->str:
    """Return the Redis key for storing the OTP for a given patient_id."""
    return f"otp:{patient_id}"

async def _send_otp_sms(phone_number: str, otp: str) -> None:
    """
    Dispatch the OTP SMS via the Celery task tasks.send_otp_sms().
 
    Fire-and-forget: the Celery worker handles actual delivery and
    retries. If the task module isn't available yet (Phase 7 has not
    been built), this logs a warning and continues - the OTP is still
    generated and stored in Redis, so the flow remains testable end to
    end even before the SMS provider integration exists.
 
    Never raises - a notification dispatch failure must never block
    the authentication flow itself.
    """
    try:
        from app.notifications.tasks import send_otp_sms
        send_otp_sms.delay(phone_number, otp)
        logger.info(f"_send_otp_sms: OTP dispatch queued for phone ending in {phone_number[-4:]}")
    except ImportError:
        logger.warning(f"_send_otp_sms: Celery task module not available, OTP dispatch skipped for phone ending in {phone_number[-4:]}")
    except Exception as e:
        logger.error(f"_send_otp_sms: Failed to dispatch OTP SMS for phone ending in {phone_number[-4:]}: {e}")
        
async def _get_redis():
    from app.api.dependencies import get_redis_pool
    return await get_redis_pool()

async def auth_agent_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The shared inline authentication flow graph node.
    """
    session_id = state["session_id"]
    entities = dict(state.get("entities", {}))
 
    latest_text = _latest_human_text(state["messages"])
 
    if entities.get(OTP_VERIFIED_FLAG) == "pending":
        claimed_patient_id = entities[AUTH_SLOT_KEYS["patient_id"]]
 
        otp_match = _OTP_PATTERN.search(latest_text)
 
        redis = await _get_redis()
        redis_key = _otp_redis_key(claimed_patient_id)
 
        try:
            stored_otp = await redis.get(redis_key)
        except Exception as exc:
            logger.error(f"auth_agent: Redis OTP lookup failed for session={session_id}: {exc}")
            stored_otp = None
 
        if stored_otp is not None and isinstance(stored_otp, bytes):
            stored_otp = stored_otp.decode("utf-8")
 
        if otp_match and stored_otp is not None and otp_match.group(0) == stored_otp:
            logger.info(f"auth_agent: OTP verified for session={session_id} patient={claimed_patient_id}")
            try:
                await redis.delete(redis_key)
            except Exception as exc:
                logger.warning(f"auth_agent: failed to delete consumed OTP key for {claimed_patient_id}: {exc}")
 
            cleaned_entities = _clear_auth_entities(entities)
            return {
                "messages": [AIMessage(content="Thanks, your identity has been verified.")],
                "is_authenticated": True,
                "patient_id": claimed_patient_id,
                "active_agent": "auth_agent",
                "next_action": "supervisor",
                "entities": cleaned_entities,
            }
 
        if stored_otp is None:
            logger.info(f"auth_agent: OTP expired for session={session_id} patient={claimed_patient_id}, resending")
            phone = entities.get(OTP_PHONE_KEY)
            new_otp = _generate_otp()
            try:
                await redis.setex(redis_key, OTP_TTL_SECONDS, new_otp)
            except Exception as exc:
                logger.error(f"auth_agent: failed to store refreshed OTP for {claimed_patient_id}: {exc}")
 
            if phone:
                await _send_otp_sms(phone, new_otp)
 
            return {
                "messages": [AIMessage(content="That verification code has expired. I've sent you a new one - please enter the 6-digit code.")],
                "active_agent": "auth_agent",
                "next_action": "end",
                "entities": entities,
            }
 
        otp_attempts = int(entities.get("otp_attempts", 0)) + 1
        entities["otp_attempts"] = otp_attempts
 
        if otp_attempts > MAX_AUTH_ATTEMPTS:
            logger.warning(f"auth_agent: OTP verification failed after {otp_attempts} attempts for session={session_id}")
            try:
                await redis.delete(redis_key)
            except Exception:
                pass
            cleaned_entities = _clear_auth_entities(entities)
            return {
                "messages": [AIMessage(content="I'm sorry, I wasn't able to verify that code. Authentication failed, please contact reception at 16700 for assistance.")],
                "active_agent": "auth_agent",
                "next_action": "end",
                "entities": cleaned_entities,
            }
 
        logger.info(f"auth_agent: OTP mismatch, attempt {otp_attempts}/{MAX_AUTH_ATTEMPTS + 1} for session={session_id}")
        return {
            "messages": [AIMessage(content="That code doesn't match. Please double-check the 6-digit code we sent you and try again.")],
            "active_agent": "auth_agent",
            "next_action": "end",
            "entities": entities,
        }
 
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
        patient = await repo.get_by_id(claimed_patient_id) if verified else None
 
    if not verified:
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
 
    logger.info(f"auth_agent: session={session_id} Stage 1 verified for patient={claimed_patient_id}, issuing OTP")
 
    if patient is None:
        logger.error(f"auth_agent: verify_identity() succeeded but get_by_id() returned None for {claimed_patient_id}")
        cleaned_entities = _clear_auth_entities(entities)
        return {
            "messages": [AIMessage(content="Something went wrong verifying your account. Please contact reception at 16700 for assistance.")],
            "active_agent": "auth_agent",
            "next_action": "end",
            "entities": cleaned_entities,
        }
 
    otp = _generate_otp()
    redis = await _get_redis()
    redis_key = _otp_redis_key(claimed_patient_id)
 
    try:
        await redis.setex(redis_key, OTP_TTL_SECONDS, otp)
    except Exception as exc:
        logger.error(f"auth_agent: failed to store OTP in Redis for {claimed_patient_id}: {exc}")
        cleaned_entities = _clear_auth_entities(entities)
        return {
            "messages": [AIMessage(content="Something went wrong starting verification. Please try again shortly.")],
            "active_agent": "auth_agent",
            "next_action": "end",
            "entities": cleaned_entities,
        }
 
    await _send_otp_sms(patient.phone, otp)
 
    entities[OTP_VERIFIED_FLAG] = "pending"
    entities[OTP_PHONE_KEY] = patient.phone
    entities.pop("auth_attempts", None)
 
    masked_phone = f"***-***-{patient.phone[-4:]}" if len(patient.phone) >= 4 else "your registered number"
 
    return {
        "messages": [AIMessage(content=f"Thanks, I've found your account. I've sent a 6-digit verification code by SMS to {masked_phone}. Please enter the code to finish verifying your identity.")],
        "active_agent": "auth_agent",
        "next_action": "end",
        "entities": entities,
    }