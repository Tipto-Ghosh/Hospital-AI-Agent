from __future__ import annotations
from datetime import time
from typing import List, Optional

from sqlalchemy import (
    TEXT, Boolean, Enum, ForeignKey, Integer, Numeric, String, Time, event
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.logger import logging
from app.exception import CustomException


class Department(Base):
    __tablename__ = "departments"

    department_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    floor_location: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    phone_extension: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    head_doctor_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    doctors: Mapped[List["Doctor"]] = relationship(
        "Doctor", back_populates="department", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<Department id={self.department_id} name={self.name!r} active={self.is_active}>"


class Doctor(Base):
    __tablename__ = "doctors"

    doctor_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    specialization: Mapped[str] = mapped_column(String(100), nullable=False)
    department_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("departments.department_id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    qualification: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    experience_years: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    consultation_fee: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    department: Mapped["Department"] = relationship(
        "Department", back_populates="doctors", lazy="select"
    )
    schedules: Mapped[List["DoctorSchedule"]] = relationship(
        "DoctorSchedule", back_populates="doctor",
        cascade="all, delete-orphan", lazy="select"
    )

    def __repr__(self) -> str:
        return (
            f"<Doctor id={self.doctor_id} name={self.full_name!r} "
            f"spec={self.specialization!r} active={self.is_active}>"
        )


class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"

    schedule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doctor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("doctors.doctor_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    day_of_week: Mapped[Optional[str]] = mapped_column(
        Enum("Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday",
             name="day_of_week_enum"),
        nullable=True,
    )
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_duration_min: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    max_appointments: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="schedules", lazy="select")

    def __repr__(self) -> str:
        return (
            f"<DoctorSchedule id={self.schedule_id} doctor_id={self.doctor_id} "
            f"day={self.day_of_week} {self.start_time}–{self.end_time}>"
        )


# Lifecycle event listeners – log insert/update/delete and raise CustomException on error

# Department listeners 
@event.listens_for(Department, "after_insert")
def _log_department_insert(mapper, connection, target: Department) -> None:
    try:
        logging.info("Department created: id=%d, name=%s", target.department_id, target.name)
    except Exception as exc:
        logging.exception("Logging failure during Department insert event.")
        raise CustomException(
            error_message="Failed to process Department insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Department, "after_update")
def _log_department_update(mapper, connection, target: Department) -> None:
    try:
        logging.info("Department updated: id=%d, name=%s", target.department_id, target.name)
    except Exception as exc:
        logging.exception("Logging failure during Department update event.")
        raise CustomException(
            error_message="Failed to process Department update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Department, "after_delete")
def _log_department_delete(mapper, connection, target: Department) -> None:
    try:
        logging.info("Department deleted: id=%d, name=%s", target.department_id, target.name)
    except Exception as exc:
        logging.exception("Logging failure during Department delete event.")
        raise CustomException(
            error_message="Failed to process Department delete event.",
            error_detail=str(exc),
        ) from exc


# Doctor listeners
@event.listens_for(Doctor, "after_insert")
def _log_doctor_insert(mapper, connection, target: Doctor) -> None:
    try:
        logging.info("Doctor created: id=%d, name=%s, spec=%s", target.doctor_id, target.full_name, target.specialization)
    except Exception as exc:
        logging.exception("Logging failure during Doctor insert event.")
        raise CustomException(
            error_message="Failed to process Doctor insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Doctor, "after_update")
def _log_doctor_update(mapper, connection, target: Doctor) -> None:
    try:
        logging.info("Doctor updated: id=%d, name=%s, spec=%s", target.doctor_id, target.full_name, target.specialization)
    except Exception as exc:
        logging.exception("Logging failure during Doctor update event.")
        raise CustomException(
            error_message="Failed to process Doctor update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Doctor, "after_delete")
def _log_doctor_delete(mapper, connection, target: Doctor) -> None:
    try:
        logging.info("Doctor deleted: id=%d, name=%s", target.doctor_id, target.full_name)
    except Exception as exc:
        logging.exception("Logging failure during Doctor delete event.")
        raise CustomException(
            error_message="Failed to process Doctor delete event.",
            error_detail=str(exc),
        ) from exc


# DoctorSchedule listeners 
@event.listens_for(DoctorSchedule, "after_insert")
def _log_schedule_insert(mapper, connection, target: DoctorSchedule) -> None:
    try:
        logging.info("DoctorSchedule created: id=%d, doctor_id=%d, day=%s", target.schedule_id, target.doctor_id, target.day_of_week)
    except Exception as exc:
        logging.exception("Logging failure during DoctorSchedule insert event.")
        raise CustomException(
            error_message="Failed to process DoctorSchedule insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(DoctorSchedule, "after_update")
def _log_schedule_update(mapper, connection, target: DoctorSchedule) -> None:
    try:
        logging.info("DoctorSchedule updated: id=%d, doctor_id=%d, day=%s", target.schedule_id, target.doctor_id, target.day_of_week)
    except Exception as exc:
        logging.exception("Logging failure during DoctorSchedule update event.")
        raise CustomException(
            error_message="Failed to process DoctorSchedule update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(DoctorSchedule, "after_delete")
def _log_schedule_delete(mapper, connection, target: DoctorSchedule) -> None:
    try:
        logging.info("DoctorSchedule deleted: id=%d, doctor_id=%d, day=%s", target.schedule_id, target.doctor_id, target.day_of_week)
    except Exception as exc:
        logging.exception("Logging failure during DoctorSchedule delete event.")
        raise CustomException(
            error_message="Failed to process DoctorSchedule delete event.",
            error_detail=str(exc),
        ) from exc