"""
Rest endpoints for direct appointment operations.

Endpoints
POST   /api/v1/appointments - AI-assisted booking
GET    /api/v1/appointments/{id} - get by ID (auth required)
PATCH  /api/v1/appointments/{id}/cancel - cancel an appointment
PATCH  /api/v1/appointments/{id}/reschedule - reschedule to a new slot
"""

from __future__ import annotations
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_authenticated_patient, get_db
from app.db.repositories.appointment_repo import AppointmentRepository
from app.db.repositories.audit_repo import AuditRepository
from app.logger import logging


router = APIRouter()
class AppointmentCreateRequest(BaseModel):
    """Request body for POST /api/v1/appointments."""

    doctor_id: int = Field(..., gt=0, description="Doctor PK.")
    scheduled_at: datetime = Field(
        ...,
        description=(
            "Desired appointment datetime (UTC, naive). "
            "Must be at least 2 hours in the future and match an "
            "available slot from GET /doctors/{id}/availability."
        ),
    )
    reason: str | None = Field(
        None, max_length=500, description="Reason for visit (optional)."
    )
    notes: str | None = Field(
        None, max_length=500, description="Additional notes (optional)."
    )


class AppointmentResponse(BaseModel):
    """Standard appointment representation returned by all endpoints."""

    appointment_id: str
    patient_id: str
    doctor_id: int
    scheduled_at: datetime
    duration_min: int
    status: str
    reason_for_visit: str | None
    notes: str | None
    booked_via: str
    created_at: datetime
    cancelled_at: datetime | None
    cancellation_reason: str | None

    @classmethod
    def from_orm_appointment(cls, appt) -> "AppointmentResponse":
        return cls(
            appointment_id=appt.appointment_id,
            patient_id=appt.patient_id,
            doctor_id=appt.doctor_id,
            scheduled_at=appt.scheduled_at,
            duration_min=appt.duration_min,
            status=appt.status,
            reason_for_visit=appt.reason_for_visit,
            notes=appt.notes,
            booked_via=appt.booked_via,
            created_at=appt.created_at,
            cancelled_at=appt.cancelled_at,
            cancellation_reason=appt.cancellation_reason,
        )


class CancelRequest(BaseModel):
    """Request body for PATCH /api/v1/appointments/{id}/cancel."""

    reason: str | None = Field(
        None, max_length=500, description="Patient-provided cancellation reason."
    )


class RescheduleRequest(BaseModel):
    """Request body for PATCH /api/v1/appointments/{id}/reschedule."""

    new_datetime: datetime = Field(
        ...,
        description="New appointment datetime (UTC, naive). Must satisfy the "
                     "same booking rules as a fresh appointment.",
    )
    reason: str | None = Field(
        None, max_length=500, description="Reason for rescheduling (optional)."
    )


# Ownership helper 
async def _get_owned_appointment(
    repo: AppointmentRepository,
    appointment_id: str,
    patient_id: str,
):
    """
    Fetch an appointment and verify it belongs to the requesting patient.

    Raises
    ------
    404  if the appointment does not exist.
    403  if the appointment exists but belongs to a different patient.
         (Returned as 404 instead of 403 to avoid leaking the existence
         of other patients' appointment IDs — standard practice for
         resource enumeration prevention.)
    """
    appt = await repo.get_by_id(appointment_id)
    if appt is None or appt.patient_id != patient_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment {appointment_id!r} not found.",
        )
    return appt


# POST /api/v1/appointments 
@router.post(
    "/appointments",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Book an appointment (AI-assisted)",
    description=(
        "Creates a new appointment for the authenticated patient. "
        "Applies the same guardrails as the conversational Booking Agent: "
        "minimum 2-hour advance notice, slot availability check, and "
        "max-1-active-appointment-per-doctor rule. "
        "Use GET /api/v1/doctors/{doctor_id}/availability first to find "
        "a valid scheduled_at value."
    ),
    responses={
        201: {"description": "Appointment created"},
        400: {"description": "Booking rule violated (slot taken, too soon, "
                              "or duplicate active appointment)"},
        401: {"description": "Not authenticated"},
    },
)
async def create_appointment(
    body: AppointmentCreateRequest,
    patient_id: str = Depends(get_authenticated_patient),
    db: AsyncSession = Depends(get_db),
) -> AppointmentResponse:
    repo = AppointmentRepository(db)
    audit_repo = AuditRepository(db)

    try:
        appt = await repo.create(
            patient_id=patient_id,
            doctor_id=body.doctor_id,
            scheduled_at=body.scheduled_at,
            reason=body.reason,
            notes=body.notes,
            booked_via="web",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await audit_repo.log(
        agent_name="appointments_route",
        action="create_appointment",
        patient_id=patient_id,
        resource_type="appointment",
        resource_id=appt.appointment_id,
        payload_summary=f"Booked appointment with doctor {body.doctor_id}.",
    )
    await db.commit()

    logging.info(
        "Appointment created via REST: %s | patient=%s | doctor=%d",
        appt.appointment_id, patient_id, body.doctor_id,
    )
    return AppointmentResponse.from_orm_appointment(appt)


# GET /api/v1/appointments/{id} 
@router.get(
    "/appointments/{appointment_id}",
    response_model=AppointmentResponse,
    summary="Get appointment details by ID",
    responses={
        200: {"description": "Appointment found"},
        404: {"description": "Appointment not found or not owned by you"},
    },
)
async def get_appointment(
    appointment_id: str,
    patient_id: str = Depends(get_authenticated_patient),
    db: AsyncSession = Depends(get_db),
) -> AppointmentResponse:
    repo = AppointmentRepository(db)
    appt = await _get_owned_appointment(repo, appointment_id, patient_id)
    return AppointmentResponse.from_orm_appointment(appt)


# PATCH /api/v1/appointments/{id}/cancel 
@router.patch(
    "/appointments/{appointment_id}/cancel",
    response_model=AppointmentResponse,
    summary="Cancel an appointment",
    description=(
        "Soft-cancels the appointment (status='cancelled'). "
        "Must be at least 24 hours before the scheduled time — see "
        "Appointment.is_cancellable()."
    ),
    responses={
        200: {"description": "Appointment cancelled"},
        400: {"description": "Cancellation policy violated (within 24h, "
                              "or appointment already cancelled/completed)"},
        404: {"description": "Appointment not found or not owned by you"},
    },
)
async def cancel_appointment(
    appointment_id: str,
    body: CancelRequest,
    patient_id: str = Depends(get_authenticated_patient),
    db: AsyncSession = Depends(get_db),
) -> AppointmentResponse:
    repo = AppointmentRepository(db)
    audit_repo = AuditRepository(db)

    # Ownership check first (before attempting cancel)
    await _get_owned_appointment(repo, appointment_id, patient_id)

    try:
        appt = await repo.cancel(appointment_id, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await audit_repo.log(
        agent_name="appointments_route",
        action="cancel_appointment",
        patient_id=patient_id,
        resource_type="appointment",
        resource_id=appointment_id,
        payload_summary="Appointment cancelled by patient.",
    )
    await db.commit()

    logging.info("Appointment cancelled via REST: %s | patient=%s", appointment_id, patient_id)
    return AppointmentResponse.from_orm_appointment(appt)


# PATCH /api/v1/appointments/{id}/reschedule
@router.patch(
    "/appointments/{appointment_id}/reschedule",
    response_model=AppointmentResponse,
    summary="Reschedule an appointment to a new time",
    description=(
        "Atomically cancels the existing appointment and creates a new "
        "one at new_datetime. If the new slot is unavailable, the entire "
        "operation rolls back and the original appointment remains intact. "
        "The response is the NEW appointment (with a new appointment_id)."
    ),
    responses={
        200: {"description": "Rescheduled — response is the new appointment"},
        400: {"description": "Reschedule rule violated (original not cancellable, "
                              "or new slot unavailable)"},
        404: {"description": "Appointment not found or not owned by you"},
    },
)
async def reschedule_appointment(
    appointment_id: str,
    body: RescheduleRequest,
    patient_id: str = Depends(get_authenticated_patient),
    db: AsyncSession = Depends(get_db),
) -> AppointmentResponse:
    repo = AppointmentRepository(db)
    audit_repo = AuditRepository(db)

    # Ownership check first
    await _get_owned_appointment(repo, appointment_id, patient_id)

    try:
        new_appt = await repo.reschedule(
            appointment_id, body.new_datetime, reason=body.reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await audit_repo.log(
        agent_name="appointments_route",
        action="reschedule_appointment",
        patient_id=patient_id,
        resource_type="appointment",
        resource_id=new_appt.appointment_id,
        payload_summary=(
            f"Rescheduled from {appointment_id} to {new_appt.appointment_id}."
        ),
    )
    await db.commit()

    logging.info(
        "Appointment rescheduled via REST: %s → %s | patient=%s",
        appointment_id, new_appt.appointment_id, patient_id,
    )
    return AppointmentResponse.from_orm_appointment(new_appt)