"""
The canonical tool implementation for patient record access.
"""

from __future__ import annotations
 
from datetime import date
from typing import Optional
 
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import select
 
from app.db.base import get_session_context
from app.db.models.doctor import Doctor
from app.db.models.medical_record import LabResult, MedicalRecord, Prescription
from app.db.models.patient import Patient
from app.db.repositories.audit_repo import AuditRepository
from app.db.repositories.patient_repo import PatientRepository
from app.logger import logging
 
logger = logging.getLogger(__name__)

class AuthenticationResult(BaseModel):
    """
    Result of patient authentication.
    """
    verified: bool = Field(description="True if all three identity factors match, False otherwise.")
    patient_id: str = Field(description="The patient ID that was checked (not necessarily verified).")
    
class PatientProfile(BaseModel):
    """A patient's demographic and contact profile."""
 
    found: bool
    patient_id: Optional[str] = None
    full_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    insurance_provider: Optional[str] = None
    
class MedicalHistoryEntry(BaseModel):
    """A single past visit summary (no raw clinical narrative fields)."""
 
    visit_date: date
    doctor_name: str
    specialization: Optional[str] = None
    follow_up_date: Optional[date] = None
    
class MedicalHistoryResult(BaseModel):
    """List of medical history entries for a patient."""
    records: list[MedicalHistoryEntry] = Field(default_factory=list)

class LabResultEntry(BaseModel):
    """A single lab result entry."""
    test_name: str
    test_date: date
    result_value: Optional[str] = None
    unit: Optional[str] = None
    reference_range: Optional[str] = None
    is_abnormal: bool 

class LabResultsResult(BaseModel):
    """List of lab results for a patient.""" 
    results: list[LabResultEntry] = Field(default_factory=list)

class PrescriptionEntry(BaseModel):
    """A single prescription record."""
 
    medication_name: str
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    prescribed_date: date
    duration_days: Optional[int] = None
    is_active: bool
    doctor_name: str
    
class PrescriptionsResult(BaseModel):
    """List of prescriptions for a patient."""
    prescriptions: list[PrescriptionEntry] = Field(default_factory=list)
    
@tool
async def authenticate_patient(patient_id: str, date_of_birth: str, phone_last4: str) -> AuthenticationResult:
    """
    Verify a patient's identity using three factors: patient ID, date
    of birth, and the last 4 digits of their registered phone number.
 
    Parameters
    ----------
    patient_id      Patient PK as claimed, e.g. "P-2024-00001".
    date_of_birth   ISO date string, e.g. "1990-05-15".
    phone_last4     Last 4 digits of the registered phone number.
 
    Returns
    -------
    AuthenticationResult. Gives no detail about which factor failed -
    only verified=true/false.
    """
    parsed_dob = date.fromisoformat(date_of_birth)
 
    async with get_session_context() as session:
        repo = PatientRepository(session)
        verified = await repo.verify_identity(patient_id, parsed_dob, phone_last4)
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="patient_record_tools",
            action="authenticate_patient",
            patient_id=patient_id,
            resource_type="patient",
            payload_summary=f"Identity verification {'succeeded' if verified else 'failed'}.",
        )
 
    logger.info(f"authenticate_patient(patient_id={patient_id}) -> verified={verified}")
    return AuthenticationResult(verified=verified, patient_id=patient_id)

@tool
async def get_patient_profile(patient_id: str) -> PatientProfile:
    """
    Get a patient's demographic and contact profile.
 
    Parameters
    ----------
    patient_id   The authenticated patient's PK.
 
    Returns
    -------
    PatientProfile with found=false if no matching patient exists.
    """
    async with get_session_context() as session:
        result = await session.execute(select(Patient).where(Patient.patient_id == patient_id))
        patient = result.scalar_one_or_none()
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="patient_record_tools",
            action="read_patient_profile",
            patient_id=patient_id,
            resource_type="patient_profile",
            payload_summary="Read patient profile.",
        )
 
    if patient is None:
        logger.info(f"get_patient_profile(patient_id={patient_id}) -> not found")
        return PatientProfile(found=False)
 
    logger.info(f"get_patient_profile(patient_id={patient_id}) -> found")
    return PatientProfile(
        found=True,
        patient_id=patient.patient_id,
        full_name=patient.full_name,
        date_of_birth=patient.date_of_birth,
        gender=patient.gender,
        blood_group=patient.blood_group,
        phone=patient.phone,
        email=patient.email,
        insurance_provider=patient.insurance_provider,
    )

@tool
async def get_medical_history(patient_id: str, limit: int = 10) -> MedicalHistoryResult:
    """
    Get a patient's medical visit history (summaries only - visit
    date and doctor seen, not raw diagnosis/treatment text).
 
    Parameters
    ----------
    patient_id   The authenticated patient's PK.
    limit        Maximum number of records to return (most recent
                 first). Default 10.
 
    Returns
    -------
    MedicalHistoryResult with an empty records list if none are on file.
    """
    async with get_session_context() as session:
        result = await session.execute(
            select(MedicalRecord)
            .where(MedicalRecord.patient_id == patient_id)
            .order_by(MedicalRecord.visit_date.desc())
            .limit(limit)
        )
        records = result.scalars().all()
 
        entries: list[MedicalHistoryEntry] = []
        for r in records:
            doctor_row = await session.execute(select(Doctor).where(Doctor.doctor_id == r.doctor_id))
            doctor = doctor_row.scalar_one_or_none()
            entries.append(MedicalHistoryEntry(
                visit_date=r.visit_date,
                doctor_name=doctor.full_name if doctor else f"Doctor #{r.doctor_id}",
                specialization=doctor.specialization if doctor else None,
                follow_up_date=r.follow_up_date,
            ))
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="patient_record_tools",
            action="read_medical_history",
            patient_id=patient_id,
            resource_type="medical_records",
            payload_summary=f"Read {len(entries)} medical history record(s).",
        )
 
    logger.info(f"get_medical_history(patient_id={patient_id}) -> {len(entries)} record(s)")
    return MedicalHistoryResult(records=entries)

@tool
async def get_lab_results(patient_id: str, test_name: Optional[str] = None, limit: int = 10) -> LabResultsResult:
    """
    Get a patient's lab results.
 
    Parameters
    ----------
    patient_id   The authenticated patient's PK.
    test_name    Optional partial, case-insensitive match on test name
                 (e.g. "glucose"). Leave as None to return all tests.
    limit        Maximum number of results to return (most recent
                 first). Default 10.
 
    Returns
    -------
    LabResultsResult with an empty results list if none are on file.
    Any entry with is_abnormal=true should be highlighted to the
    patient by the calling agent.
    """
    async with get_session_context() as session:
        stmt = select(LabResult).where(LabResult.patient_id == patient_id)
        if test_name:
            stmt = stmt.where(LabResult.test_name.ilike(f"%{test_name}%"))
        stmt = stmt.order_by(LabResult.test_date.desc()).limit(limit)
 
        result = await session.execute(stmt)
        rows = result.scalars().all()
 
        entries = [
            LabResultEntry(
                test_name=r.test_name,
                test_date=r.test_date,
                result_value=r.result_value,
                unit=r.unit,
                reference_range=r.reference_range,
                is_abnormal=r.is_abnormal,
            )
            for r in rows
        ]
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="patient_record_tools",
            action="read_lab_results",
            patient_id=patient_id,
            resource_type="lab_results",
            payload_summary=f"Read {len(entries)} lab result(s).",
        )
 
    abnormal_count = sum(1 for e in entries if e.is_abnormal)
    logger.info(f"get_lab_results(patient_id={patient_id}) -> {len(entries)} result(s), {abnormal_count} abnormal")
    return LabResultsResult(results=entries)


@tool
async def get_prescriptions(patient_id: str, active_only: bool = True) -> PrescriptionsResult:
    """
    Get a patient's prescriptions.
 
    Parameters
    ----------
    patient_id    The authenticated patient's PK.
    active_only   If True (default), return only currently active
                  prescriptions. If False, include discontinued/
                  completed prescriptions too.
 
    Returns
    -------
    PrescriptionsResult with an empty prescriptions list if none are
    on file.
    """
    async with get_session_context() as session:
        stmt = select(Prescription).where(Prescription.patient_id == patient_id)
        if active_only:
            stmt = stmt.where(Prescription.is_active.is_(True))
        stmt = stmt.order_by(Prescription.prescribed_date.desc())
 
        result = await session.execute(stmt)
        rows = result.scalars().all()
 
        entries: list[PrescriptionEntry] = []
        for r in rows:
            doctor_row = await session.execute(select(Doctor).where(Doctor.doctor_id == r.doctor_id))
            doctor = doctor_row.scalar_one_or_none()
            entries.append(PrescriptionEntry(
                medication_name=r.medication_name,
                dosage=r.dosage,
                frequency=r.frequency,
                prescribed_date=r.prescribed_date,
                duration_days=r.duration_days,
                is_active=r.is_active,
                doctor_name=doctor.full_name if doctor else f"Doctor #{r.doctor_id}",
            ))
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="patient_record_tools",
            action="read_prescriptions",
            patient_id=patient_id,
            resource_type="prescriptions",
            payload_summary=f"Read {len(entries)} prescription(s).",
        )
 
    logger.info(f"get_prescriptions(patient_id={patient_id}, active_only={active_only}) -> {len(entries)} result(s)")
    return PrescriptionsResult(prescriptions=entries)

patient_record_tools = [
    authenticate_patient,
    get_patient_profile,
    get_medical_history,
    get_lab_results,
    get_prescriptions,
]