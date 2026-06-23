"""
The canonical @tool implementations for billing and insurance queries.
 
Take patient_id (where relevant) as an explicit argument
rather than relying on a ContextVar, and return Pydantic model
instances.
Every read here also writes an audit_log entry for the patient-specific
lookups (get_outstanding_bills, get_invoice_details) - billing data is
PHI-adjacent and access should be traceable. check_insurance_coverage
and get_payment_methods are general, non-patient-specific information
and are not audited.
"""

from __future__ import annotations
 
from datetime import date
from typing import Optional
 
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import select
 
from app.db.base import get_session_context
from app.db.models.medication import HospitalInfo
from app.db.repositories.audit_repo import AuditRepository
from app.db.repositories.billing_repo import BillingRepository
from app.logger import logging
 
logger = logging.getLogger(__name__)

class OutstandingInvoice(BaseModel):
    """A single outstanding (unpaid or paritially paid) invoice for a patient."""
    invoice_id: str
    total_amount: float
    amount_due: float
    status: str
    due_date: Optional[date] = None
    
class OutstandingBillsResult(BaseModel):
    """A patient's outstanding bills, with a running total.""" 
    invoices: list[OutstandingInvoice] = Field(default_factory=list)
    total_outstanding: float = 0.0
    
class InvoiceLineItem(BaseModel):
    """A single line item on an invoice."""
    description: str
    quantity: float
    unit_price: int
    total_price: float

class InvoiceDetailResult(BaseModel):
    """Itemized detail for a single invoice."""
 
    found: bool
    invoice_id: Optional[str] = None
    total_amount: Optional[float] = None
    paid_amount: Optional[float] = None
    amount_due: Optional[float] = None
    status: Optional[str] = None
    items: list[InvoiceLineItem] = Field(default_factory=list)
 
 
class InsuranceCoverageResult(BaseModel):
    """General insurance acceptance/coverage information."""
 
    accepted_providers_info: Optional[str] = None
    matches_query: bool = False
 
 
class PaymentMethodsResult(BaseModel):
    """Accepted payment methods information."""
 
    content: Optional[str] = None
    

@tool
async def get_outstanding_bills(patient_id: str) -> OutstandingBillsResult:
    """
    Get a patient's outstanding (unpaid or partially paid) invoices.
 
    Parameters
    ----------
    patient_id   The authenticated patient's PK.
 
    Returns
    -------
    OutstandingBillsResult with an empty invoices list and
    total_outstanding=0.0 if nothing is owed.
    """
    async with get_session_context() as session:
        repo = BillingRepository(session)
        invoices = await repo.get_outstanding_bills(patient_id)
        total = await repo.get_total_outstanding(patient_id)
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="billing_tools",
            action="read_outstanding_bills",
            patient_id=patient_id,
            resource_type="billing_invoice",
            payload_summary=f"Read {len(invoices)} outstanding invoice(s).",
        )
 
    entries = [
        OutstandingInvoice(
            invoice_id=inv.invoice_id,
            total_amount=float(inv.total_amount),
            amount_due=float(inv.amount_due()),
            status=inv.status,
            due_date=inv.due_date,
        )
        for inv in invoices
    ]
 
    logger.info(f"get_outstanding_bills(patient_id={patient_id}) -> {len(entries)} invoice(s)")
    return OutstandingBillsResult(invoices=entries, total_outstanding=float(total))


@tool
async def get_invoice_details(patient_id: str, invoice_id: str) -> InvoiceDetailResult:
    """
    Get itemized details for a specific invoice, scoped to the
    requesting patient.
 
    Parameters
    ----------
    patient_id   The authenticated patient's PK - used to verify
                 ownership of the invoice.
    invoice_id   The invoice PK, e.g. "INV-20241101-0001".
 
    Returns
    -------
    InvoiceDetailResult with found=false if the invoice doesn't exist
    or doesn't belong to patient_id.
    """
    async with get_session_context() as session:
        repo = BillingRepository(session)
        invoice = await repo.get_invoice_detail(invoice_id)
 
        if invoice is None or invoice.patient_id != patient_id:
            logger.info(f"get_invoice_details(invoice_id={invoice_id}, patient_id={patient_id}) -> not found / not owned")
            return InvoiceDetailResult(found=False)
 
        items = [
            InvoiceLineItem(
                description=item.description,
                quantity=item.quantity,
                unit_price=float(item.unit_price),
                total_price=float(item.total_price),
            )
            for item in invoice.items
        ]
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="billing_tools",
            action="read_invoice_details",
            patient_id=patient_id,
            resource_type="billing_invoice",
            resource_id=invoice_id,
            payload_summary=f"Read invoice details for {invoice_id}.",
        )
 
    logger.info(f"get_invoice_details(invoice_id={invoice_id}) -> {len(items)} item(s)")
    return InvoiceDetailResult(
        found=True,
        invoice_id=invoice.invoice_id,
        total_amount=float(invoice.total_amount),
        paid_amount=float(invoice.paid_amount),
        amount_due=float(invoice.amount_due()),
        status=invoice.status,
        items=items,
    )


@tool
async def check_insurance_coverage(insurance_provider: Optional[str] = None) -> InsuranceCoverageResult:
    """
    Check whether an insurance provider is accepted, and general
    coverage information. Does not require authentication.
 
    Parameters
    ----------
    insurance_provider   Name of the insurance provider, e.g. "Green
                          Delta Insurance". Leave as None to just
                          retrieve the general accepted-providers
                          information.
 
    Returns
    -------
    InsuranceCoverageResult. accepted_providers_info is None if no
    hospital_info row is on file for insurance.
    """
    async with get_session_context() as session:
        result = await session.execute(
            select(HospitalInfo).where(
                HospitalInfo.category == "service",
                HospitalInfo.topic.ilike("%insurance%"),
            )
        )
        row = result.scalars().first()
 
    if row is None:
        logger.info("check_insurance_coverage -> no hospital_info row found")
        return InsuranceCoverageResult(accepted_providers_info=None, matches_query=False)
 
    matches = True
    if insurance_provider:
        matches = insurance_provider.lower() in row.content.lower()
 
    logger.info(f"check_insurance_coverage(provider={insurance_provider!r}) -> matches={matches}")
    return InsuranceCoverageResult(accepted_providers_info=row.content, matches_query=matches)
 
 
@tool
async def get_payment_methods() -> PaymentMethodsResult:
    """
    List accepted payment methods. Does not require authentication.
 
    Returns
    -------
    PaymentMethodsResult with content=None if no hospital_info row is
    on file for payment methods.
    """
    async with get_session_context() as session:
        result = await session.execute(
            select(HospitalInfo).where(
                HospitalInfo.category == "service",
                HospitalInfo.topic.ilike("%payment%"),
            )
        )
        row = result.scalars().first()
 
    logger.info(f"get_payment_methods() -> {'found' if row else 'not found'}")
    return PaymentMethodsResult(content=row.content if row else None)
 
billing_tools = [
    get_outstanding_bills,
    get_invoice_details,
    check_insurance_coverage,
    get_payment_methods,
]