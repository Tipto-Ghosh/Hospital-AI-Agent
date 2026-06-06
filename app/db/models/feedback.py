"""
ORM models for patient feedback and complaint management.
"""
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import TEXT,CheckConstraint,DateTime,Enum,ForeignKey,Index,Integer,SmallInteger,String,event,func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.logger import logging
from app.exception import CustomException

if TYPE_CHECKING:
    from app.db.models.patient import Patient


FEEDBACK_CATEGORIES = (
    "general",
    "doctor",
    "billing",
    "facilities",
    "staff",
    "ai_agent",
)

TICKET_STATUSES = ("open", "in_review", "resolved", "escalated")
TICKET_PRIORITIES = ("low", "medium", "high", "critical")


class Feedback(Base):
    """
    Maps to the `feedback` table.

    Lightweight, one-shot feedback record — no lifecycle, no follow-up
    required.  Patients may submit anonymously (patient_id=NULL).

    Rating scale: 1 (very poor) -> 5 (excellent).
    The CHECK constraint is enforced at DB level for data integrity.

    Agent behaviour
    ---------------
    - Agent acknowledges receipt and thanks the patient.
    - Agent does NOT promise any action on general feedback.
    - For negative ratings (1–2) the agent offers to open a formal
      ComplaintTicket instead.
    - For ai_agent category, the row is flagged for internal review
      by the hospital AI operations team.
    """

    __tablename__ = "feedback"

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_feedback_rating"),
        Index("idx_feedback_patient", "patient_id"),
        Index("idx_feedback_category", "category"),
    )

    feedback_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    patient_id: Mapped[Optional[str]] = mapped_column(
        String(20),
        ForeignKey("patients.patient_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    category: Mapped[str] = mapped_column(
        Enum(*FEEDBACK_CATEGORIES, name="feedback_category_enum"),
        nullable=False,
        index=True,
    )
    message: Mapped[str] = mapped_column(
        TEXT,
        nullable=False,
        comment="Free-text feedback from the patient.",
    )
    rating: Mapped[Optional[int]] = mapped_column(
        SmallInteger,
        nullable=True,
        comment="Optional 1–5 star rating. Enforced by CHECK constraint.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    patient: Mapped[Optional["Patient"]] = relationship(
        "Patient",
        back_populates="feedback",
        lazy="select",
    )

    def __repr__(self) -> str:
        stars = f" ★{self.rating}" if self.rating else ""
        return (
            f"<Feedback id={self.feedback_id} "
            f"category={self.category!r}{stars} "
            f"patient={self.patient_id!r}>"
        )


class ComplaintTicket(Base):
    """
    Maps to the `complaint_tickets` table.

    Structured complaint lifecycle — opened by the agent, resolved by
    hospital staff via the admin dashboard.

    Status lifecycle
    ----------------
    open -> in_review -> resolved
        |-> escalated  (at any point via escalate_to_manager)

    Priority escalation
    -------------------
    The agent can call escalate_to_manager() which sets:
        status   = 'escalated'
        priority = 'critical'
    This flags the ticket for immediate attention in the admin dashboard.

    The agent NEVER resolves a ticket — resolution is exclusively done
    by hospital staff.  The agent can only report the current status.
    """

    __tablename__ = "complaint_tickets"

    __table_args__ = (
        Index("idx_ticket_patient", "patient_id"),
        Index("idx_ticket_status_priority", "status", "priority"),
    )

    ticket_id: Mapped[str] = mapped_column(
        String(20),
        primary_key=True,
        comment="Application-generated ID, e.g. TKT-20241101-0001",
    )

    patient_id: Mapped[Optional[str]] = mapped_column(
        String(20),
        ForeignKey("patients.patient_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    department: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Hospital department the complaint is directed at.",
    )
    description: Mapped[str] = mapped_column(
        TEXT,
        nullable=False,
        comment="Full complaint description as submitted by the patient.",
    )

    status: Mapped[str] = mapped_column(
        Enum(*TICKET_STATUSES, name="ticket_status_enum"),
        nullable=False,
        default="open",
        index=True,
    )
    priority: Mapped[str] = mapped_column(
        Enum(*TICKET_PRIORITIES, name="ticket_priority_enum"),
        nullable=False,
        default="medium",
        index=True,
    )

    assigned_to: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Name/ID of the staff member handling this ticket.",
    )
    resolution_note: Mapped[Optional[str]] = mapped_column(
        TEXT,
        nullable=True,
        comment="Set by staff on resolution. Never modified by the AI agent.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="Set by staff when status transitions to 'resolved'.",
    )

    @property
    def is_open(self) -> bool:
        """True if the ticket still requires action."""
        return self.status in ("open", "in_review", "escalated")

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"

    def __repr__(self) -> str:
        return (
            f"<ComplaintTicket id={self.ticket_id!r} "
            f"status={self.status!r} priority={self.priority!r} "
            f"patient={self.patient_id!r}>"
        )


# Lifecycle event listeners — log feedback/ticket changes & catch errors
@event.listens_for(Feedback, "after_insert")
def _log_feedback_insert(mapper, connection, target: Feedback) -> None:
    try:
        logging.info(
            "Feedback created: id=%d, category=%s, rating=%s, patient=%s",
            target.feedback_id,
            target.category,
            target.rating,
            target.patient_id,
        )
    except Exception as exc:
        logging.exception("Logging failure during Feedback insert event.")
        raise CustomException(
            error_message="Failed to process Feedback insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Feedback, "after_update")
def _log_feedback_update(mapper, connection, target: Feedback) -> None:
    try:
        logging.info(
            "Feedback updated: id=%d, category=%s, rating=%s, patient=%s",
            target.feedback_id,
            target.category,
            target.rating,
            target.patient_id,
        )
    except Exception as exc:
        logging.exception("Logging failure during Feedback update event.")
        raise CustomException(
            error_message="Failed to process Feedback update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Feedback, "after_delete")
def _log_feedback_delete(mapper, connection, target: Feedback) -> None:
    try:
        logging.info(
            "Feedback deleted: id=%d, category=%s, patient=%s",
            target.feedback_id,
            target.category,
            target.patient_id,
        )
    except Exception as exc:
        logging.exception("Logging failure during Feedback delete event.")
        raise CustomException(
            error_message="Failed to process Feedback delete event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(ComplaintTicket, "after_insert")
def _log_complaint_ticket_insert(mapper, connection, target: ComplaintTicket) -> None:
    try:
        logging.info(
            "ComplaintTicket created: id=%s, status=%s, priority=%s, patient=%s",
            target.ticket_id,
            target.status,
            target.priority,
            target.patient_id,
        )
    except Exception as exc:
        logging.exception("Logging failure during ComplaintTicket insert event.")
        raise CustomException(
            error_message="Failed to process ComplaintTicket insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(ComplaintTicket, "after_update")
def _log_complaint_ticket_update(mapper, connection, target: ComplaintTicket) -> None:
    try:
        logging.info(
            "ComplaintTicket updated: id=%s, status=%s, priority=%s, patient=%s",
            target.ticket_id,
            target.status,
            target.priority,
            target.patient_id,
        )
    except Exception as exc:
        logging.exception("Logging failure during ComplaintTicket update event.")
        raise CustomException(
            error_message="Failed to process ComplaintTicket update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(ComplaintTicket, "after_delete")
def _log_complaint_ticket_delete(mapper, connection, target: ComplaintTicket) -> None:
    try:
        logging.info(
            "ComplaintTicket deleted: id=%s, status=%s, patient=%s",
            target.ticket_id,
            target.status,
            target.patient_id,
        )
    except Exception as exc:
        logging.exception("Logging failure during ComplaintTicket delete event.")
        raise CustomException(
            error_message="Failed to process ComplaintTicket delete event.",
            error_detail=str(exc),
        ) from exc

# Wire back-references onto Patient
def _patch_back_references() -> None:
    """Add feedback back-reference to Patient."""
    try:
        from app.db.models.patient import Patient

        if not hasattr(Patient, "feedback"):
            Patient.feedback = relationship(  # type: ignore[attr-defined]
                "Feedback",
                back_populates="patient",
                lazy="select",
                cascade="all, delete-orphan",
            )
        logging.debug("Feedback back-reference patched onto Patient successfully.")
    except Exception as exc:
        logging.exception("Failed to patch feedback back-reference onto Patient.")
        raise CustomException(
            error_message="Failed to wire feedback back-reference for Patient.",
            error_detail=str(exc),
        ) from exc


_patch_back_references()