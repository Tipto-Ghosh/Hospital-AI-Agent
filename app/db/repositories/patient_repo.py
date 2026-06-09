"""
Repository layer for all patient identity operations.
 
Used by
- Supervisor Agent : get_by_phone() to resolve "my patient ID is..."
- Patient Records Agent: get_by_id(), verify_identity() before any PHI access
- Booking Agent : get_or_create_anonymous() for first-time callers
- Auth Agent : verify_identity() as the authentication gate
 
Security rules
- verify_identity() is the ONLY authentication path - agents must never
  bypass this to access PHI.
- get_or_create_anonymous() creates a minimal record with is_active=False
  and a generated patient_id so the system can track pre-registrations
  without exposing full records.
- All calls to methods that return PHI must be preceded by verify_identity().
  Enforcement is at the tool/agent layer; this repo does not enforce it.
- Patient IDs follow the format P-YYYY-NNNNN (e.g. P-2024-00042).
"""
from __future__ import annotations
from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logging
from app.exception import CustomException
from app.db.models.patient import Patient


async def _generate_patient_id(session: AsyncSession) -> str:
    """
    Generate the next sequential patient ID for the current year.
 
    Format: P-YYYY-NNNNN  (e.g. P-2024-00042)
 
    Queries the highest existing ID for the current year and increments
    by 1.  Safe within a single transaction (no race between flush and
    commit for normal single-user seed/registration scenarios.)
    """
    year = datetime.now(timezone.utc).year
    prefix = f"P-{year}-"
    result = await session.execute(
        select(Patient.patient_id)
        .where(Patient.patient_id.like(f"{prefix}%"))
        .order_by(Patient.patient_id.desc())
        .limit(1)
    )
    last_id: str | None = result.scalar_one_or_none()
    seq = int(last_id.split("-")[-1]) + 1 if last_id else 1
    return f"{prefix}{seq:05d}"


class PatientRepository:
    """
    All database operations for the patients table.
 
    Parameters:
    session: Active AsyncSession provided by the caller's get_session_context() or FastAPI Depends(get_db).
    """
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
 
    
    async def get_by_id(self, patient_id: str) -> Patient | None:
        """
        Fetch a patient by their primary key.
 
        Returns None if the patient does not exist or is_active = False.
        Agents that need to access deactivated records (admin use only)
        must use a raw session query directly - this method enforces
        the is_active filter as a safety default.
        """
        result = await self._s.execute(
            select(Patient).where(
                Patient.patient_id == patient_id,
                Patient.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()
 
    async def get_by_id_any_status(self, patient_id: str) -> Patient | None:
        """
        Fetch a patient regardless of is_active status.
        Used by admin endpoints only — agents must use get_by_id().
        """
        result = await self._s.execute(
            select(Patient).where(Patient.patient_id == patient_id)
        )
        return result.scalar_one_or_none()
 
    async def get_by_phone(self, phone: str) -> Patient | None:
        """
        Fetch an active patient by their phone number.
 
        Phone is a UNIQUE column — at most one row matches.
        Used by the Supervisor Agent to resolve patient identity from
        the phone number the caller provides before authentication.
 
        Returns None if no active patient has that phone number.
        """
        result = await self._s.execute(
            select(Patient).where(
                Patient.phone == phone,
                Patient.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()
 
    async def verify_identity(
        self,
        patient_id: str,
        dob: date,
        phone_last4: str,
    ) -> bool:
        """
        Multi-factor identity verification gate.
        Checks that the patient exists AND all three factors match:
          1. patient_id — what the patient claims their ID is
          2. dob — date of birth
          3. phone_last4  — last 4 digits of the registered phone
 
        Returns True only when all three factors match an active patient.
        Returns False for any mismatch — deliberately gives no detail
        about which factor failed (prevents enumeration attacks).
 
        This must be called before any PHI access in the Patient Records
        Agent or Billing Agent.
 
        Parameters
        patient_id: Patient PK string, e.g. 'P-2024-00001'.
        dob: date object — must exactly match date_of_birth.
        phone_last4: 4-digit string — matched against the last 4 characters of the stored phone number.
        """
        if len(phone_last4) != 4 or not phone_last4.isdigit():
            logging.warning(
                f"verify_identity called with invalid phone_last4={phone_last4}"
            )
            return False
 
        result = await self._s.execute(
            select(Patient).where(
                Patient.patient_id == patient_id,
                Patient.is_active.is_(True),
            )
        )
        patient: Patient | None = result.scalar_one_or_none()
 
        if patient is None:
            logging.debug(f"verify_identity: patient {patient_id} not found")
            return False
 
        dob_match   = patient.date_of_birth == dob
        phone_match = patient.phone.endswith(phone_last4)
 
        if not (dob_match and phone_match):
            logging.warning(
                f"verify_identity: factor mismatch for patient {patient_id} "
                f"(dob_ok={dob_match}, phone_ok={phone_match})"
            )
            return False
 
        logging.info("verify_identity: patient %r authenticated", patient_id)
        return True
 
    async def get_or_create_anonymous(
        self,
        phone: str,
        full_name: str = "Pre-registered Patient",
    ) -> tuple[Patient, bool]:
        """
        Return an existing patient by phone, or create a minimal pre-registration.
 
        Used by the Booking Agent when a caller has not yet registered but
        wants to book an appointment.  Creates a minimal Patient row with
        is_active=False so the system can associate a booking with the phone
        number without granting full record access.
 
        A hospital staff member later completes the registration
        (adding DOB, address, etc.) which sets is_active=True.
 
        Parameters
        phone: Phone number as provided by the caller.
        full_name: Optional name — defaults to a placeholder.
 
        Returns:
        (patient, created)
            patient : the Patient instance (existing or new)
            created : True if a new row was inserted, False if existing
        """
        # Check for existing patient with this phone (active or pre-registered)
        result = await self._s.execute(
            select(Patient).where(Patient.phone == phone)
        )
        existing: Patient | None = result.scalar_one_or_none()
        if existing:
            return existing, False
 
        # Generate a new ID and create a minimal record
        patient_id = await _generate_patient_id(self._s)
        new_patient = Patient(
            patient_id=patient_id,
            full_name=full_name,
            date_of_birth=date(1900, 1, 1), # placeholder — updated at registration
            gender="Other", # placeholder
            phone=phone,
            is_active=False,  # not fully registered yet
        )
        self._s.add(new_patient)
        await self._s.commit()
        await self._s.refresh(new_patient)
 
        logging.info(
            f"Pre-registration created: patient_id={patient_id} phone={phone}"
        )
        return new_patient, True