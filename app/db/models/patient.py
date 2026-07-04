from __future__ import annotations
from datetime import date, datetime
from typing import Optional

from sqlalchemy import TEXT, Boolean, DateTime, Enum, String, event, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship
from app.db.base import Base
from app.logger import logging
from app.exception import CustomException


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String(20), primary_key = True)
    full_name: Mapped[str] = mapped_column(String(100), nullable = False)
    date_of_birth: Mapped[date] = mapped_column(nullable = False)
    gender: Mapped[str] = mapped_column(
        Enum("Male", "Female", "Other", name = "gender_enum"), nullable = False
    )
    blood_group: Mapped[Optional[str]] = mapped_column(String(5), nullable = True)
    phone: Mapped[str] = mapped_column(
        String(15), unique = True, nullable = False, index = True
    )
    email: Mapped[Optional[str]] = mapped_column(String(100), nullable = True)
    address: Mapped[Optional[str]] = mapped_column(TEXT, nullable = True)
    emergency_contact: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    insurance_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    insurance_provider: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    registration_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    
    medical_records = relationship(
        "MedicalRecord", back_populates="patient",lazy = "select", cascade="all, delete-orphan"
    )
    lab_results = relationship(
        "LabResult",
        back_populates="patient",
        lazy="select",
        cascade="all, delete-orphan"
    )
    prescriptions = relationship(
        "Prescription",
        back_populates="patient",
        lazy="select",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return (
            f"<Patient id={self.patient_id!r} name={self.full_name!r} "
            f"phone={self.phone!r} active={self.is_active}>"
        )


# Lifecycle event listeners – log patient changes & catch errors
@event.listens_for(Patient, "after_insert")
def _log_patient_insert(mapper, connection, target: Patient) -> None:
    try:
        logging.info("Patient created: id=%s, name=%s", target.patient_id, target.full_name)
    except Exception as exc:
        logging.exception("Logging failure during Patient insert event.")
        raise CustomException(
            error_message="Failed to process Patient insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Patient, "after_update")
def _log_patient_update(mapper, connection, target: Patient) -> None:
    try:
        logging.info("Patient updated: id=%s, name=%s", target.patient_id, target.full_name)
    except Exception as exc:
        logging.exception("Logging failure during Patient update event.")
        raise CustomException(
            error_message="Failed to process Patient update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Patient, "after_delete")
def _log_patient_delete(mapper, connection, target: Patient) -> None:
    try:
        logging.info("Patient deleted: id=%s, name=%s", target.patient_id, target.full_name)
    except Exception as exc:
        logging.exception("Logging failure during Patient delete event.")
        raise CustomException(
            error_message="Failed to process Patient delete event.",
            error_detail=str(exc),
        ) from exc