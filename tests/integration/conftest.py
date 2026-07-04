"""
tests/integration/conftest.py

Shared fixtures for all integration tests. Provides:
  - A real in-memory SQLite database with all tables created and seed
    data inserted (departments, doctors, patients, hospital_info).
  - A fully compiled LangGraph graph using that patched DB engine.
  - A MockRedis helper that emulates the Redis operations used by
    session/OTP/memory code without requiring a real Redis server.

All integration tests in this directory inherit these fixtures via
pytest's conftest.py discovery.
"""

import asyncio
from datetime import date, datetime, time, timedelta
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models.doctor import Department, Doctor, DoctorSchedule
from app.db.models.medication import HospitalInfo
from app.db.models.patient import Patient
from app.db.models.appointment import Appointment
from app.db.models.billing import BillingInvoice, InvoiceItem
from app.db.models.medical_record import MedicalRecord, LabResult, Prescription

class MockRedis:
    """
    In-memory Redis emulator covering the subset of commands used by
    session_manager, RedisMessageHistory, and auth_agent_node in
    integration tests:
      SETEX, GET, DEL, EXISTS, RPUSH, LTRIM, LRANGE, EXPIRE, LLEN,
      PIPELINE.

    Not a full Redis emulator - only the operations exercised by these
    tests are implemented.
    """

    def __init__(self):
        self._store: dict[str, bytes | list[bytes]] = {}
        self._pipeline_ops: list = []
        self._in_pipeline = False

    def _encode(self, value) -> bytes:
        if isinstance(value, bytes):
            return value
        return str(value).encode("utf-8")

    async def setex(self, key: str, ttl: int, value) -> None:
        self._store[key] = self._encode(value)

    async def get(self, key: str):
        return self._store.get(key)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                deleted += 1
        return deleted

    async def expire(self, key: str, ttl: int) -> int:
        return 1 if key in self._store else 0

    async def rpush(self, key: str, *values) -> int:
        if key not in self._store:
            self._store[key] = []
        for v in values:
            self._store[key].append(self._encode(v))
        return len(self._store[key])

    async def ltrim(self, key: str, start: int, end: int) -> None:
        lst = self._store.get(key, [])
        if isinstance(lst, list):
            self._store[key] = lst[start : end + 1 if end != -1 else None]

    async def lrange(self, key: str, start: int, end: int) -> list:
        lst = self._store.get(key, [])
        if not isinstance(lst, list):
            return []
        return lst[start : end + 1 if end != -1 else None]

    async def llen(self, key: str) -> int:
        lst = self._store.get(key, [])
        return len(lst) if isinstance(lst, list) else 0

    def pipeline(self, transaction: bool = True):
        return _MockPipeline(self)


class _MockPipeline:
    def __init__(self, redis: MockRedis):
        self._redis = redis
        self._ops: list = []

    def rpush(self, key: str, *values):
        self._ops.append(("rpush", key, values))
        return self

    def ltrim(self, key: str, start: int, end: int):
        self._ops.append(("ltrim", key, start, end))
        return self

    def expire(self, key: str, ttl: int):
        self._ops.append(("expire", key, ttl))
        return self

    async def execute(self) -> list:
        results = []
        for op in self._ops:
            if op[0] == "rpush":
                r = await self._redis.rpush(op[1], *op[2])
            elif op[0] == "ltrim":
                await self._redis.ltrim(op[1], op[2], op[3])
                r = None
            elif op[0] == "expire":
                r = await self._redis.expire(op[1], op[2])
            else:
                r = None
            results.append(r)
        return results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a fresh in-memory SQLite engine per test function."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session_factory(db_engine):
    """Return an async session factory bound to the test engine."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False, autoflush=False)
    return factory


@pytest_asyncio.fixture(scope="function")
async def seeded_db(db_engine, db_session_factory, monkeypatch):
    """
    Create all tables, insert canonical seed data, and monkeypatch
    app.db.base so every get_session_context() call uses the in-memory
    engine.
    """
    import app.db.base as base_module
    from app.db.base import Base

    monkeypatch.setattr(base_module, "_engine", db_engine)
    monkeypatch.setattr(base_module, "_session_factory", db_session_factory)

    # ---------- FIX: Import all models BEFORE create_all ----------
    from app.db.models.doctor import Department, Doctor, DoctorSchedule
    from app.db.models.medication import HospitalInfo
    from app.db.models.patient import Patient
    # These imports are required for relationship resolution (billing -> appointment)
    from app.db.models.appointment import Appointment
    from app.db.models.billing import BillingInvoice, InvoiceItem

    # Create tables using the engine (now metadata knows about all models)
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed data
    async with db_session_factory() as session:
        dept = Department(name="Cardiology", floor_location="3rd Floor",
                          phone_extension="301", is_active=True)
        session.add(dept)
        await session.flush()

        doctor = Doctor(
            full_name="Dr. Kamal Rahman", specialization="Cardiologist",
            department_id=dept.department_id, consultation_fee=1200,
            qualification="MBBS, MD", experience_years=20, is_active=True,
        )
        session.add(doctor)
        await session.flush()

        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
            session.add(DoctorSchedule(
                doctor_id=doctor.doctor_id, day_of_week=day,
                start_time=time(9, 0), end_time=time(12, 0),
                slot_duration_min=20, max_appointments=10, is_active=True,
            ))

        patient = Patient(
            patient_id="P-2024-00001", full_name="Tipto Ghosh",
            date_of_birth=date(1990, 5, 15), gender="Male",
            phone="01987654321", is_active=True,
        )
        session.add(patient)

        session.add(HospitalInfo(
            category="contact", topic="Emergency Contacts",
            content="Hospital Emergency Hotline (24/7): 109\nAmbulance: 01711-AMBU",
        ))
        session.add(HospitalInfo(
            category="hours", topic="ICU Visiting Hours",
            content="8 AM - 10 AM and 4 PM - 6 PM daily.",
        ))

        await session.commit()

    return db_session_factory


@pytest.fixture
def mock_redis():
    """Return a fresh MockRedis instance per test."""
    return MockRedis()


@pytest_asyncio.fixture(scope="function")
async def compiled_graph(seeded_db):
    """
    Return a compiled graph using the seeded test DB.
    Imported after seeded_db monkeypatches app.db.base.
    """
    from app.agents.graph import build_graph
    return build_graph(checkpointer=None)