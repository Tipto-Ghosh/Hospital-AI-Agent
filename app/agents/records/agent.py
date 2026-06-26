import functools
import json
from contextvars import ContextVar
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from sqlalchemy import select

from app.agents.records.prompts import build_records_prompt
from app.agents.state import HospitalAgentState
from app.config import get_settings
from app.db.base import get_session_context
from app.db.models.appointment import Appointment
from app.db.models.doctor import Doctor
from app.db.models.medical_record import LabResult, MedicalRecord, Prescription
from app.db.models.patient import Patient
from app.db.repositories.audit_repo import AuditRepository
from app.llm.factory import LLMTier, get_llm
from app.logger import logging

logger = logging.getLogger(__name__)


_current_patient_context: ContextVar[Optional[tuple[str, str]]] = ContextVar(
    "_current_patient_context", default = None
)


def audited(action: str, resource_type: str):
    """
    Decorator that writes an audit_log entry after a records tool runs.

    If no patient context is set (e.g. in a unit test calling the tool
    directly), the audit log is skipped with a debug log rather than
    raising. Audit logging failures are caught and logged — they never
    prevent the tool result from being returned.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)

            ctx = _current_patient_context.get()
            if ctx is None:
                logger.debug(f"audited({action}): no patient context set, skipping audit log")
                return result

            session_id, patient_id = ctx
            try:
                async with get_session_context() as session:
                    audit_repo = AuditRepository(session)
                    await audit_repo.log(
                        agent_name="records_agent",
                        action=action,
                        session_id=session_id,
                        patient_id=patient_id,
                        resource_type=resource_type,
                        payload_summary=f"Accessed {resource_type} for patient.",
                    )
            except Exception as exc:
                logger.error(
                    f"audited({action}): failed to write audit log for patient={patient_id}: {exc}"
                )

            return result

        return wrapper
    return decorator


@tool
@audited("read_patient_profile", "patient_profile")
async def get_patient_profile() -> str:
    """
    Get the authenticated patient's profile information.

    Returns a JSON string with full_name, date_of_birth, gender,
    blood_group, phone, email, insurance_provider, and
    registration_date. Returns {"found": false} if no profile is on
    file.
    """
    ctx = _current_patient_context.get()
    if ctx is None:
        return json.dumps({"found": False})
    _, patient_id = ctx

    async with get_session_context() as session:
        result = await session.execute(select(Patient).where(Patient.patient_id == patient_id))
        patient = result.scalar_one_or_none()

    if patient is None:
        return json.dumps({"found": False})

    return json.dumps({
        "found": True,
        "full_name": patient.full_name,
        "date_of_birth": patient.date_of_birth.isoformat(),
        "gender": patient.gender,
        "blood_group": patient.blood_group,
        "phone": patient.phone,
        "email": patient.email,
        "insurance_provider": patient.insurance_provider,
        "registration_date": patient.registration_date.isoformat(),
    })


@tool
@audited("read_medical_history", "medical_records")
async def get_medical_history(limit: int = 10) -> str:
    """
    Get the authenticated patient's medical visit history (summaries
    only — visit dates and the doctor seen, not raw diagnosis or
    treatment text).

    Parameters
    ----------
    limit   Maximum number of records to return (most recent first).
            Default 10.

    Returns a JSON string: {"records": [{visit_date, doctor_name,
    specialization, follow_up_date}, ...]}.
    """
    ctx = _current_patient_context.get()
    if ctx is None:
        return json.dumps({"records": []})
    _, patient_id = ctx

    async with get_session_context() as session:
        result = await session.execute(
            select(MedicalRecord)
            .where(MedicalRecord.patient_id == patient_id)
            .order_by(MedicalRecord.visit_date.desc())
            .limit(limit)
        )
        records = result.scalars().all()

        records_out = []
        for r in records:
            doctor_row = await session.execute(
                select(Doctor).where(Doctor.doctor_id == r.doctor_id)
            )
            doctor = doctor_row.scalar_one_or_none()
            records_out.append({
                "visit_date": r.visit_date.isoformat(),
                "doctor_name": doctor.full_name if doctor else f"Doctor #{r.doctor_id}",
                "specialization": doctor.specialization if doctor else None,
                "follow_up_date": r.follow_up_date.isoformat() if r.follow_up_date else None,
            })

    logger.info(f"get_medical_history(patient_id={patient_id}) -> {len(records_out)} record(s)")
    return json.dumps({"records": records_out})


@tool
@audited("read_lab_results", "lab_results")
async def get_lab_results(test_name: str = "", limit: int = 10) -> str:
    """
    Get the authenticated patient's lab results.

    Parameters
    ----------
    test_name   Optional partial, case-insensitive match on test name
                (e.g. "glucose"). Leave empty to return all tests.
    limit       Maximum number of results to return (most recent first).
                Default 10.

    Returns a JSON string: {"results": [{test_name, test_date,
    result_value, unit, reference_range, is_abnormal}, ...]}.
    Any entry with is_abnormal=true must be highlighted to the patient.
    """
    ctx = _current_patient_context.get()
    if ctx is None:
        return json.dumps({"results": []})
    _, patient_id = ctx

    async with get_session_context() as session:
        stmt = select(LabResult).where(LabResult.patient_id == patient_id)
        if test_name:
            stmt = stmt.where(LabResult.test_name.ilike(f"%{test_name}%"))
        stmt = stmt.order_by(LabResult.test_date.desc()).limit(limit)

        result = await session.execute(stmt)
        rows = result.scalars().all()

    results_out = [
        {
            "test_name": r.test_name,
            "test_date": r.test_date.isoformat(),
            "result_value": r.result_value,
            "unit": r.unit,
            "reference_range": r.reference_range,
            "is_abnormal": r.is_abnormal,
        }
        for r in rows
    ]

    abnormal_count = sum(1 for r in results_out if r["is_abnormal"])
    logger.info(
        f"get_lab_results(patient_id={patient_id}, test_name={test_name!r}) "
        f"-> {len(results_out)} result(s), {abnormal_count} abnormal"
    )
    return json.dumps({"results": results_out})


@tool
@audited("read_prescriptions", "prescriptions")
async def get_prescriptions(active_only: bool = True) -> str:
    """
    Get the authenticated patient's prescriptions.

    Parameters
    ----------
    active_only   If True (default), return only currently active
                  prescriptions. If False, include all prescriptions.

    Returns a JSON string: {"prescriptions": [{medication_name,
    dosage, frequency, prescribed_date, duration_days, is_active,
    doctor_name}, ...]}.
    """
    ctx = _current_patient_context.get()
    if ctx is None:
        return json.dumps({"prescriptions": []})
    _, patient_id = ctx

    async with get_session_context() as session:
        stmt = select(Prescription).where(Prescription.patient_id == patient_id)
        if active_only:
            stmt = stmt.where(Prescription.is_active.is_(True))
        stmt = stmt.order_by(Prescription.prescribed_date.desc())

        result = await session.execute(stmt)
        rows = result.scalars().all()

        prescriptions_out = []
        for r in rows:
            doctor_row = await session.execute(
                select(Doctor).where(Doctor.doctor_id == r.doctor_id)
            )
            doctor = doctor_row.scalar_one_or_none()
            prescriptions_out.append({
                "medication_name": r.medication_name,
                "dosage": r.dosage,
                "frequency": r.frequency,
                "prescribed_date": r.prescribed_date.isoformat(),
                "duration_days": r.duration_days,
                "is_active": r.is_active,
                "doctor_name": doctor.full_name if doctor else f"Doctor #{r.doctor_id}",
            })

    logger.info(
        f"get_prescriptions(patient_id={patient_id}, active_only={active_only}) "
        f"-> {len(prescriptions_out)} result(s)"
    )
    return json.dumps({"prescriptions": prescriptions_out})


@tool
@audited("read_visit_history", "appointments")
async def get_visit_history(limit: int = 10) -> str:
    """
    Get the authenticated patient's appointment and visit history.

    Parameters
    ----------
    limit   Maximum number of appointments to return (most recent
            first). Default 10.

    Returns a JSON string: {"visits": [{appointment_id, doctor_name,
    specialization, scheduled_at, status}, ...]}.
    """
    ctx = _current_patient_context.get()
    if ctx is None:
        return json.dumps({"visits": []})
    _, patient_id = ctx

    async with get_session_context() as session:
        result = await session.execute(
            select(Appointment)
            .where(Appointment.patient_id == patient_id)
            .order_by(Appointment.scheduled_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()

        visits_out = []
        for r in rows:
            doctor_row = await session.execute(
                select(Doctor).where(Doctor.doctor_id == r.doctor_id)
            )
            doctor = doctor_row.scalar_one_or_none()
            visits_out.append({
                "appointment_id": r.appointment_id,
                "doctor_name": doctor.full_name if doctor else f"Doctor #{r.doctor_id}",
                "specialization": doctor.specialization if doctor else None,
                "scheduled_at": r.scheduled_at.isoformat(),
                "status": r.status,
            })

    logger.info(f"get_visit_history(patient_id={patient_id}) -> {len(visits_out)} visit(s)")
    return json.dumps({"visits": visits_out})


records_tools = [
    get_patient_profile,
    get_medical_history,
    get_lab_results,
    get_prescriptions,
    get_visit_history,
]
records_tool_node = ToolNode(records_tools)


async def records_agent_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Patient Records Agent graph node.

    First thing: checks state["is_authenticated"]. If False, sets
    next_action="auth_required" and returns immediately — no tools are
    bound, no patient data is touched.

    Once authenticated, sets the (session_id, patient_id) ContextVar
    so every tool call is audit-logged against this patient
    automatically via the @audited decorator. Calls the CAPABLE-tier
    LLM with tools bound. If the response contains tool calls, routes
    to records_tool_node (next_action="records_tools") for execution
    and loops back. Otherwise returns the final answer
    (next_action="end"). The ContextVar is always reset in a finally
    block, even on error.
    """
    session_id = state["session_id"]

    if not state.get("is_authenticated", False):
        logger.info(f"records_agent: session={session_id} not authenticated")
        return {
            "messages": [AIMessage(content="To access your medical records, I first need to verify your identity. Could you provide your patient ID, date of birth, and the last 4 digits of your registered phone number?")],
            "active_agent": "auth_agent",
            "next_action": "auth_required",
        }

    patient_id = state["patient_id"]
    token = _current_patient_context.set((session_id, patient_id))

    try:
        settings = get_settings()
        system_prompt = build_records_prompt(settings.HOSPITAL_NAME)

        llm = get_llm(LLMTier.CAPABLE).bind_tools(records_tools)
        llm_messages: list[BaseMessage] = [SystemMessage(content=system_prompt), *state["messages"]]

        try:
            response: AIMessage = await llm.ainvoke(llm_messages)
        except Exception as exc:
            logger.error(f"records_agent LLM call failed for session={session_id}: {exc}")
            return {
                "messages": [AIMessage(content="I'm having trouble accessing records right now. Please try again shortly, or contact reception at 16700.")],
                "active_agent": "records_agent",
                "next_action": "end",
                "error": "Records agent LLM call failed.",
            }

        has_tool_calls = bool(getattr(response, "tool_calls", None))
        next_action = "records_tools" if has_tool_calls else "end"

        logger.info(
            f"records_agent responded for session={session_id} patient={patient_id} "
            f"(tool_calls={len(response.tool_calls) if has_tool_calls else 0})"
        )

        return {
            "messages": [response],
            "active_agent": "records_agent",
            "next_action": next_action,
        }
    finally:
        _current_patient_context.reset(token)