from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.memory import PatientLongTermContext
from app.logger import logging

logger = logging.getLogger(__name__)


async def load_patient_context(
    patient_id: str, 
    db: AsyncSession
) -> Optional[dict[str, Any]]:
    """
    Load a patient's long-term context row from MySQL.

    Returns a plain dict with the patient's stored preference signals,
    or None if no row exists yet for this patient.

    Parameters
    ----------
    patient_id: The patient's PK.
    db: An active AsyncSession.

    Returns
    -------
    A dict with keys: preferred_doctor (int|None), preferred_time_slot
    (str|None, one of "morning"/"afternoon"/"evening"/"any"),
    language_preference (str, e.g. "en"), communication_opt_in (bool),
    last_concern (str|None, non-clinical summary only).

    Returns None on a missing row OR on a database error — callers
    should treat both cases identically (no context available), so
    this function never raises.
    """
    try:
        result = await db.execute(
            select(PatientLongTermContext).where(
                PatientLongTermContext.patient_id == patient_id
            )
        )
        row = result.scalar_one_or_none()
    except Exception as exc:
        logger.error(f"load_patient_context: query failed for patient={patient_id}: {exc}")
        return None

    if row is None:
        logger.debug(f"load_patient_context: no context row for patient={patient_id}")
        return None

    logger.debug(f"load_patient_context: loaded context for patient={patient_id}")
    return {
        "preferred_doctor": row.preferred_doctor,
        "preferred_time_slot": row.preferred_time_slot,
        "language_preference": row.language_preference,
        "communication_opt_in": row.communication_opt_in,
        "last_concern": row.last_concern,
    }


async def update_patient_context(
    patient_id: str,
    updates: dict[str, Any],
    db: AsyncSession,
) -> bool:
    """
    Create or update a patient's long-term context row.

    Only the keys present in `updates` are changed - fields not
    included are left untouched (or, for a brand-new row, fall back to
    the model's defaults: language_preference="en",
    communication_opt_in=True).

    Parameters
    ----------
    patient_id   The patient's PK.
    
    updates: A dict of fields to set.
    db: An active AsyncSession.
    
    Returns
    -------
    True if the upsert succeeded, False if it failed. Never raises —
    a context update failure should never block the calling agent's
    response delivery.
    """
    recognized_keys = {
        "preferred_doctor",
        "preferred_time_slot",
        "language_preference",
        "communication_opt_in",
        "last_concern",
    }

    unrecognized = set(updates.keys()) - recognized_keys
    if unrecognized:
        logger.warning(
            f"update_patient_context: ignoring unrecognized keys {unrecognized} "
            f"for patient={patient_id}"
        )

    try:
        result = await db.execute(
            select(PatientLongTermContext).where(
                PatientLongTermContext.patient_id == patient_id
            )
        )
        row = result.scalar_one_or_none()

        if row is None:
            row = PatientLongTermContext(
                patient_id=patient_id,
                language_preference=updates.get("language_preference", "en"),
                communication_opt_in=updates.get("communication_opt_in", True),
            )
            db.add(row)

        if "preferred_doctor" in updates:
            row.preferred_doctor = updates["preferred_doctor"]
        if "preferred_time_slot" in updates:
            row.preferred_time_slot = updates["preferred_time_slot"]
        if "language_preference" in updates:
            row.language_preference = updates["language_preference"]
        if "communication_opt_in" in updates:
            row.communication_opt_in = updates["communication_opt_in"]
        if "last_concern" in updates:
            row.last_concern = updates["last_concern"]

        logger.debug(f"update_patient_context: upserted context for patient={patient_id}")
        return True

    except Exception as exc:
        logger.error(f"update_patient_context: upsert failed for patient={patient_id}: {exc}")
        return False