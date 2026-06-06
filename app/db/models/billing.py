"""
ORM models for the financial layer of the hospital system.
"""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import TEXT,DateTime,Enum,ForeignKey,Index,Integer,Numeric,String,event,func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.logger import logging
from app.exception import CustomException

if TYPE_CHECKING:
    from app.db.models.appointment import Appointment
    from app.db.models.patient import Patient

# Invoice status values — used in ENUM column and in agent response logic
INVOICE_STATUSES = ("unpaid", "partial", "paid", "waived")

class BillingInvoice(Base):
    """
    Maps to the `billing_invoices` table.

    One invoice is created per visit/service episode.  It may cover
    a single appointment or a bundle (e.g. admission + labs + pharmacy).

    The Billing Agent uses amount_due() to tell the patient their
    outstanding balance without exposing raw numeric fields to the LLM.

    Design rules
    ------------
    - paid_amount is always <= total_amount (enforced by billing system).
    - Soft status transitions: unpaid -> partial -> paid (or waived).
    - Invoices are never deleted — only voided via status change.
    - appointment_id is nullable: invoices can exist for non-appointment
      charges (e.g. emergency walk-ins billed retroactively).
    """

    __tablename__ = "billing_invoices"

    __table_args__ = (
        Index("idx_invoice_patient_status", "patient_id", "status"),
    )

    # Primary key
    invoice_id: Mapped[str] = mapped_column(
        String(20),
        primary_key=True,
        comment="Application-generated ID, e.g. INV-20241101-0001",
    )

    # Foreign keys 
    patient_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("patients.patient_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    appointment_id: Mapped[Optional[str]] = mapped_column(
        String(20),
        ForeignKey("appointments.appointment_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Amounts
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Gross invoice total including all line items.",
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        comment="Amount already paid. paid_amount <= total_amount always.",
    )

    # Status 
    status: Mapped[str] = mapped_column(
        Enum(*INVOICE_STATUSES, name="invoice_status_enum"),
        nullable=False,
        default="unpaid",
        index=True,
    )

    # Due date
    due_date: Mapped[Optional[date]] = mapped_column(nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="billing_invoices",
        lazy="select",
    )
    appointment: Mapped[Optional["Appointment"]] = relationship(
        "Appointment",
        lazy="select",
        foreign_keys=[appointment_id],
    )
    items: Mapped[List["InvoiceItem"]] = relationship(
        "InvoiceItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="InvoiceItem.item_id",
    )

    # Business logic helpers
    def amount_due(self) -> Decimal:
        """
        Returns the outstanding balance.

        Used by the Billing Agent to answer "how much do I owe?" without
        sending raw total_amount and paid_amount values to the LLM.
        The agent receives a single formatted string: e.g. "৳ 3,200.00".
        """
        return self.total_amount - self.paid_amount

    def is_settled(self) -> bool:
        """True if the invoice requires no further payment."""
        return self.status in ("paid", "waived")

    def __repr__(self) -> str:
        return (
            f"<BillingInvoice id={self.invoice_id!r} patient={self.patient_id!r} "
            f"total={self.total_amount} paid={self.paid_amount} "
            f"due={self.amount_due()} status={self.status!r}>"
        )

# InvoiceItem
class InvoiceItem(Base):
    """
    Maps to the `invoice_items` table.

    Each row is one chargeable line item on a billing invoice.
    Examples:
        - "Cardiology Consultation"  qty=1  unit_price=800.00
        - "HbA1c Lab Test"           qty=1  unit_price=350.00
        - "Metformin 500mg x30"      qty=2  unit_price=120.00

    The Billing Agent uses these rows to render an itemised breakdown
    when a patient asks "what exactly am I being charged for?".
    """

    __tablename__ = "invoice_items"

    item_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    invoice_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("billing_invoices.invoice_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Number of units billed.",
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Price per unit before quantity multiplication.",
    )
    total_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Should equal quantity × unit_price. Stored explicitly for audit.",
    )

    # Relationship
    invoice: Mapped["BillingInvoice"] = relationship(
        "BillingInvoice",
        back_populates="items",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<InvoiceItem id={self.item_id} invoice={self.invoice_id!r} "
            f"desc={self.description!r} qty={self.quantity} "
            f"unit={self.unit_price} total={self.total_price}>"
        )

# Lifecycle event listeners — log billing changes & catch errors

# BillingInvoice listeners 
@event.listens_for(BillingInvoice, "after_insert")
def _log_invoice_insert(mapper, connection, target: BillingInvoice) -> None:
    try:
        logging.info(
            "BillingInvoice created: id=%s, patient=%s, total=%s, status=%s",
            target.invoice_id,
            target.patient_id,
            target.total_amount,
            target.status,
        )
    except Exception as exc:
        logging.exception("Logging failure during BillingInvoice insert event.")
        raise CustomException(
            error_message="Failed to process BillingInvoice insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(BillingInvoice, "after_update")
def _log_invoice_update(mapper, connection, target: BillingInvoice) -> None:
    try:
        logging.info(
            "BillingInvoice updated: id=%s, patient=%s, total=%s, status=%s",
            target.invoice_id,
            target.patient_id,
            target.total_amount,
            target.status,
        )
    except Exception as exc:
        logging.exception("Logging failure during BillingInvoice update event.")
        raise CustomException(
            error_message="Failed to process BillingInvoice update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(BillingInvoice, "after_delete")
def _log_invoice_delete(mapper, connection, target: BillingInvoice) -> None:
    try:
        logging.info(
            "BillingInvoice deleted: id=%s, patient=%s, total=%s, status=%s",
            target.invoice_id,
            target.patient_id,
            target.total_amount,
            target.status,
        )
    except Exception as exc:
        logging.exception("Logging failure during BillingInvoice delete event.")
        raise CustomException(
            error_message="Failed to process BillingInvoice delete event.",
            error_detail=str(exc),
        ) from exc


# InvoiceItem listeners
@event.listens_for(InvoiceItem, "after_insert")
def _log_invoice_item_insert(mapper, connection, target: InvoiceItem) -> None:
    try:
        logging.info(
            "InvoiceItem created: id=%d, invoice=%s, desc=%s, total=%s",
            target.item_id,
            target.invoice_id,
            target.description,
            target.total_price,
        )
    except Exception as exc:
        logging.exception("Logging failure during InvoiceItem insert event.")
        raise CustomException(
            error_message="Failed to process InvoiceItem insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(InvoiceItem, "after_update")
def _log_invoice_item_update(mapper, connection, target: InvoiceItem) -> None:
    try:
        logging.info(
            "InvoiceItem updated: id=%d, invoice=%s, desc=%s, total=%s",
            target.item_id,
            target.invoice_id,
            target.description,
            target.total_price,
        )
    except Exception as exc:
        logging.exception("Logging failure during InvoiceItem update event.")
        raise CustomException(
            error_message="Failed to process InvoiceItem update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(InvoiceItem, "after_delete")
def _log_invoice_item_delete(mapper, connection, target: InvoiceItem) -> None:
    try:
        logging.info(
            "InvoiceItem deleted: id=%d, invoice=%s, desc=%s, total=%s",
            target.item_id,
            target.invoice_id,
            target.description,
            target.total_price,
        )
    except Exception as exc:
        logging.exception("Logging failure during InvoiceItem delete event.")
        raise CustomException(
            error_message="Failed to process InvoiceItem delete event.",
            error_detail=str(exc),
        ) from exc

# Wire back-reference onto Patient
def _patch_back_references() -> None:
    """Add billing_invoices back-reference to Patient."""
    try:
        from app.db.models.patient import Patient

        if not hasattr(Patient, "billing_invoices"):
            Patient.billing_invoices = relationship(  # type: ignore[attr-defined]
                "BillingInvoice",
                back_populates="patient",
                lazy="select",
                cascade="all, delete-orphan",
            )

        logging.debug("Billing back-reference patched onto Patient successfully.")
    except Exception as exc:
        logging.exception("Failed to patch billing back-reference onto Patient.")
        raise CustomException(
            error_message="Failed to wire billing back-reference for Patient.",
            error_detail=str(exc),
        ) from exc


_patch_back_references()