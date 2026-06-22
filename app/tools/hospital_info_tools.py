"""
The tools implementations for hospital information retrieval.

This module provides tools for retrieving hospital information, including hospital details and doctor information. It defines the `HospitalInfoTool` class, which implements the `BaseTool` interface for fetching hospital data based on user queries.
"""

from __future__ import annotations
import json
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from sqlalchemy import select

from app.db.base import get_session_context
from app.db.models.medication import HospitalInfo
from app.db.repositories.doctor_repo import DoctorRepository
from app.logger import logging

logger = logging.get_logger(__name__)

@tool
async def get_hospital_info(topic: str) -> str:
    """
    Look up general hospital information by topic.
 
    Use this for questions about hours, location, parking, visiting
    policy, payment methods, insurance, FAQs, or anything not covered
    by the doctor or department tools.
 
    Parameters
    ----------
    topic   A short phrase describing what the patient is asking about
            (e.g. "visiting hours", "parking", "insurance plans").
            Matched as a case-insensitive partial match against the
            topic field.
 
    Returns
    -------
    A JSON string containing a list of matching hospital_info rows
    (category, topic, content). Returns an empty list if nothing
    matches.
    """
    async with get_session_context() as session:
        result = await session.execute(
            select(HospitalInfo).where(HospitalInfo.topic.ilike(f"%{topic}%"))
        )
        rows = result.scalars().all()
 
    results = [
        {"category": row.category, "topic": row.topic, "content": row.content}
        for row in rows
    ]
 
    logger.info(f"get_hospital_info(topic={topic!r}) -> {len(results)} result(s)")
    return json.dumps(results)


@tool
async def get_department_info(department_name: str) -> str:
    """
    Look up a hospital department by name.
 
    Use this when the patient asks where a department is located, its
    extension number, or general department information (e.g. "where
    is cardiology?").
 
    Parameters
    ----------
    department_name   Partial, case-insensitive department name (e.g.
                       "cardio", "emergency").
 
    Returns
    -------
    A JSON string containing a list of matching departments with name,
    floor location, phone extension, and description. Returns an empty
    list if nothing matches.
    """
    async with get_session_context() as session:
        repo = DoctorRepository(session)
        departments = await repo.search_departments(department_name)
 
    results = [
        {
            "department_id": d.department_id,
            "name": d.name,
            "floor_location": d.floor_location,
            "phone_extension": d.phone_extension,
            "description": d.description,
        }
        for d in departments
    ]
 
    logger.info(f"get_department_info(department_name={department_name!r}) -> {len(results)} result(s)")
    return json.dumps(results)

 
@tool
async def get_doctor_info(name: Optional[str] = None, specialization: Optional[str] = None) -> str:
    """
    Look up doctors by name and/or specialization.
 
    Use this when the patient asks about a specific doctor (e.g. "Dr.
    Rahman") or a type of specialist (e.g. "do you have a cardiologist?").
 
    Parameters
    ----------
    name             Partial, case-insensitive doctor name. Leave as
                     None if not searching by name.
    specialization   Partial, case-insensitive specialization (e.g.
                     "cardio", "pediatrics"). Leave as None if not
                     searching by specialization.
 
    Returns
    -------
    A JSON string containing a list of matching doctors with their
    name, specialization, department, consultation fee, and
    qualification. Returns an empty list if nothing matches.
    """
    async with get_session_context() as session:
        repo = DoctorRepository(session)
        doctors = await repo.search(
            name=name or None,
            specialization=specialization or None,
            load_department=True,
        )
 
    results = [
        {
            "doctor_id": d.doctor_id,
            "full_name": d.full_name,
            "specialization": d.specialization,
            "department": d.department.name if d.department else None,
            "consultation_fee": float(d.consultation_fee) if d.consultation_fee is not None else None,
            "qualification": d.qualification,
            "experience_years": d.experience_years,
        }
        for d in doctors
    ]
 
    logger.info(
        f"get_doctor_info(name={name!r}, specialization={specialization!r}) "
        f"-> {len(results)} result(s)"
    )
    return json.dumps(results)

@tool
async def list_services(service_type: Optional[str] = None) -> str:
    """
    List hospital services, optionally filtered by service type.
 
    Use this when the patient asks what services or facilities the
    hospital offers (e.g. "what services do you provide?", "do you have
    a blood bank?").
 
    Parameters
    ----------
    service_type   Optional partial, case-insensitive match against the
                   service topic (e.g. "blood bank", "radiology").
                   Leave as None to list all services.
 
    Returns
    -------
    A JSON string containing a list of services, each with a topic and
    content description. Returns an empty list if no services match
    (or none are on file).
    """
    async with get_session_context() as session:
        stmt = select(HospitalInfo).where(HospitalInfo.category == "service")
        if service_type:
            stmt = stmt.where(HospitalInfo.topic.ilike(f"%{service_type}%"))
 
        result = await session.execute(stmt)
        rows = result.scalars().all()
 
    results = [{"topic": row.topic, "content": row.content} for row in rows]
 
    logger.info(f"list_services(service_type={service_type!r}) -> {len(results)} result(s)")
    return json.dumps(results)
 

hospital_info_tools = [get_hospital_info, get_department_info, get_doctor_info, list_services]