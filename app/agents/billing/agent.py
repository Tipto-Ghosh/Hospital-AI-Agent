"""
The Billing & Insurance Agent node and its tools.
 
Authentication:
Looking up a specific patient's bills (get_outstanding_bills,
get_invoice_details, request_receipt) requires
state["is_authenticated"]. General insurance/payment-method questions
(check_insurance_coverage, get_payment_methods) do not.
 
billing_agent_node binds ALL FIVE tools regardless of authentication
status - the patient-specific tools simply return
{"authenticated": false} if called without an authenticated session,
and the system prompt instructs the LLM to ask the patient to verify
their identity in that case rather than presenting an error to them
directly.
 
Payments
---------
This agent NEVER processes payments. request_receipt only queues a
receipt email - it does not take any payment information, and the
system prompt explicitly forbids collecting card/bank details.
"""

from __future__ import annotations
import json
from typing import Any 
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from sqlalchemy import select

from app.agents.billing.prompts import build_billing_prompt
from app.agents.state import HospitalAgentState
from app.config import get_settings
from app.db.base import get_session_context
from app.db.models.medication import HospitalInfo
from app.db.repositories.audit_repo import AuditRepository
from app.db.repositories.billing_repo import BillingRepository
from app.llm.factory import LLMTier, get_llm
from app.logger import logging
 
logger = logging.getLogger(__name__)

"""
Set by billing_agent_node before invoking the LLM, read by the patient-specific tools
bellow. 
"""
from contextvars import ContextVar
_current_billing_context: ContextVar[tuple[str, str | None, bool] | None] = ContextVar(
    "_current_billing_context", default=None
)


@tool
async def get_outstanding_bills() -> str:
    """
    Get the authenticated patient's outstanding (unpaid or partially
    paid) invoices.
 
    Returns
    -------
    A JSON string. If not authenticated:
    {"authenticated": false}. Otherwise:
    {"authenticated": true, "invoices": [{"invoice_id": str,
    "total_amount": float, "amount_due": float, "status": str,
    "due_date": str|null}, ...], "total_outstanding": float}.
    Returns an empty invoices list if nothing is outstanding.
    """
    ctx = _current_billing_context.get()
    if ctx is None or not ctx[2]:
        return json.dumps({"authenticated": False})
 
    session_id, patient_id, _ = ctx
 
    async with get_session_context() as session:
        repo = BillingRepository(session)
        invoices = await repo.get_outstanding_bills(patient_id)
        total = await repo.get_total_outstanding(patient_id)
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="billing_agent",
            action="read_outstanding_bills",
            session_id=session_id,
            patient_id=patient_id,
            resource_type="billing_invoice",
            payload_summary=f"Read {len(invoices)} outstanding invoice(s).",
        )
 
    invoices_out = [
        {
            "invoice_id": inv.invoice_id,
            "total_amount": float(inv.total_amount),
            "amount_due": float(inv.amount_due()),
            "status": inv.status,
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
        }
        for inv in invoices
    ]
 
    logger.info(f"get_outstanding_bills(patient_id={patient_id}) -> {len(invoices_out)} invoice(s)")
    return json.dumps({
        "authenticated": True,
        "invoices": invoices_out,
        "total_outstanding": float(total),
    })


@tool
async def get_invoice_details(invoice_id: str) -> str:
    """
    Get itemized details for a specific invoice belonging to the
    authenticated patient.
 
    Parameters
    ----------
    invoice_id   The invoice PK, e.g. "INV-20241101-0001".
 
    Returns
    -------
    A JSON string. If not authenticated: {"authenticated": false}.
    If the invoice doesn't exist or doesn't belong to this patient:
    {"authenticated": true, "found": false}. Otherwise:
    {"authenticated": true, "found": true, "invoice_id": str,
    "total_amount": float, "paid_amount": float, "amount_due": float,
    "status": str, "items": [{"description": str, "quantity": int,
    "unit_price": float, "total_price": float}, ...]}.
    """
    ctx = _current_billing_context.get()
    if ctx is None or not ctx[2]:
        return json.dumps({"authenticated": False})
 
    session_id, patient_id, _ = ctx
 
    async with get_session_context() as session:
        repo = BillingRepository(session)
        invoice = await repo.get_invoice_detail(invoice_id)
 
        if invoice is None or invoice.patient_id != patient_id:
            logger.info(f"get_invoice_details(invoice_id={invoice_id}, patient_id={patient_id}) -> not found / not owned")
            return json.dumps({"authenticated": True, "found": False})
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="billing_agent",
            action="read_invoice_details",
            session_id=session_id,
            patient_id=patient_id,
            resource_type="billing_invoice",
            resource_id=invoice_id,
            payload_summary=f"Read invoice details for {invoice_id}.",
        )
 
        items_out = [
            {
                "description": item.description,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "total_price": float(item.total_price),
            }
            for item in invoice.items
        ]
 
    logger.info(f"get_invoice_details(invoice_id={invoice_id}) -> {len(items_out)} item(s)")
    return json.dumps({
        "authenticated": True,
        "found": True,
        "invoice_id": invoice.invoice_id,
        "total_amount": float(invoice.total_amount),
        "paid_amount": float(invoice.paid_amount),
        "amount_due": float(invoice.amount_due()),
        "status": invoice.status,
        "items": items_out,
    })


@tool
async def check_insurance_coverage(insurance_provider: str = "", service_type: str = "") -> str:
    """
    Check whether an insurance provider is accepted, and general
    coverage information.
 
    Does NOT require authentication.
 
    Parameters
    ----------
    insurance_provider: Name of the insurance provider, e.g. "Green Delta Insurance". Leave empty to list all accepted providers.
    service_type: Optional service type to ask about coverage for, e.g. "consultation". Currently informational only - matched against hospital_info content.
 
    Returns
    -------
    A JSON string: {"accepted_providers_info": str|null,
    "matches_query": bool}. accepted_providers_info contains the
    hospital's accepted-insurance content if found, else null.
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
        return json.dumps({"accepted_providers_info": None, "matches_query": False})
 
    matches = True
    if insurance_provider:
        matches = insurance_provider.lower() in row.content.lower()
 
    logger.info(f"check_insurance_coverage(provider={insurance_provider!r}) -> matches={matches}")
    return json.dumps({"accepted_providers_info": row.content, "matches_query": matches})


@tool
async def get_payment_methods() -> str:
    """
    List accepted payment methods.
 
    Does NOT require authentication.
 
    Returns
    -------
    A JSON string: {"content": str|null}. content contains the
    hospital's payment-methods information if found on file, else null.
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
    return json.dumps({"content": row.content if row else None})


@tool
async def request_receipt(invoice_id: str, patient_contact: str) -> str:
    """
    Request that a receipt for an invoice be emailed to the patient.
 
    Requires authentication. This is an informational request only - no
    payment is processed. Actual email delivery is implemented via
    Celery in Phase 7; this logs the request so the flow can be
    exercised end-to-end before Celery is wired up.
 
    Parameters
    ----------
    invoice_id        The invoice PK, e.g. "INV-20241101-0001".
    patient_contact   Email address or phone number to send the
                       receipt to.
 
    Returns
    -------
    A JSON string. If not authenticated: {"authenticated": false}.
    Otherwise: {"authenticated": true, "queued": true,
    "invoice_id": str, "contact": str}.
    """
    ctx = _current_billing_context.get()
    if ctx is None or not ctx[2]:
        return json.dumps({"authenticated": False})
 
    session_id, patient_id, _ = ctx
 
    async with get_session_context() as session:
        repo = BillingRepository(session)
        invoice = await repo.get_invoice_detail(invoice_id)
 
        if invoice is None or invoice.patient_id != patient_id:
            return json.dumps({"authenticated": True, "queued": False, "error": "Invoice not found."})
 
        audit_repo = AuditRepository(session)
        await audit_repo.log(
            agent_name="billing_agent",
            action="request_receipt",
            session_id=session_id,
            patient_id=patient_id,
            resource_type="billing_invoice",
            resource_id=invoice_id,
            payload_summary=f"Receipt requested for {invoice_id}.",
        )
 
    logger.info(f"request_receipt (stub): invoice_id={invoice_id} contact={patient_contact}")
    return json.dumps({"authenticated": True, "queued": True, "invoice_id": invoice_id, "contact": patient_contact})
 
 
billing_tools = [
    get_outstanding_bills,
    check_insurance_coverage,
    get_payment_methods,
    get_invoice_details,
    request_receipt,
]
billing_tool_node = ToolNode(billing_tools)
 

async def billing_agent_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Billing & Insurance Agent graph node.
 
    Flow
    ----
    1. Set the billing context ContextVar with
       (session_id, patient_id, is_authenticated) so the
       patient-specific tools above can check authentication and scope
       their queries.
    2. Call the CAPABLE-tier LLM with all five tools bound, passing the
       billing system prompt plus conversation history. The prompt
       instructs the LLM to ask for identity verification if a
       patient-specific tool returns {"authenticated": false}.
    3. If the response contains tool calls, append it and set
       next_action="billing_tools" so billing_tool_node executes them
       - the graph routes back to this node for a final answer.
    4. Otherwise the response is final - append it and set
       next_action="end".
 
    The ContextVar is always reset in a finally block, even on error.
 
    Returns
    -------
    A partial state update dict.
    """
    session_id = state["session_id"]
    patient_id = state.get("patient_id")
    is_authenticated = state.get("is_authenticated", False)
 
    token = _current_billing_context.set((session_id, patient_id, is_authenticated))
 
    try:
        settings = get_settings()
        system_prompt = build_billing_prompt(settings.HOSPITAL_NAME)
 
        llm = get_llm(LLMTier.CAPABLE).bind_tools(billing_tools)
        llm_messages: list[BaseMessage] = [SystemMessage(content=system_prompt), *state["messages"]]
 
        try:
            response: AIMessage = await llm.ainvoke(llm_messages)
        except Exception as exc:
            logger.error(f"billing_agent LLM call failed for session={session_id}: {exc}")
            return {
                "messages": [AIMessage(content="I'm having trouble accessing billing information right now. Please try again shortly, or contact the billing desk at Ext. 104.")],
                "active_agent": "billing_agent",
                "next_action": "end",
                "error": "Billing agent LLM call failed.",
            }
 
        has_tool_calls = bool(getattr(response, "tool_calls", None))
        next_action = "billing_tools" if has_tool_calls else "end"
 
        logger.info(
            f"billing_agent responded for session={session_id} patient={patient_id or 'anonymous'} "
            f"(tool_calls={len(response.tool_calls) if has_tool_calls else 0})"
        )
 
        return {
            "messages": [response],
            "active_agent": "billing_agent",
            "next_action": next_action,
        }
    finally:
        _current_billing_context.reset(token)