from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DATETIME,TEXT,Boolean,DateTime,Enum,ForeignKey,Index,Integer,String,event,func,Date
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.logger import logging
from app.exception import CustomException

if TYPE_CHECKING:
    from app.db.models.doctor import Doctor
    from app.db.models.patient import Patient

class MedicalRecord(Base):
    """
    Maps to the `medical_records` table.

    Created by a doctor after a patient visit.  Contains the clinical
    narrative: chief complaint, diagnosis, treatment plan, and follow-up.

    The LLM must never receive diagnosis or treatment_plan text directly
    the tool layer summarises these into safe natural-language phrases
    like "has a record of a cardiology visit on 2024-03-01".
    """

    __tablename__ = "medical_records"

    record_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    patient_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("patients.patient_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # appointment_id is nullable - records can exist without a linked appointment
    appointment_id: Mapped[Optional[str]] = mapped_column(
        String(20),
        ForeignKey("appointments.appointment_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.doctor_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    visit_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Clinical content (PHI - never surface to LLM raw)
    chief_complaint: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    diagnosis: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    treatment_plan: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    follow_up_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="medical_records",
        lazy="select",
    )
    doctor: Mapped["Doctor"] = relationship(
        "Doctor",
        back_populates="medical_records",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<MedicalRecord id={self.record_id} patient={self.patient_id!r} "
            f"doctor={self.doctor_id} date={self.visit_date}>"
        )


# LabResult
class LabResult(Base):
    """
    Maps to the `lab_results` table.

    Stores individual test results.  The is_abnormal flag is set by the
    lab system (or manually by a doctor) and drives alerts in the
    Patient Records Agent response ("⚠ 2 abnormal results found").

    The agent must flag any abnormal result to the patient and recommend
    contacting their doctor - it must never interpret the clinical
    significance of the result itself.
    """

    __tablename__ = "lab_results"

    result_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    patient_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("patients.patient_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    test_name: Mapped[str] = mapped_column(String(100), nullable=False)
    test_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Result data 
    result_value: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    reference_range: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Abnormal flag
    is_abnormal: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment=(
            "Set True if result falls outside the reference range. "
            "Agent must surface this to the patient with a 'consult your doctor' advisory."
        ),
    )

    # Ordering doctor (nullable - some labs are ordered externally)
    ordered_by_doctor: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("doctors.doctor_id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # Relationships 
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="lab_results",
        lazy="select",
    )

    def __repr__(self) -> str:
        abnormal_flag = " ⚠ABNORMAL" if self.is_abnormal else ""
        return (
            f"<LabResult id={self.result_id} patient={self.patient_id!r} "
            f"test={self.test_name!r} date={self.test_date}{abnormal_flag}>"
        )


# Prescription
class Prescription(Base):
    """
    Maps to the `prescriptions` table.

    Tracks medications prescribed to a patient.  The is_active flag
    distinguishes current medications from historical ones - agents
    use this when checking for drug interactions (only active
    prescriptions are checked by default).

    Hard guardrails for the Medication Information Agent:
    - Never suggest stopping an active prescription.
    - Never modify dosage or frequency fields.
    - Drug interaction checks are informational only - always direct
      to the prescribing doctor for any change.
    """

    __tablename__ = "prescriptions"

    prescription_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    patient_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("patients.patient_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.doctor_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    prescribed_date: Mapped[date] = mapped_column(Date, nullable=False)
    medication_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Dosage details
    dosage: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="e.g. '500mg'",
    )
    frequency: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="e.g. 'twice daily', 'every 8 hours'",
    )
    duration_days: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Intended course length in days. NULL means ongoing.",
    )

    #  Status 
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment=(
            "True = currently active prescription. "
            "Set False when discontinued or course completed - never delete."
        ),
    )
    notes: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # Relationships
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="prescriptions",
        lazy="select",
    )
    doctor: Mapped["Doctor"] = relationship(
        "Doctor",
        back_populates="prescriptions",
        lazy="select",
    )

    def __repr__(self) -> str:
        active_flag = "ACTIVE" if self.is_active else "inactive"
        return (
            f"<Prescription id={self.prescription_id} patient={self.patient_id!r} "
            f"drug={self.medication_name!r} [{active_flag}]>"
        )

# Lifecycle event listeners - log clinical record changes & catch errors

# MedicalRecord listeners 
@event.listens_for(MedicalRecord, "after_insert")
def _log_medical_record_insert(mapper, connection, target: MedicalRecord) -> None:
    try:
        logging.info(
            "MedicalRecord created: id=%d, patient=%s, doctor=%d, date=%s",
            target.record_id,
            target.patient_id,
            target.doctor_id,
            target.visit_date,
        )
    except Exception as exc:
        logging.exception("Logging failure during MedicalRecord insert event.")
        raise CustomException(
            error_message="Failed to process MedicalRecord insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(MedicalRecord, "after_update")
def _log_medical_record_update(mapper, connection, target: MedicalRecord) -> None:
    try:
        logging.info(
            "MedicalRecord updated: id=%d, patient=%s, doctor=%d, date=%s",
            target.record_id,
            target.patient_id,
            target.doctor_id,
            target.visit_date,
        )
    except Exception as exc:
        logging.exception("Logging failure during MedicalRecord update event.")
        raise CustomException(
            error_message="Failed to process MedicalRecord update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(MedicalRecord, "after_delete")
def _log_medical_record_delete(mapper, connection, target: MedicalRecord) -> None:
    try:
        logging.info(
            "MedicalRecord deleted: id=%d, patient=%s, doctor=%d, date=%s",
            target.record_id,
            target.patient_id,
            target.doctor_id,
            target.visit_date,
        )
    except Exception as exc:
        logging.exception("Logging failure during MedicalRecord delete event.")
        raise CustomException(
            error_message="Failed to process MedicalRecord delete event.",
            error_detail=str(exc),
        ) from exc


# LabResult listeners
@event.listens_for(LabResult, "after_insert")
def _log_lab_result_insert(mapper, connection, target: LabResult) -> None:
    try:
        logging.info(
            "LabResult created: id=%d, patient=%s, test=%s, date=%s, abnormal=%s",
            target.result_id,
            target.patient_id,
            target.test_name,
            target.test_date,
            target.is_abnormal,
        )
    except Exception as exc:
        logging.exception("Logging failure during LabResult insert event.")
        raise CustomException(
            error_message="Failed to process LabResult insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(LabResult, "after_update")
def _log_lab_result_update(mapper, connection, target: LabResult) -> None:
    try:
        logging.info(
            "LabResult updated: id=%d, patient=%s, test=%s, date=%s, abnormal=%s",
            target.result_id,
            target.patient_id,
            target.test_name,
            target.test_date,
            target.is_abnormal,
        )
    except Exception as exc:
        logging.exception("Logging failure during LabResult update event.")
        raise CustomException(
            error_message="Failed to process LabResult update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(LabResult, "after_delete")
def _log_lab_result_delete(mapper, connection, target: LabResult) -> None:
    try:
        logging.info(
            "LabResult deleted: id=%d, patient=%s, test=%s, date=%s, abnormal=%s",
            target.result_id,
            target.patient_id,
            target.test_name,
            target.test_date,
            target.is_abnormal,
        )
    except Exception as exc:
        logging.exception("Logging failure during LabResult delete event.")
        raise CustomException(
            error_message="Failed to process LabResult delete event.",
            error_detail=str(exc),
        ) from exc


# Prescription listeners
@event.listens_for(Prescription, "after_insert")
def _log_prescription_insert(mapper, connection, target: Prescription) -> None:
    try:
        logging.info(
            "Prescription created: id=%d, patient=%s, drug=%s, date=%s, active=%s",
            target.prescription_id,
            target.patient_id,
            target.medication_name,
            target.prescribed_date,
            target.is_active,
        )
    except Exception as exc:
        logging.exception("Logging failure during Prescription insert event.")
        raise CustomException(
            error_message="Failed to process Prescription insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Prescription, "after_update")
def _log_prescription_update(mapper, connection, target: Prescription) -> None:
    try:
        logging.info(
            "Prescription updated: id=%d, patient=%s, drug=%s, date=%s, active=%s",
            target.prescription_id,
            target.patient_id,
            target.medication_name,
            target.prescribed_date,
            target.is_active,
        )
    except Exception as exc:
        logging.exception("Logging failure during Prescription update event.")
        raise CustomException(
            error_message="Failed to process Prescription update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Prescription, "after_delete")
def _log_prescription_delete(mapper, connection, target: Prescription) -> None:
    try:
        logging.info(
            "Prescription deleted: id=%d, patient=%s, drug=%s, date=%s, active=%s",
            target.prescription_id,
            target.patient_id,
            target.medication_name,
            target.prescribed_date,
            target.is_active,
        )
    except Exception as exc:
        logging.exception("Logging failure during Prescription delete event.")
        raise CustomException(
            error_message="Failed to process Prescription delete event.",
            error_detail=str(exc),
        ) from exc


# Wire back-references onto Patient and Doctor
def _patch_back_references() -> None:
    """
    Add medical_records, lab_results, and prescriptions back-references
    to Patient and Doctor once all three models are defined.
    """
    try:
        from app.db.models.doctor import Doctor
        from app.db.models.patient import Patient

        # Patient.medical_records
        if not hasattr(Patient, "medical_records"):
            Patient.medical_records = relationship(  # type: ignore[attr-defined]
                "MedicalRecord",
                back_populates="patient",
                lazy="select",
                cascade="all, delete-orphan",
            )

        # Patient.lab_results
        if not hasattr(Patient, "lab_results"):
            Patient.lab_results = relationship(  # type: ignore[attr-defined]
                "LabResult",
                back_populates="patient",
                lazy="select",
                cascade="all, delete-orphan",
            )

        # Patient.prescriptions
        if not hasattr(Patient, "prescriptions"):
            Patient.prescriptions = relationship(  # type: ignore[attr-defined]
                "Prescription",
                back_populates="patient",
                lazy="select",
                cascade="all, delete-orphan",
            )

        # Doctor.medical_records
        if not hasattr(Doctor, "medical_records"):
            Doctor.medical_records = relationship(  # type: ignore[attr-defined]
                "MedicalRecord",
                back_populates="doctor",
                lazy="select",
            )

        # Doctor.prescriptions
        if not hasattr(Doctor, "prescriptions"):
            Doctor.prescriptions = relationship(  # type: ignore[attr-defined]
                "Prescription",
                back_populates="doctor",
                lazy="select",
            )

        logging.debug("Clinical back-references patched onto Patient and Doctor successfully.")
    except Exception as exc:
        logging.exception("Failed to patch clinical back-references onto Patient/Doctor.")
        raise CustomException(
            error_message="Failed to wire clinical back-references for medical models.",
            error_detail=str(exc),
        ) from exc


_patch_back_references()