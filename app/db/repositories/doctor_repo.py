"""
Repository layer for doctor and department lookups.

Used by
- Information Agent : search(), list_active() to answer "who are your doctors"
- Booking Agent : get_by_id() to validate doctor before slot lookup
- Supervisor Agent : search(specialization=...) to route "I need a cardiologist"
- Patient Records Agent: get_by_id() to resolve doctor name in record display
"""

from __future__ import annotations
from typing import Optional
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.doctor import Department, Doctor

from app.logger import logging

class DoctorRepository:
    """
    All database read operations for the doctors and departments tables.
    No write methods — doctors are managed by hospital administration,
    not by the AI agent.

    Parameters
    session: Active AsyncSession.
    """
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_by_id(
        self,
        doctor_id: int,
        load_department: bool = False,
        load_schedules: bool = False,
    ) -> Doctor | None:
        """
        Fetch an active doctor by primary key.

        Parameters
        doctor_id: Doctor PK (integer).
        load_department: If True, eagerly loads doctor.department.
        load_schedules: If True, eagerly loads doctor.schedules.

        Returns None if the doctor does not exist or is_active=False.
        """
        stmt = select(Doctor).where(
            Doctor.doctor_id == doctor_id,
            Doctor.is_active.is_(True),
        )
        if load_department:
            stmt = stmt.options(selectinload(Doctor.department))
        if load_schedules:
            stmt = stmt.options(selectinload(Doctor.schedules))

        result = await self._s.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        name: str | None = None,
        specialization: str | None = None,
        department_id: int | None = None,
        load_department: bool = True,
    ) -> list[Doctor]:
        """
        Search active doctors by name, specialization, and/or department.
        All filters are combined with AND.  Each text filter uses
        case-insensitive LIKE matching so partial terms work:
            search(name="rahman") -> matches "Dr. Kamal Rahman"
            search(specialization="cardio") -> matches "Cardiologist"

        Parameters
        name: Partial match against Doctor.full_name.
        specialization: Partial match against Doctor.specialization.
        department_id: Exact match on department FK.
        load_department: If True (default), eagerly loads doctor.department so callers can access department.name without an extra query.

        Returns
        List of matching Doctor instances, ordered alphabetically by name.
        Empty list if no matches.
        """
        filters = [Doctor.is_active.is_(True)]

        if name:
            filters.append(
                func.lower(Doctor.full_name).contains(name.lower())
            )
        if specialization:
            filters.append(
                func.lower(Doctor.specialization).contains(specialization.lower())
            )
        if department_id is not None:
            filters.append(Doctor.department_id == department_id)

        stmt = (
            select(Doctor)
            .where(*filters)
            .order_by(Doctor.full_name)
        )
        if load_department:
            stmt = stmt.options(selectinload(Doctor.department))

        result = await self._s.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self, load_department: bool = True) -> list[Doctor]:
        """
        Return all active doctors, ordered by name.

        Used by the Information Agent to answer broad queries like
        "what doctors do you have?" or "show me your specialists".

        Parameters
        load_department: If True (default), eagerly loads Department so doctor.department.name is available.

        Returns
        List of all active Doctor instances.
        """
        stmt = (
            select(Doctor)
            .where(Doctor.is_active.is_(True))
            .order_by(Doctor.full_name)
        )
        if load_department:
            stmt = stmt.options(selectinload(Doctor.department))

        result = await self._s.execute(stmt)
        doctors = list(result.scalars().all())
        logging.debug("list_active: returned %d doctors", len(doctors))
        return doctors

    async def get_department_by_id(self, department_id: int) -> Department | None:
        """
        Fetch an active department by its primary key.

        Used by the Information Agent to resolve department details
        when the patient asks "where is the cardiology department?".
        """
        result = await self._s.execute(
            select(Department).where(
                Department.department_id == department_id,
                Department.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def search_departments(self, name: str) -> list[Department]:
        """
        Case-insensitive partial name search across active departments.

        Used by the Information Agent for queries like
        "where is the cardio department?" -> matches "Cardiology".

        Returns list ordered alphabetically.
        """
        result = await self._s.execute(
            select(Department)
            .where(
                Department.is_active.is_(True),
                func.lower(Department.name).contains(name.lower()),
            )
            .order_by(Department.name)
        )
        return list(result.scalars().all())

    async def list_active_departments(self) -> list[Department]:
        """Return all active departments, ordered by name."""
        result = await self._s.execute(
            select(Department)
            .where(Department.is_active.is_(True))
            .order_by(Department.name)
        )
        return list(result.scalars().all())