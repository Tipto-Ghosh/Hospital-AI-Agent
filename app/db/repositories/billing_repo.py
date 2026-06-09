"""
Repository layer for billing and invoice data.

Used by:
- Billing & Insurance Agent: all methods

Scope:
Read only from the agent perspective.This repository exposes no write
methods — invoices are created and updated by the hospital's internal
billing system, not by the AI agent.

The Billing Agent answers patient queries like:
  "How much do I owe?" -> get_outstanding_bills()
  "What was I charged for last visit?" -> get_invoice_detail()

PHI rules:
Invoice data is not directly PHI but does reveal visit history.
verify_identity() in PatientRepository must be called before invoking
any method that takes a patient_id.  Enforcement is at the tool layer.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.billing import BillingInvoice, InvoiceItem
from app.logger import logging

class BillingRepository:
    """
    Read-only access to billing_invoices and invoice_items.

    Parameters:
    session: Active AsyncSession.
    """
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_outstanding_bills(
        self,
        patient_id: str,
    ) -> list[BillingInvoice]:
        """
        Return all unpaid or partially-paid invoices for a patient.

        An 'outstanding' bill is any invoice with status in
        ('unpaid', 'partial') — paid and waived invoices are excluded.

        The Billing Agent formats these as a natural-language summary,
        e.g. "You have 2 outstanding invoices totalling ৳ 4,200."

        Parameters:
        patient_id: Patient PK — caller must have verified identity first.

        Returns:
        List of BillingInvoice ordered by created_at descending
        (most recent first).  Each invoice's .amount_due() helper gives
        the remaining balance.
        """
        result = await self._s.execute(
            select(BillingInvoice)
            .where(
                and_(
                    BillingInvoice.patient_id == patient_id,
                    BillingInvoice.status.in_(["unpaid", "partial"]),
                )
            )
            .order_by(BillingInvoice.created_at.desc())
        )
        invoices = list(result.scalars().all())
        logging.debug(
            f"get_outstanding_bills: patient= {patient_id} -> {len(invoices)} outstanding"
        )
        return invoices

    async def get_all_bills(
        self,
        patient_id: str,
        limit: int = 10,
    ) -> list[BillingInvoice]:
        """
        Return all invoices for a patient regardless of status.

        Used when a patient asks for their full billing history.

        Parameters:
        patient_id: Patient PK.
        limit: Maximum rows (default 10, most-recent first).
        """
        result = await self._s.execute(
            select(BillingInvoice)
            .where(BillingInvoice.patient_id == patient_id)
            .order_by(BillingInvoice.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_invoice_detail(
        self,
        invoice_id: str,
    ) -> BillingInvoice | None:
        """
        Fetch a single invoice with all its line items eagerly loaded.
        Used when the patient asks "what exactly was I charged for?".
        The Billing Agent renders the items list as a human-readable
        breakdown, e.g.:

            Invoice INV-20241101-0001
            ─────────────────────────────────────
            Cardiology Consultation  × 1   ৳  800
            HbA1c Lab Test           × 1   ৳  350
            ─────────────────────────────────────
            Total                          ৳ 1,150
            Paid                           ৳   800
            Outstanding                    ৳   350

        Parameters
        ----------
        invoice_id      Invoice PK string, e.g. 'INV-20241101-0001'.

        Returns None if the invoice does not exist.
        """
        result = await self._s.execute(
            select(BillingInvoice)
            .where(BillingInvoice.invoice_id == invoice_id)
            .options(selectinload(BillingInvoice.items))
        )
        invoice = result.scalar_one_or_none()
        if invoice:
            logging.debug(
                "get_invoice_detail: %r → %d line items",
                invoice_id, len(invoice.items),
            )
        return invoice

    async def get_total_outstanding(self, patient_id: str) -> Decimal:
        """
        Return the sum of amount_due() across all outstanding invoices.

        Convenience helper for the Billing Agent's one-line answer:
        "Your total outstanding balance is ৳ 4,200."
        """
        invoices = await self.get_outstanding_bills(patient_id)
        return sum((inv.amount_due() for inv in invoices), Decimal("0.00"))