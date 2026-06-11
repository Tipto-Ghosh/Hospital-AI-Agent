from __future__ import annotations
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.db.repositories.appointment_repo import AppointmentRepository
from app.db.repositories.doctor_repo import DoctorRepository
from app.logger import logging as logger

router = APIRouter()
class DepartmentSummary(BaseModel):
    """Nested department info embedded in DoctorResponse."""

    department_id: int
    name: str
    floor_location: str | None
    phone_extension: str | None


class DoctorResponse(BaseModel):
    """Doctor representation with eagerly-loaded department info."""

    doctor_id: int
    full_name: str
    specialization: str
    qualification: str | None
    experience_years: int | None
    consultation_fee: float | None
    phone: str | None
    email: str | None
    bio: str | None
    department: DepartmentSummary | None

    @classmethod
    def from_orm_doctor(cls, doc) -> "DoctorResponse":
        dept = None
        if doc.department is not None:
            dept = DepartmentSummary(
                department_id=doc.department.department_id,
                name=doc.department.name,
                floor_location=doc.department.floor_location,
                phone_extension=doc.department.phone_extension,
            )
        return cls(
            doctor_id=doc.doctor_id,
            full_name=doc.full_name,
            specialization=doc.specialization,
            qualification=doc.qualification,
            experience_years=doc.experience_years,
            consultation_fee=(
                float(doc.consultation_fee) if doc.consultation_fee is not None else None
            ),
            phone=doc.phone,
            email=doc.email,
            bio=doc.bio,
            department=dept,
        )


class DoctorListResponse(BaseModel):
    """Response body for GET /api/v1/doctors."""

    count: int
    doctors: list[DoctorResponse]


class AvailableSlotResponse(BaseModel):
    """A single bookable slot in the availability response."""

    starts_at: str = Field(description="ISO 8601 datetime (UTC, naive).")
    ends_at: str = Field(description="ISO 8601 datetime (UTC, naive).")
    duration_minutes: int


class AvailabilityResponse(BaseModel):
    """Response body for GET /api/v1/doctors/{doctor_id}/availability."""

    doctor_id: int
    doctor_name: str
    date: str
    slot_count: int
    slots: list[AvailableSlotResponse]


# GET /api/v1/doctors
@router.get(
    "/doctors",
    response_model=DoctorListResponse,
    summary="List all active doctors with department info",
    description=(
        "Returns all active doctors, ordered alphabetically by name, with "
        "their department information eagerly loaded. "
        "Supports optional filtering by name, specialization, or department."
    ),
)
async def list_doctors(
    name: str | None = Query(
        None, description="Partial, case-insensitive match on doctor name."
    ),
    specialization: str | None = Query(
        None, description="Partial, case-insensitive match on specialization."
    ),
    department_id: int | None = Query(
        None, gt=0, description="Exact match on department ID."
    ),
    db: AsyncSession = Depends(get_db),
) -> DoctorListResponse:
    repo = DoctorRepository(db)

    if name or specialization or department_id:
        doctors = await repo.search(
            name=name, specialization=specialization, department_id=department_id
        )
    else:
        doctors = await repo.list_active()

    return DoctorListResponse(
        count=len(doctors),
        doctors=[DoctorResponse.from_orm_doctor(d) for d in doctors],
    )


# GET /api/v1/doctors/{doctor_id}/availability 
@router.get(
    "/doctors/{doctor_id}/availability",
    response_model=AvailabilityResponse,
    summary="Get available appointment slots for a doctor on a given date",
    description=(
        "Computes bookable time slots from the doctor's weekly schedule, "
        "minus already-booked appointments and a 2-hour minimum-advance "
        "buffer. Returns an empty slots list if the doctor doesn't work "
        "on that day or is fully booked."
    ),
    responses={
        200: {"description": "Availability computed (may be empty)"},
        404: {"description": "Doctor not found or inactive"},
    },
)
async def get_doctor_availability(
    doctor_id: int,
    target_date: date = Query(
        ...,
        alias="date",
        description="Calendar date to check availability for (YYYY-MM-DD).",
    ),
    db: AsyncSession = Depends(get_db),
) -> AvailabilityResponse:
    doctor_repo = DoctorRepository(db)
    appt_repo = AppointmentRepository(db)

    doctor = await doctor_repo.get_by_id(doctor_id)
    if doctor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Doctor {doctor_id} not found or inactive.",
        )

    slots = await appt_repo.get_available_slots(
        doctor_id=doctor_id,
        target_date=target_date,
        slot_buffer_hours=2,
    )

    return AvailabilityResponse(
        doctor_id=doctor_id,
        doctor_name=doctor.full_name,
        date=target_date.isoformat(),
        slot_count=len(slots),
        slots=[
            AvailableSlotResponse(
                starts_at=s.starts_at.isoformat(),
                ends_at=s.ends_at.isoformat(),
                duration_minutes=s.slot_minutes,
            )
            for s in slots
        ],
    )