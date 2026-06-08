"""
Repository layer for appointment-related DB operations.

Every agent that touches appointments (Booking, Cancellation, Rescheduling,
Supervisor) calls methods on this class.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.db.models.appointment import Appointment
from app.db.models.doctor import Doctor, DoctorSchedule
from app.logger import logging
from app.exception import CustomException

@dataclass(frozen=True, order=True)
class AvailableSlot:
    """
    A single bookable time slot for a doctor.

    # Attributes
    starts_at - Naive UTC datetime of the slot start.
    ends_at - Naive UTC datetime of the slot end.
    slot_minutes - Duration of this slot in minutes (from doctor's schedule).
    is_available - Always True — unavailable slots are excluded from results.
    """
    starts_at: datetime
    ends_at: datetime
    slot_minutes: int = 20
    is_available: bool = field(default=True, compare=False)

    def __str__(self) -> str:
        return self.starts_at.strftime("%Y-%m-%d %H:%M")

# Appointment ID generator
async def _generate_appointment_id(session: AsyncSession, target_date: datetime) -> str:
    """
    Generate the next sequential appointment ID for a given date.

    Format: APT-YYYYMMDD-NNNN  (e.g. APT-20241105-0001)

    Queries the DB for the highest sequence number on that date and
    increments by 1.  Safe for concurrent inserts because the ID is
    checked/generated within the same transaction as the INSERT.
    """
    date_str = target_date.strftime("%Y%m%d")
    prefix = f"APT-{date_str}-"

    result = await session.execute(
        select(Appointment.appointment_id)
        .where(Appointment.appointment_id.like(f"{prefix}%"))
        .order_by(Appointment.appointment_id.desc())
        .limit(1)
    )
    last_id: str | None = result.scalar_one_or_none()

    if last_id is None:
        seq = 1
    else:
        seq = int(last_id.split("-")[-1]) + 1

    return f"{prefix}{seq:04d}"


# AppointmentRepository
class AppointmentRepository:
    """
    All database operations for the appointments table.

    Instantiate with an active AsyncSession; the session is provided
    by the agent tool via the get_session_context() context manager.

    # Parameters
    session - An active AsyncSession (not yet committed).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        appointment_id: str,
        load_relations: bool = False,
    ) -> Appointment | None:
        """
        Fetch a single appointment by its primary key.

        Parameters:
        appointment_id - The appointment PK.
        load_relations - If True, eagerly loads patient and doctor via
        selectinload — use when the agent needs doctor.full_name
        or patient.phone without additional queries.

        Returns None if no matching appointment exists.
        """
        stmt = select(Appointment).where(Appointment.appointment_id == appointment_id)

        if load_relations:
            stmt = stmt.options(
                selectinload(Appointment.patient),
                selectinload(Appointment.doctor),
            )

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_patient(
        self,
        patient_id: str,
        status: str | None = None,
        upcoming_only: bool = False,
        limit: int = 20,
    ) -> list[Appointment]:
        """
        Fetch all appointments for a patient, optionally filtered.

        # Parameters
        
        patient_id - Patient PK.
        status - Filter to a specific status string.If None, returns all statuses.
        upcoming_only - If True, only returns appointments where scheduled_at > now (UTC).
        limit - Maximum number of rows to return (newest first).

        Returns a list ordered by scheduled_at descending (most recent first).
        """
        filters = [Appointment.patient_id == patient_id]

        if status is not None:
            filters.append(Appointment.status == status)

        if upcoming_only:
            now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC
            filters.append(Appointment.scheduled_at > now)

        stmt = (
            select(Appointment)
            .where(and_(*filters))
            .order_by(Appointment.scheduled_at.desc())
            .limit(limit)
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_doctor_and_date(
        self,
        doctor_id: int,
        target_date: date,
    ) -> list[Appointment]:
        """
        Fetch all non-cancelled appointments for a doctor on a specific date.

        Used by get_available_slots() to determine which time slots are
        already taken.

        Parameters
        doctor_id - Doctor PK.
        target_date-The calendar date to check.
        """
        day_start = datetime.combine(target_date, time.min)
        day_end = datetime.combine(target_date, time.max)

        stmt = (
            select(Appointment)
            .where(
                and_(
                    Appointment.doctor_id == doctor_id,
                    Appointment.scheduled_at >= day_start,
                    Appointment.scheduled_at <= day_end,
                    Appointment.status.notin_(["cancelled", "no_show"]),
                )
            )
            .order_by(Appointment.scheduled_at)
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_available_slots(
        self,
        doctor_id: int,
        target_date: date,
        slot_buffer_hours: int = 2,
    ) -> list[AvailableSlot]:
        """
        Compute all bookable time slots for a doctor on a given date.

        Algorithm
        1. Fetch the doctor's DoctorSchedule row for the day of the week.
        2. Generate all slot start times from start_time to end_time
           using slot_duration_min as the step.
        3. Fetch all existing non-cancelled appointments for that doctor
           on that date.
        4. Subtract booked slots (any slot whose starts_at matches an
           existing appointment's scheduled_at).
        5. Also subtract slots that fall within slot_buffer_hours of now
           (prevents same-day last-minute bookings that the agent can't
           process in time).

        Parameters
        doctor_id-Doctor PK.
        target_date-Calendar date to compute slots for.
        slot_buffer_hours-Minimum lead time in hours before a slot
                        can be booked.  Default 2h (from SecuritySettings).

        Returns
        
        List of AvailableSlot, ordered chronologically.
        Empty list if the doctor doesn't work on that day or is fully booked.
        """
        day_name = target_date.strftime("%A")  # e.g. "Monday"

        # Fetch the schedule for this day
        sched_result = await self._session.execute(
            select(DoctorSchedule).where(
                and_(
                    DoctorSchedule.doctor_id == doctor_id,
                    DoctorSchedule.day_of_week == day_name,
                    DoctorSchedule.is_active.is_(True),
                )
            )
        )
        schedule: DoctorSchedule | None = sched_result.scalar_one_or_none()

        if schedule is None:
            logging.debug(f"Doctor {doctor_id} has no schedule for {day_name}")
            return []

        # Build all possible slot start times for this day
        slot_min = schedule.slot_duration_min
        current = datetime.combine(target_date, schedule.start_time)
        end_dt  = datetime.combine(target_date, schedule.end_time)

        all_slots: list[datetime] = []
        while current + timedelta(minutes=slot_min) <= end_dt:
            all_slots.append(current)
            current += timedelta(minutes=slot_min)

        if not all_slots:
            return []

        # Fetch already-booked slots for this doctor on this date
        booked_appts = await self.get_by_doctor_and_date(doctor_id, target_date)
        booked_times: set[datetime] = {
            appt.scheduled_at.replace(second=0, microsecond=0)
            for appt in booked_appts
        }

        # Buffer: don't offer slots within N hours of now
        buffer_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
            hours=slot_buffer_hours
        )

        # Build available slots
        available: list[AvailableSlot] = []
        for slot_start in all_slots:
            slot_key = slot_start.replace(second=0, microsecond=0)

            if slot_start <= buffer_cutoff:
                continue  # too soon

            if slot_key in booked_times:
                continue  # already taken

            available.append(
                AvailableSlot(
                    starts_at=slot_start,
                    ends_at=slot_start + timedelta(minutes=slot_min),
                    slot_minutes=slot_min,
                )
            )

        logging.debug(
            f"Doctor {doctor_id} on {target_date}: {len(all_slots)} total slots, {len(booked_times)} booked, {len(available)} available"
        )
        return available

    async def count_active_by_patient_and_doctor(
        self,
        patient_id: str,
        doctor_id: int,
    ) -> int:
        """
        Count active (non-cancelled) appointments between a patient and doctor.

        Used to enforce the guardrail: max 1 active appointment per
        patient per doctor at a time.
        """
        result = await self._session.execute(
            select(Appointment)
            .where(
                and_(
                    Appointment.patient_id == patient_id,
                    Appointment.doctor_id == doctor_id,
                    Appointment.status.in_(["pending", "confirmed"]),
                    Appointment.scheduled_at > datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
        )
        return len(result.scalars().all())

    async def create(
        self,
        patient_id: str,
        doctor_id: int,
        scheduled_at: datetime,
        reason: str | None = None,
        notes: str | None = None,
        booked_via: str = "ai_agent",
        duration_min: int | None = None,
    ) -> Appointment:
        """
        Create a new appointment and commit it to the database.

        Pre-conditions (checked by this method — raises CustomException on violation)
        
        1. The slot (doctor_id, scheduled_at) must not already be booked.
        2. The patient must not have an existing active appointment with
           the same doctor (max-1-per-doctor guardrail).
        3. scheduled_at must be in the future (at least 2 hours from now).

        Parameters
        patient_id-Patient PK.
        doctor_id-Doctor PK.
        scheduled_at-Naive UTC datetime of the desired slot.
        reason-Optional reason for visit (stored in reason_for_visit).
        notes-Optional internal notes.
        booked_via-Channel: 'ai_agent' | 'web' | 'phone' | 'walk_in'.
        duration_min-Slot duration in minutes.  If None, fetched from the doctor's schedule; falls back to 20 min.

        Returns
        The newly created and committed Appointment instance.
        """
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        # Guard: minimum 2-hour advance notice
        if scheduled_at <= now_utc + timedelta(hours=2):
            raise CustomException(
                f"Appointments must be booked at least 2 hours in advance. "
                f"Requested: {scheduled_at}, now: {now_utc}.",
                sys
            )

        # Guard: slot not already taken
        existing = await self.get_by_doctor_and_date(
            doctor_id, scheduled_at.date()
        )
        booked_times = {
            a.scheduled_at.replace(second=0, microsecond=0) for a in existing
        }
        requested = scheduled_at.replace(second=0, microsecond=0)
        if requested in booked_times:
            raise CustomException(
                f"The slot {scheduled_at} for doctor {doctor_id} is already booked.",
                sys
            )

        # Guard: max 1 active appointment per patient per doctor
        active_count = await self.count_active_by_patient_and_doctor(
            patient_id, doctor_id
        )
        if active_count >= 1:
            raise CustomException(
                f"Patient {patient_id} already has an active appointment "
                f"with doctor {doctor_id}.",
                sys
            )

        # Resolve slot duration from schedule if not provided
        if duration_min is None:
            day_name = scheduled_at.strftime("%A")
            sched_result = await self._session.execute(
                select(DoctorSchedule).where(
                    and_(
                        DoctorSchedule.doctor_id == doctor_id,
                        DoctorSchedule.day_of_week == day_name,
                        DoctorSchedule.is_active.is_(True),
                    )
                )
            )
            sched = sched_result.scalar_one_or_none()
            duration_min = sched.slot_duration_min if sched else 20

        appointment_id = await _generate_appointment_id(self._session, scheduled_at)

        appointment = Appointment(
            appointment_id=appointment_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            scheduled_at=scheduled_at,
            duration_min=duration_min,
            status="pending",
            reason_for_visit=reason,
            notes=notes,
            booked_via=booked_via,
        )

        self._session.add(appointment)
        await self._session.commit()
        await self._session.refresh(appointment)

        logging.info(
            f"Appointment created: {appointment_id} | patient={patient_id} | doctor={doctor_id} | at={scheduled_at}"
        )
        return appointment

    async def cancel(
        self,
        appointment_id: str,
        reason: str | None = None,
    ) -> Appointment:
        """
        Cancel an appointment (soft-delete).

        Sets status='cancelled', records cancelled_at and
        cancellation_reason.  The row is never hard-deleted.

        Pre-conditions (raises CustomException on violation)
        1. Appointment must exist.
        2. Appointment must be is_cancellable() → True (>24h away,
           not already cancelled/completed/no_show).

        Parameters
        appointment_id  The appointment to cancel.
        reason-Optional patient-provided reason (stored in
                        cancellation_reason).

        Returns
        The updated Appointment instance.
        """
        appointment = await self.get_by_id(appointment_id)

        if appointment is None:
            raise CustomException(f"Appointment {appointment_id!r} not found.", sys)

        if not appointment.is_cancellable():
            raise CustomException(
                f"Appointment {appointment_id!r} cannot be cancelled. "
                f"Current status: {appointment.status!r}. "
                "Cancellations must be made at least 24 hours before the scheduled time.",
                sys
            )

        appointment.status = "cancelled"
        appointment.cancelled_at = datetime.now(timezone.utc).replace(tzinfo=None)
        appointment.cancellation_reason = reason or "Cancelled by patient"

        await self._session.commit()
        await self._session.refresh(appointment)

        logging.info(
            f"Appointment cancelled: {appointment_id} | reason={reason!r}"
        )
        return appointment

    async def reschedule(
        self,
        appointment_id: str,
        new_datetime: datetime,
        reason: str | None = None,
    ) -> Appointment:
        """
        Atomically cancel the existing appointment and create a new one.

        Both operations happen within a single transaction:
        - If the new slot is unavailable, the entire operation rolls back
          and the original appointment remains intact.
        - If the cancel succeeds but the create fails, the rollback
          restores the original appointment.

        Pre-conditions
        1. Original appointment must exist and be cancellable.
        2. new_datetime must satisfy the same rules as create()
           (>2h advance, slot must be free, no duplicate active appt).

        Parameters
        ----------
        appointment_id-The existing appointment to reschedule.
        new_datetime-The desired new slot (naive UTC datetime).
        reason-Optional reason for rescheduling.

        Returns
        The newly created Appointment (the rescheduled one).
        The old appointment is cancelled (its row is updated in place).
        """
        # Fetch original within the current transaction
        original = await self.get_by_id(appointment_id)

        if original is None:
            raise CustomException(f"Appointment {appointment_id!r} not found.", sys)

        if not original.is_cancellable():
            raise CustomException(
                f"Appointment {appointment_id!r} cannot be rescheduled. "
                f"Status: {original.status!r}.",
                sys
            )

        patient_id = original.patient_id
        doctor_id  = original.doctor_id

        # Step 1: Cancel the original (within the same transaction — no commit yet)
        original.status = "cancelled"
        original.cancelled_at = datetime.now(timezone.utc).replace(tzinfo=None)
        original.cancellation_reason = (
            reason or f"Rescheduled to {new_datetime.strftime('%Y-%m-%d %H:%M')}"
        )
        await self._session.flush()  # write cancel to DB but don't commit yet

        # Step 2: Validate and create the new appointment
        # Re-use create() logic inline so guards fire correctly.
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        if new_datetime <= now_utc + timedelta(hours=2):
            await self._session.rollback()
            raise CustomException(
                "New appointment time must be at least 2 hours in the future.",
                sys
            )

        existing = await self.get_by_doctor_and_date(doctor_id, new_datetime.date())
        booked_times = {
            a.scheduled_at.replace(second=0, microsecond=0) for a in existing
        }
        requested = new_datetime.replace(second=0, microsecond=0)
        if requested in booked_times:
            await self._session.rollback()
            raise CustomException(
                f"The slot {new_datetime} for doctor {doctor_id} is already booked. "
                "The original appointment has NOT been cancelled.",
                sys
            )

        # Resolve slot duration
        day_name = new_datetime.strftime("%A")
        sched_result = await self._session.execute(
            select(DoctorSchedule).where(
                and_(
                    DoctorSchedule.doctor_id == doctor_id,
                    DoctorSchedule.day_of_week == day_name,
                    DoctorSchedule.is_active.is_(True),
                )
            )
        )
        sched = sched_result.scalar_one_or_none()
        duration_min = sched.slot_duration_min if sched else 20

        new_appointment_id = await _generate_appointment_id(
            self._session, new_datetime
        )
        new_appointment = Appointment(
            appointment_id=new_appointment_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            scheduled_at=new_datetime,
            duration_min=duration_min,
            status="pending",
            reason_for_visit=original.reason_for_visit,
            notes=f"Rescheduled from {appointment_id}.",
            booked_via=original.booked_via,
        )
        self._session.add(new_appointment)

        # Single commit for both cancel + create — atomic
        await self._session.commit()
        await self._session.refresh(new_appointment)

        logging.info(
            f"Appointment rescheduled: {appointment_id} → {new_appointment_id} | doctor={doctor_id} | new_time={new_datetime}"
        )
        return new_appointment

    async def confirm(self, appointment_id: str) -> Appointment:
        """
        Confirm a pending appointment (status: pending → confirmed).

        Called by the Booking Agent after the patient explicitly confirms
        the booking details in the conversation.
        """
        appointment = await self.get_by_id(appointment_id)
        if appointment is None:
            raise CustomException(f"Appointment {appointment_id!r} not found.", sys)
        if appointment.status != "pending":
            raise CustomException(
                f"Only pending appointments can be confirmed. "
                f"Current status: {appointment.status!r}.",
                sys
            )

        appointment.status = "confirmed"
        await self._session.commit()
        await self._session.refresh(appointment)

        logging.info(f"Appointment confirmed: {appointment_id}")
        return appointment