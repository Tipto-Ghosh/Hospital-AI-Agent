from __future__ import annotations
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"]    = "redis://localhost:6379/0"
os.environ["REDIS_PASSWORD"] = ""
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/1"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["JWT_SECRET_KEY"] = "a" * 64

import pytest
import pytest_asyncio
from datetime import date, datetime, timedelta, time as dt_time
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from app.logger import logging
from app.exception import CustomException

_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)
_Session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_ENGINE, expire_on_commit=False, autoflush=False
)


async def _create_tables() -> None:
    from app.db.models.patient import Patient
    from app.db.models.doctor import Department, Doctor, DoctorSchedule
    from app.db.models.appointment import Appointment
    from app.db.models.medical_record import MedicalRecord, LabResult, Prescription
    from app.db.models.billing import BillingInvoice, InvoiceItem
    from app.db.models.medication import Medication, DrugInteraction, HospitalInfo
    from app.db.models.feedback import Feedback, ComplaintTicket
    from app.db.models.audit_log import AuditLog
    from app.db.models.memory import ConversationSession, ConversationMemory, PatientLongTermContext
    from app.db.base import Base
    async with _ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _drop_tables() -> None:
    from app.db.base import Base
    async with _ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def db():
    await _create_tables()
    async with _Session() as session:
        yield session
    await _drop_tables()


# ── Seed helpers ──────────────────────────────────────────────────────────

async def _seed_dept(s: AsyncSession, name: str = "Cardiology") -> "Department":
    from app.db.models.doctor import Department
    d = Department(name=name, is_active=True)
    s.add(d); await s.flush(); return d


async def _seed_doctor(s: AsyncSession, dept_id: int) -> "Doctor":
    from app.db.models.doctor import Doctor
    d = Doctor(full_name="Dr. Rahman", specialization="Cardiologist",
               department_id=dept_id, is_active=True)
    s.add(d); await s.flush(); return d


async def _seed_schedule(
    s: AsyncSession,
    doctor_id: int,
    day: str = "Monday",
    start: str = "09:00",
    end: str = "17:00",
    slot_min: int = 20,
    max_appts: int = 24,
) -> "DoctorSchedule":
    from app.db.models.doctor import DoctorSchedule
    h_s, m_s = map(int, start.split(":"))
    h_e, m_e = map(int, end.split(":"))
    sched = DoctorSchedule(
        doctor_id=doctor_id, day_of_week=day,
        start_time=dt_time(h_s, m_s), end_time=dt_time(h_e, m_e),
        slot_duration_min=slot_min, max_appointments=max_appts, is_active=True,
    )
    s.add(sched); await s.flush(); return sched


async def _seed_patient(s: AsyncSession, pid: str = "P-0001", phone: str = "01987654321"):
    from app.db.models.patient import Patient
    p = Patient(patient_id=pid, full_name="Tipto Ghosh",
                date_of_birth=date(1990, 5, 15), gender="Male",
                phone=phone, is_active=True)
    s.add(p); await s.flush(); return p


def _next_weekday(day_name: str, min_days: int = 3) -> date:
    """Return next calendar date matching day_name, at least min_days ahead."""
    days = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    target = days.index(day_name)
    today = datetime.utcnow().date()
    delta = (target - today.weekday() + 7) % 7 or 7
    while delta < min_days:
        delta += 7
    return today + timedelta(days=delta)


# ══════════════════════════════════════════════════════════════════════════ #
# STEP 16 — Seed Script
# ══════════════════════════════════════════════════════════════════════════ #

class TestSeedScript:
    """Unit tests for the seed_db.py helper functions."""

    def test_split_statements_basic(self):
        from scripts.seed_db import _split_statements
        sql = """
        -- comment
        INSERT INTO departments (name) VALUES ('Cardiology');
        INSERT INTO departments (name) VALUES ('Neurology');
        """
        stmts = _split_statements(sql)
        assert len(stmts) == 2
        assert all("INSERT" in s for s in stmts)

    def test_split_statements_strips_comments(self):
        from scripts.seed_db import _split_statements
        sql = "-- full line comment\nSELECT 1;"
        stmts = _split_statements(sql)
        assert len(stmts) == 1
        assert stmts[0] == "SELECT 1;"

    def test_split_statements_multiline_insert(self):
        from scripts.seed_db import _split_statements
        sql = """
        INSERT INTO departments
            (name, floor_location)
        VALUES
            ('Emergency', 'Ground Floor');
        """
        stmts = _split_statements(sql)
        assert len(stmts) == 1
        assert "Emergency" in stmts[0]

    def test_split_statements_skips_empty(self):
        from scripts.seed_db import _split_statements
        sql = "\n\n-- just comments\n\n"
        stmts = _split_statements(sql)
        assert stmts == []

    def test_split_statements_block_comment_stripped(self):
        from scripts.seed_db import _split_statements
        sql = "/* block comment */ INSERT INTO foo (x) VALUES (1);"
        stmts = _split_statements(sql)
        assert len(stmts) == 1
        assert "INSERT" in stmts[0]

    def test_seed_files_exist(self):
        from scripts.seed_db import SEED_DIR, SEED_FILES
        for filename, _ in SEED_FILES:
            path = SEED_DIR / filename
            assert path.exists(), f"Missing seed file: {path}"

    def test_seed_files_in_correct_order(self):
        from scripts.seed_db import SEED_FILES
        names = [f for f, _ in SEED_FILES]
        assert names.index("departments.sql") < names.index("doctors.sql")

    @pytest.mark.asyncio
    async def test_table_has_rows_empty(self, db: AsyncSession):
        from scripts.seed_db import _table_has_rows
        result = await _table_has_rows(db, "departments")
        assert result is False

    @pytest.mark.asyncio
    async def test_table_has_rows_after_insert(self, db: AsyncSession):
        from scripts.seed_db import _table_has_rows
        await _seed_dept(db, "Cardiology")
        await db.commit()
        result = await _table_has_rows(db, "departments")
        assert result is True

    @pytest.mark.asyncio
    async def test_dry_run_skips_writes(self, db: AsyncSession):
        import tempfile
        from scripts.seed_db import _seed_file, _table_has_rows
        sql = "INSERT INTO hospital_info (category, topic, content) VALUES ('faq', 'Test', 'Test content');"
        with tempfile.NamedTemporaryFile(suffix=".sql", mode="w", delete=False) as f:
            f.write(sql)
            tmp_path = Path(f.name)
        try:
            name, status = await _seed_file(
                session=db, sql_file=tmp_path,
                guard_table="hospital_info", force=False, dry_run=True,
            )
            assert status == "dry_run"
            has_rows = await _table_has_rows(db, "hospital_info")
            assert has_rows is False
        finally:
            tmp_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_skip_when_table_has_rows(self, db: AsyncSession):
        import tempfile
        from scripts.seed_db import _seed_file
        from app.db.models.medication import HospitalInfo
        db.add(HospitalInfo(category="faq", topic="Existing", content="Already there"))
        await db.commit()
        sql = "INSERT INTO hospital_info (category, topic, content) VALUES ('faq', 'New', 'New content');"
        with tempfile.NamedTemporaryFile(suffix=".sql", mode="w", delete=False) as f:
            f.write(sql)
            tmp_path = Path(f.name)
        try:
            name, status = await _seed_file(
                session=db, sql_file=tmp_path,
                guard_table="hospital_info", force=False,
            )
            assert status == "skipped"
        finally:
            tmp_path.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════ #
# STEP 17 — AppointmentRepository
# ══════════════════════════════════════════════════════════════════════════ #

@pytest.mark.asyncio
class TestGetById:

    async def test_returns_none_for_missing(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        repo = AppointmentRepository(db)
        result = await repo.get_by_id("APT-NOTEXIST-0001")
        assert result is None

    async def test_returns_appointment(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        from app.db.models.appointment import Appointment
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db)
        appt = Appointment(
            appointment_id="APT-TEST-0001",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=datetime.utcnow() + timedelta(days=3),
            status="pending", booked_via="ai_agent",
        )
        db.add(appt); await db.commit()
        repo = AppointmentRepository(db)
        result = await repo.get_by_id("APT-TEST-0001")
        assert result is not None
        assert result.status == "pending"

    async def test_load_relations(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        from app.db.models.appointment import Appointment
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db)
        db.add(Appointment(
            appointment_id="APT-REL-0001",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=datetime.utcnow() + timedelta(days=2),
            status="pending", booked_via="ai_agent",
        ))
        await db.commit()
        repo = AppointmentRepository(db)
        result = await repo.get_by_id("APT-REL-0001", load_relations=True)
        assert result.doctor.full_name == "Dr. Rahman"
        assert result.patient.full_name == "Tipto Ghosh"


@pytest.mark.asyncio
class TestGetByPatient:

    async def test_returns_all_appointments(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        from app.db.models.appointment import Appointment
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db)
        for i, status in enumerate(["pending", "confirmed", "cancelled"]):
            db.add(Appointment(
                appointment_id=f"APT-ALL-{i:04d}",
                patient_id=pat.patient_id, doctor_id=doc.doctor_id,
                scheduled_at=datetime.utcnow() + timedelta(days=i+1),
                status=status, booked_via="ai_agent",
            ))
        await db.commit()
        repo = AppointmentRepository(db)
        results = await repo.get_by_patient(pat.patient_id)
        assert len(results) == 3

    async def test_filter_by_status(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        from app.db.models.appointment import Appointment
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db)
        for i, status in enumerate(["pending", "confirmed", "cancelled"]):
            db.add(Appointment(
                appointment_id=f"APT-ST-{i:04d}",
                patient_id=pat.patient_id, doctor_id=doc.doctor_id,
                scheduled_at=datetime.utcnow() + timedelta(days=i+1),
                status=status, booked_via="ai_agent",
            ))
        await db.commit()
        repo = AppointmentRepository(db)
        pending = await repo.get_by_patient(pat.patient_id, status="pending")
        assert len(pending) == 1
        assert pending[0].status == "pending"

    async def test_upcoming_only_filter(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        from app.db.models.appointment import Appointment
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db)
        db.add(Appointment(
            appointment_id="APT-PAST-0001",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=datetime.utcnow() - timedelta(days=2),
            status="completed", booked_via="ai_agent",
        ))
        db.add(Appointment(
            appointment_id="APT-FUTURE-0001",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=datetime.utcnow() + timedelta(days=3),
            status="pending", booked_via="ai_agent",
        ))
        await db.commit()
        repo = AppointmentRepository(db)
        upcoming = await repo.get_by_patient(pat.patient_id, upcoming_only=True)
        assert len(upcoming) == 1
        assert upcoming[0].appointment_id == "APT-FUTURE-0001"


@pytest.mark.asyncio
class TestGetAvailableSlots:

    async def test_returns_slots_for_scheduled_day(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept  = await _seed_dept(db)
        doc   = await _seed_doctor(db, dept.department_id)
        monday = _next_weekday("Monday")
        await _seed_schedule(db, doc.doctor_id, day="Monday",
                              start="09:00", end="11:00", slot_min=20)
        await db.commit()
        repo  = AppointmentRepository(db)
        slots = await repo.get_available_slots(doc.doctor_id, monday, slot_buffer_hours=0)
        assert len(slots) == 6
        assert all(s.is_available for s in slots)
        assert all(s.slot_minutes == 20 for s in slots)

    async def test_returns_empty_for_unscheduled_day(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept  = await _seed_dept(db)
        doc   = await _seed_doctor(db, dept.department_id)
        await _seed_schedule(db, doc.doctor_id, day="Monday")
        await db.commit()
        sunday = _next_weekday("Sunday")
        repo  = AppointmentRepository(db)
        slots = await repo.get_available_slots(doc.doctor_id, sunday, slot_buffer_hours=0)
        assert slots == []

    async def test_booked_slot_excluded(self, db: AsyncSession):
        from app.db.models.appointment import Appointment
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept  = await _seed_dept(db)
        doc   = await _seed_doctor(db, dept.department_id)
        pat   = await _seed_patient(db)
        monday = _next_weekday("Monday")
        await _seed_schedule(db, doc.doctor_id, day="Monday",
                              start="09:00", end="10:00", slot_min=20)
        db.add(Appointment(
            appointment_id="APT-BKD-0001",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=datetime.combine(monday, dt_time(9, 0)),
            status="confirmed", booked_via="ai_agent",
        ))
        await db.commit()
        repo  = AppointmentRepository(db)
        slots = await repo.get_available_slots(doc.doctor_id, monday, slot_buffer_hours=0)
        assert len(slots) == 2
        slot_times = [s.starts_at.hour * 60 + s.starts_at.minute for s in slots]
        assert 9 * 60 not in slot_times

    async def test_slot_dataclass_fields(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept  = await _seed_dept(db)
        doc   = await _seed_doctor(db, dept.department_id)
        monday = _next_weekday("Monday")
        await _seed_schedule(db, doc.doctor_id, day="Monday",
                              start="09:00", end="09:20", slot_min=20)
        await db.commit()
        repo  = AppointmentRepository(db)
        slots = await repo.get_available_slots(doc.doctor_id, monday, slot_buffer_hours=0)
        assert len(slots) == 1
        s = slots[0]
        assert s.ends_at == s.starts_at + timedelta(minutes=20)
        assert s.slot_minutes == 20
        assert s.is_available is True


@pytest.mark.asyncio
class TestCreate:

    async def test_creates_appointment(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept  = await _seed_dept(db)
        doc   = await _seed_doctor(db, dept.department_id)
        pat   = await _seed_patient(db)
        monday = _next_weekday("Monday")
        await _seed_schedule(db, doc.doctor_id, day="Monday")
        await db.commit()
        scheduled = datetime.combine(monday, dt_time(10, 0))
        repo  = AppointmentRepository(db)
        appt  = await repo.create(pat.patient_id, doc.doctor_id, scheduled, reason="Chest pain")
        assert appt.appointment_id.startswith("APT-")
        assert appt.status == "pending"
        assert appt.reason_for_visit == "Chest pain"

    async def test_id_format(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept  = await _seed_dept(db)
        doc   = await _seed_doctor(db, dept.department_id)
        pat   = await _seed_patient(db)
        monday = _next_weekday("Monday")
        await _seed_schedule(db, doc.doctor_id, day="Monday")
        await db.commit()
        scheduled = datetime.combine(monday, dt_time(9, 0))
        repo  = AppointmentRepository(db)
        appt  = await repo.create(pat.patient_id, doc.doctor_id, scheduled)
        import re
        assert re.match(r"APT-\d{8}-\d{4}", appt.appointment_id)

    async def test_rejects_within_2h(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db)
        await _seed_schedule(db, doc.doctor_id, day=datetime.utcnow().strftime("%A"))
        await db.commit()
        too_soon = datetime.utcnow() + timedelta(hours=1)
        repo = AppointmentRepository(db)
        with pytest.raises(CustomException, match="at least 2 hours"):
            await repo.create(pat.patient_id, doc.doctor_id, too_soon)

    async def test_rejects_duplicate_slot(self, db: AsyncSession):
        from app.db.models.appointment import Appointment
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept  = await _seed_dept(db)
        doc   = await _seed_doctor(db, dept.department_id)
        pat1  = await _seed_patient(db, pid="P-DUP1", phone="01900000001")
        pat2  = await _seed_patient(db, pid="P-DUP2", phone="01900000002")
        monday = _next_weekday("Monday")
        await _seed_schedule(db, doc.doctor_id, day="Monday")
        slot = datetime.combine(monday, dt_time(10, 0))
        db.add(Appointment(
            appointment_id="APT-DUP-0001",
            patient_id=pat1.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=slot, status="confirmed", booked_via="ai_agent",
        ))
        await db.commit()
        repo = AppointmentRepository(db)
        with pytest.raises(CustomException, match="already booked"):
            await repo.create(pat2.patient_id, doc.doctor_id, slot)

    async def test_rejects_second_active_appt_same_doctor(self, db: AsyncSession):
        from app.db.models.appointment import Appointment
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept  = await _seed_dept(db)
        doc   = await _seed_doctor(db, dept.department_id)
        pat   = await _seed_patient(db)
        monday = _next_weekday("Monday")
        next_monday = monday + timedelta(days=7)
        await _seed_schedule(db, doc.doctor_id, day="Monday")
        slot1 = datetime.combine(monday, dt_time(9, 0))
        slot2 = datetime.combine(next_monday, dt_time(9, 0))
        db.add(Appointment(
            appointment_id="APT-DUP2-0001",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=slot1, status="pending", booked_via="ai_agent",
        ))
        await db.commit()
        repo = AppointmentRepository(db)
        with pytest.raises(CustomException, match="already has an active"):
            await repo.create(pat.patient_id, doc.doctor_id, slot2)


@pytest.mark.asyncio
class TestCancel:

    async def test_cancel_sets_status(self, db: AsyncSession):
        from app.db.models.appointment import Appointment
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db)
        appt = Appointment(
            appointment_id="APT-CAN-0001",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=datetime.utcnow() + timedelta(days=3),
            status="pending", booked_via="ai_agent",
        )
        db.add(appt); await db.commit()
        repo = AppointmentRepository(db)
        cancelled = await repo.cancel("APT-CAN-0001", reason="Patient request")
        assert cancelled.status == "cancelled"
        assert cancelled.cancellation_reason == "Patient request"
        assert cancelled.cancelled_at is not None

    async def test_cancel_row_still_exists(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.appointment import Appointment
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db)
        db.add(Appointment(
            appointment_id="APT-CAN-0002",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=datetime.utcnow() + timedelta(days=3),
            status="pending", booked_via="ai_agent",
        ))
        await db.commit()
        repo = AppointmentRepository(db)
        await repo.cancel("APT-CAN-0002")
        row = (await db.execute(
            select(Appointment).where(Appointment.appointment_id == "APT-CAN-0002")
        )).scalar_one_or_none()
        assert row is not None
        assert row.status == "cancelled"

    async def test_cancel_missing_appointment(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        repo = AppointmentRepository(db)
        with pytest.raises(CustomException, match="not found"):
            await repo.cancel("APT-GHOST-9999")

    async def test_cancel_within_24h_raises(self, db: AsyncSession):
        from app.db.models.appointment import Appointment
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db)
        db.add(Appointment(
            appointment_id="APT-LATE-0001",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=datetime.utcnow() + timedelta(hours=6),
            status="pending", booked_via="ai_agent",
        ))
        await db.commit()
        repo = AppointmentRepository(db)
        with pytest.raises(CustomException):
            await repo.cancel("APT-LATE-0001")


@pytest.mark.asyncio
class TestReschedule:

    async def test_reschedule_creates_new_cancels_old(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.appointment import Appointment
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept  = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat   = await _seed_patient(db)
        monday  = _next_weekday("Monday")
        tuesday = _next_weekday("Tuesday")
        await _seed_schedule(db, doc.doctor_id, day="Monday")
        await _seed_schedule(db, doc.doctor_id, day="Tuesday")
        old_slot = datetime.combine(monday, dt_time(9, 0))
        new_slot = datetime.combine(tuesday, dt_time(10, 0))
        db.add(Appointment(
            appointment_id="APT-RSCH-0001",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=old_slot, status="pending", booked_via="ai_agent",
        ))
        await db.commit()
        repo = AppointmentRepository(db)
        new_appt = await repo.reschedule("APT-RSCH-0001", new_slot)
        assert new_appt.status == "pending"
        assert new_appt.scheduled_at == new_slot
        old = (await db.execute(
            select(Appointment).where(Appointment.appointment_id == "APT-RSCH-0001")
        )).scalar_one()
        assert old.status == "cancelled"

    async def test_reschedule_new_slot_unavailable_rollback(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.appointment import Appointment
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept  = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat1  = await _seed_patient(db, pid="P-RS1", phone="01911000001")
        pat2  = await _seed_patient(db, pid="P-RS2", phone="01911000002")
        monday = _next_weekday("Monday")
        await _seed_schedule(db, doc.doctor_id, day="Monday")
        slot_a = datetime.combine(monday, dt_time(9, 0))
        slot_b = datetime.combine(monday, dt_time(9, 20))
        db.add(Appointment(
            appointment_id="APT-RS-A",
            patient_id=pat1.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=slot_a, status="pending", booked_via="ai_agent",
        ))
        db.add(Appointment(
            appointment_id="APT-RS-B",
            patient_id=pat2.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=slot_b, status="confirmed", booked_via="ai_agent",
        ))
        await db.commit()
        repo = AppointmentRepository(db)
        with pytest.raises(CustomException, match="already booked"):
            await repo.reschedule("APT-RS-A", slot_b)
        original = (await db.execute(
            select(Appointment).where(Appointment.appointment_id == "APT-RS-A")
        )).scalar_one()
        assert original.status == "pending"

    async def test_reschedule_missing_appointment(self, db: AsyncSession):
        from app.db.repositories.appointment_repo import AppointmentRepository
        repo = AppointmentRepository(db)
        with pytest.raises(CustomException, match="not found"):
            await repo.reschedule("APT-GHOST", datetime.utcnow() + timedelta(days=5))


@pytest.mark.asyncio
class TestConfirm:

    async def test_confirm_pending_to_confirmed(self, db: AsyncSession):
        from app.db.models.appointment import Appointment
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db)
        db.add(Appointment(
            appointment_id="APT-CONF-0001",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=datetime.utcnow() + timedelta(days=2),
            status="pending", booked_via="ai_agent",
        ))
        await db.commit()
        repo = AppointmentRepository(db)
        confirmed = await repo.confirm("APT-CONF-0001")
        assert confirmed.status == "confirmed"

    async def test_confirm_non_pending_raises(self, db: AsyncSession):
        from app.db.models.appointment import Appointment
        from app.db.repositories.appointment_repo import AppointmentRepository
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db)
        db.add(Appointment(
            appointment_id="APT-CONF-0002",
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            scheduled_at=datetime.utcnow() + timedelta(days=2),
            status="cancelled", booked_via="ai_agent",
        ))
        await db.commit()
        repo = AppointmentRepository(db)
        with pytest.raises(CustomException, match="pending"):
            await repo.confirm("APT-CONF-0002")