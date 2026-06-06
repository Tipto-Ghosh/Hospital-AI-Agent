"""
ORM model for the Appointment table.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DATETIME,TEXT,Boolean,DateTime,Enum,ForeignKey,Index,Integer,String,event,func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.logger import logging
from app.exception import CustomException

if TYPE_CHECKING:
    from app.db.models.doctor import Doctor
    from app.db.models.patient import Patient

APPOINTMENT_STATUSES = (
    "pending",
    "confirmed",
    "completed",
    "cancelled",
    "no_show",
)


class Appointment(Base):
    """
    Maps to the `appointments` table.

    Every booking, cancellation, and reschedule operation in the system
    ultimately writes to this table.  The Supervisor Agent checks
    appointment context here to resolve pronouns like "my appointment"
    or "the one I booked last week".
    """
    
    __tablename__ = "appointments"

    # Composite indexes (defined at table level for multi-column)
    __table_args__ = (
        Index("idx_doctor_datetime", "doctor_id", "scheduled_at"),
        Index("idx_patient_status", "patient_id", "status"),
    )

    # Primary key 
    appointment_id: Mapped[str] = mapped_column(
        String(20),
        primary_key = True,
        comment = "Application-generated ID"
    )

    # Foreign keys
    patient_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("patients.patient_id", ondelete = "RESTRICT"),
        nullable = False
    )
    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.doctor_id", ondelete = "RESTRICT"),
        nullable = False
    )

    # Scheduling 
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable = False,
        comment = "UTC datetime of the appointment slot.",
    )
    duration_min: Mapped[int] = mapped_column(
        Integer,
        default = 20,
        nullable = False,
        comment = "Appointment slot length in minutes.",
    )

    # Status 
    status: Mapped[str] = mapped_column(
        Enum(*APPOINTMENT_STATUSES, name = "appointment_status_enum"),
        nullable = False,
        default = "pending",
        index = True
    )

    # Clinical context
    reason_for_visit: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # Booking channel
    booked_via: Mapped[str] = mapped_column(
        Enum("ai_agent", "web", "phone", "walk_in", name="booking_channel_enum"),
        nullable=False,
        default="ai_agent",
    )

    # Timestamps 
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DATETIME,
        nullable=True,
        onupdate=func.now(),
        comment="Auto-updated by MySQL on every UPDATE.",
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # Relationships
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="appointments",
        lazy="select",
    )
    doctor: Mapped["Doctor"] = relationship(
        "Doctor",
        back_populates="appointments",
        lazy="select",
    )

    # Business logic helpers
    def is_cancellable(self) -> bool:
        """
        Returns True if the appointment can still be cancelled.

        Hospital policy: cancellations must be made at least 24 hours
        before the scheduled time.  This mirrors the guardrail configured
        in SecuritySettings.MIN_BOOKING_ADVANCE_HOURS.

        Usage in Cancellation Agent tool:
            appt = await session.get(Appointment, appt_id)
            if not appt.is_cancellable():
                return {"error": "Cannot cancel within 24 hours of appointment."}
        """
        if self.status in ("cancelled", "completed", "no_show"):
            return False
        now_utc = datetime.now(timezone.utc)
        scheduled = self.scheduled_at
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        hours_until = (scheduled - now_utc).total_seconds() / 3600
        return hours_until >= 24

    def is_upcoming(self) -> bool:
        """Returns True if the appointment is in the future and not cancelled."""
        if self.status in ("cancelled", "completed", "no_show"):
            return False
        now_utc = datetime.now(timezone.utc)
        scheduled = self.scheduled_at
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        return scheduled > now_utc

    def __repr__(self) -> str:
        return (
            f"<Appointment id={self.appointment_id!r} "
            f"patient={self.patient_id!r} doctor={self.doctor_id} "
            f"at={self.scheduled_at} status={self.status!r}>"
        )

# Lifecycle event listeners — log appointment changes & catch errors
@event.listens_for(Appointment, "after_insert")
def _log_appointment_insert(mapper, connection, target: Appointment) -> None:
    try:
        logging.info(
            "Appointment created: id=%s, patient=%s, doctor=%d, at=%s, status=%s",
            target.appointment_id,
            target.patient_id,
            target.doctor_id,
            target.scheduled_at,
            target.status,
        )
    except Exception as exc:
        logging.exception("Logging failure during Appointment insert event.")
        raise CustomException(
            error_message="Failed to process Appointment insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Appointment, "after_update")
def _log_appointment_update(mapper, connection, target: Appointment) -> None:
    try:
        logging.info(
            "Appointment updated: id=%s, patient=%s, doctor=%d, at=%s, status=%s",
            target.appointment_id,
            target.patient_id,
            target.doctor_id,
            target.scheduled_at,
            target.status,
        )
    except Exception as exc:
        logging.exception("Logging failure during Appointment update event.")
        raise CustomException(
            error_message="Failed to process Appointment update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Appointment, "after_delete")
def _log_appointment_delete(mapper, connection, target: Appointment) -> None:
    try:
        logging.info(
            "Appointment deleted: id=%s, patient=%s, doctor=%d, at=%s, status=%s",
            target.appointment_id,
            target.patient_id,
            target.doctor_id,
            target.scheduled_at,
            target.status,
        )
    except Exception as exc:
        logging.exception("Logging failure during Appointment delete event.")
        raise CustomException(
            error_message="Failed to process Appointment delete event.",
            error_detail=str(exc),
        ) from exc

def _patch_back_references() -> None:
    """
    Add appointments back-reference to Patient and Doctor.

    Called once at module load.  Safe to call multiple times (no-op if
    the attribute already exists).
    """
    try:
        from app.db.models.doctor import Doctor
        from app.db.models.patient import Patient

        if not hasattr(Patient, "appointments"):
            Patient.appointments = relationship(  
                "Appointment",
                back_populates="patient",
                lazy="select",
                cascade="all, delete-orphan",
            )

        if not hasattr(Doctor, "appointments"):
            Doctor.appointments = relationship(  
                "Appointment",
                back_populates="doctor",
                lazy="select",
            )

        logging.debug("Back-references patched onto Patient and Doctor successfully.")
    except Exception as exc:
        logging.exception("Failed to patch back-references onto Patient/Doctor.")
        raise CustomException(
            error_message="Failed to wire back-references for Appointment model.",
            error_detail=str(exc),
        ) from exc


_patch_back_references()