from __future__ import annotations

import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["REDIS_PASSWORD"] = ""
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/1"
os.environ["GROQ_API_KEY"] = "gsk_test_placeholder_not_real"
os.environ["JWT_SECRET_KEY"] = "a" * 64

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool


_TEST_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)
_TestSession: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_TEST_ENGINE, expire_on_commit=False, autoflush=False
)


async def _create_tables() -> None:
    # Import ALL models so every table is registered on Base.metadata
    from app.db.models.patient import Patient                          # noqa: F401
    from app.db.models.doctor import Department, Doctor, DoctorSchedule  # noqa: F401
    from app.db.models.appointment import Appointment                  # noqa: F401
    from app.db.models.medical_record import (                         # noqa: F401
        MedicalRecord, LabResult, Prescription,
    )
    from app.db.base import Base
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _drop_tables() -> None:
    from app.db.base import Base
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)



class TestConfig:

    def setup_method(self):
        from app.config import get_settings
        get_settings.cache_clear()

    def test_settings_load(self):
        from app.config import get_settings
        assert get_settings() is not None

    def test_hospital_name(self):
        from app.config import get_settings
        assert len(get_settings().HOSPITAL_NAME) > 0

    def test_db_computed_async_url(self):
        from app.config import get_settings
        assert "://" in get_settings().db.DATABASE_URL_ASYNC

    def test_db_computed_sync_url(self):
        from app.config import get_settings
        assert isinstance(get_settings().db.DATABASE_URL_SYNC, str)

    def test_llm_models_populated(self):
        from app.config import get_settings
        s = get_settings().llm
        assert s.LLM_FAST_MODEL and s.LLM_CAPABLE_MODEL and s.LLM_HEAVY_MODEL

    def test_redis_ttl_positive(self):
        from app.config import get_settings
        assert get_settings().redis.SESSION_TTL_MINUTES > 0

    def test_security_jwt_key_length(self):
        from app.config import get_settings
        assert len(get_settings().security.JWT_SECRET_KEY) >= 32

    def test_observability_booleans(self):
        from app.config import get_settings
        s = get_settings().obs
        assert isinstance(s.langfuse_enabled, bool)
        assert isinstance(s.langsmith_enabled, bool)

    def test_is_development(self):
        from app.config import get_settings
        s = get_settings()
        assert s.is_development is True and s.is_production is False

    def test_singleton_cached(self):
        from app.config import get_settings
        assert get_settings() is get_settings()


@pytest.mark.asyncio
class TestBase:

    async def test_engine_connects(self):
        from sqlalchemy import text
        async with _TEST_ENGINE.connect() as conn:
            assert (await conn.execute(text("SELECT 1"))).scalar() == 1

    async def test_base_is_declarative(self):
        from app.db.base import Base
        from sqlalchemy.orm import DeclarativeBase
        assert issubclass(Base, DeclarativeBase)

    async def test_all_tables_registered(self):
        await _create_tables()
        from app.db.base import Base
        names = set(Base.metadata.tables.keys())
        expected = {
            "patients", "doctors", "departments", "doctor_schedules",
            "appointments", "medical_records", "lab_results", "prescriptions",
        }
        assert expected <= names, f"Missing tables: {expected - names}"
        await _drop_tables()

    async def test_session_factory_yields_session(self):
        async with _TestSession() as s:
            assert isinstance(s, AsyncSession)


class TestSession:

    def test_get_db_callable(self):
        from app.db.session import get_db
        assert callable(get_db)

    def test_session_context_callable(self):
        from app.db.session import session_context
        assert callable(session_context)

    def test_async_session_local_callable(self):
        from app.db.session import AsyncSessionLocal
        assert callable(AsyncSessionLocal)

    def test_all_in_dunder_all(self):
        import app.db.session as m
        for name in ("get_db", "session_context", "AsyncSessionLocal"):
            assert name in m.__all__


@pytest_asyncio.fixture(scope="function")
async def db():
    await _create_tables()
    async with _TestSession() as session:
        yield session
    await _drop_tables()


async def _seed_dept(session: AsyncSession):
    from app.db.models.doctor import Department
    d = Department(name="Cardiology", is_active=True)
    session.add(d)
    await session.flush()
    return d


async def _seed_doctor(session: AsyncSession, dept_id: int):
    from app.db.models.doctor import Doctor
    d = Doctor(
        full_name="Dr. Rahman", specialization="Cardiologist",
        department_id=dept_id, is_active=True,
    )
    session.add(d)
    await session.flush()
    return d


async def _seed_patient(session: AsyncSession, pid: str = "P-2024-00001",
                         phone: str = "01987654321"):
    from datetime import date
    from app.db.models.patient import Patient
    p = Patient(
        patient_id=pid, full_name="Tipto Ghosh",
        date_of_birth=date(1990, 5, 15), gender="Male",
        phone=phone, is_active=True,
    )
    session.add(p)
    await session.flush()
    return p


@pytest.mark.asyncio
class TestPatient:

    async def test_insert_select(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.patient import Patient
        p = await _seed_patient(db)
        await db.commit()
        row = (await db.execute(
            select(Patient).where(Patient.patient_id == p.patient_id)
        )).scalar_one()
        assert row.full_name == "Tipto Ghosh"

    async def test_phone_unique(self, db: AsyncSession):
        from datetime import date
        from sqlalchemy.exc import IntegrityError
        from app.db.models.patient import Patient
        db.add(Patient(patient_id="P-A", full_name="A", date_of_birth=date(1990,1,1),
                       gender="Male", phone="01111111111"))
        await db.flush()
        db.add(Patient(patient_id="P-B", full_name="B", date_of_birth=date(1991,1,1),
                       gender="Female", phone="01111111111"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_soft_delete(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.patient import Patient
        p = await _seed_patient(db, pid="P-SOFT", phone="01999000001")
        p.is_active = False
        await db.commit()
        row = (await db.execute(
            select(Patient).where(Patient.patient_id == "P-SOFT")
        )).scalar_one()
        assert row.is_active is False

    async def test_repr(self, db: AsyncSession):
        p = await _seed_patient(db)
        assert "Tipto Ghosh" in repr(p)


@pytest.mark.asyncio
class TestDoctor:

    async def test_insert_and_department_fk(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.doctor import Doctor
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        await db.commit()
        row = (await db.execute(
            select(Doctor).where(Doctor.doctor_id == doc.doctor_id)
        )).scalar_one()
        assert row.specialization == "Cardiologist"
        assert row.department_id == dept.department_id

    async def test_schedule_insert(self, db: AsyncSession):
        from datetime import time
        from app.db.models.doctor import DoctorSchedule
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        sched = DoctorSchedule(
            doctor_id=doc.doctor_id, day_of_week="Wednesday",
            start_time=time(9, 0), end_time=time(14, 0),
            slot_duration_min=20, max_appointments=15, is_active=True,
        )
        db.add(sched)
        await db.commit()
        await db.refresh(sched)
        assert sched.schedule_id is not None
        assert sched.day_of_week == "Wednesday"

    async def test_repr(self, db: AsyncSession):
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        assert "Dr. Rahman" in repr(doc)



@pytest.mark.asyncio
class TestAppointment:

    async def _seed_appt(self, db: AsyncSession, appt_id: str,
                          scheduled_at, status: str = "pending"):
        from app.db.models.appointment import Appointment
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid=f"P-{appt_id}", phone=f"019{appt_id[:8]}")
        appt = Appointment(
            appointment_id=appt_id,
            patient_id=pat.patient_id,
            doctor_id=doc.doctor_id,
            scheduled_at=scheduled_at,
            duration_min=20,
            status=status,
            booked_via="ai_agent",
        )
        db.add(appt)
        await db.flush()
        return appt, pat, doc

    async def test_insert_and_select(self, db: AsyncSession):
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from app.db.models.appointment import Appointment
        future = datetime.utcnow() + timedelta(days=3)
        appt, _, _ = await self._seed_appt(db, "APT-001", future)
        await db.commit()
        row = (await db.execute(
            select(Appointment).where(Appointment.appointment_id == "APT-001")
        )).scalar_one()
        assert row.status == "pending"
        assert row.doctor_id == appt.doctor_id

    async def test_composite_indexes_exist(self, db: AsyncSession):
        """Verify the two composite indexes are present on the appointments table."""
        from app.db.base import Base
        appt_table = Base.metadata.tables["appointments"]
        index_names = {idx.name for idx in appt_table.indexes}
        assert "idx_doctor_datetime" in index_names
        assert "idx_patient_status" in index_names

    async def test_is_cancellable_far_future(self, db: AsyncSession):
        """Appointment >24h away should be cancellable."""
        from datetime import datetime, timedelta
        future = datetime.utcnow() + timedelta(days=5)
        appt, _, _ = await self._seed_appt(db, "APT-002", future)
        assert appt.is_cancellable() is True

    async def test_is_cancellable_within_24h(self, db: AsyncSession):
        """Appointment <24h away should NOT be cancellable."""
        from datetime import datetime, timedelta
        soon = datetime.utcnow() + timedelta(hours=6)
        appt, _, _ = await self._seed_appt(db, "APT-003", soon)
        assert appt.is_cancellable() is False

    async def test_is_cancellable_already_cancelled(self, db: AsyncSession):
        """Cancelled appointment is never cancellable again."""
        from datetime import datetime, timedelta
        future = datetime.utcnow() + timedelta(days=5)
        appt, _, _ = await self._seed_appt(db, "APT-004", future, status="cancelled")
        assert appt.is_cancellable() is False

    async def test_is_upcoming_future(self, db: AsyncSession):
        from datetime import datetime, timedelta
        future = datetime.utcnow() + timedelta(days=2)
        appt, _, _ = await self._seed_appt(db, "APT-005", future)
        assert appt.is_upcoming() is True

    async def test_is_upcoming_past(self, db: AsyncSession):
        from datetime import datetime, timedelta
        past = datetime.utcnow() - timedelta(days=2)
        appt, _, _ = await self._seed_appt(db, "APT-006", past)
        assert appt.is_upcoming() is False

    async def test_is_upcoming_cancelled(self, db: AsyncSession):
        from datetime import datetime, timedelta
        future = datetime.utcnow() + timedelta(days=2)
        appt, _, _ = await self._seed_appt(db, "APT-007", future, status="cancelled")
        assert appt.is_upcoming() is False

    async def test_status_soft_cancel(self, db: AsyncSession):
        """Cancellation sets status field — never deletes the row."""
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from app.db.models.appointment import Appointment
        future = datetime.utcnow() + timedelta(days=5)
        appt, _, _ = await self._seed_appt(db, "APT-008", future)
        appt.status = "cancelled"
        appt.cancellation_reason = "Patient request"
        appt.cancelled_at = datetime.utcnow()
        await db.commit()
        row = (await db.execute(
            select(Appointment).where(Appointment.appointment_id == "APT-008")
        )).scalar_one()
        assert row.status == "cancelled"
        assert row.cancellation_reason == "Patient request"
        assert row is not None  # row still exists — not deleted

    async def test_repr(self, db: AsyncSession):
        from datetime import datetime, timedelta
        future = datetime.utcnow() + timedelta(days=1)
        appt, _, _ = await self._seed_appt(db, "APT-009", future)
        r = repr(appt)
        assert "APT-009" in r and "pending" in r

    async def test_back_ref_patient_appointments(self, db: AsyncSession):
        """patient.appointments back-reference resolves after Appointment import."""
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.patient import Patient
        future = datetime.utcnow() + timedelta(days=3)
        appt, pat, _ = await self._seed_appt(db, "APT-010", future)
        await db.commit()
        result = await db.execute(
            select(Patient)
            .where(Patient.patient_id == pat.patient_id)
            .options(selectinload(Patient.appointments))
        )
        loaded_patient = result.scalar_one()
        assert len(loaded_patient.appointments) == 1
        assert loaded_patient.appointments[0].appointment_id == "APT-010"

    async def test_back_ref_doctor_appointments(self, db: AsyncSession):
        """doctor.appointments back-reference resolves after Appointment import."""
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.doctor import Doctor
        future = datetime.utcnow() + timedelta(days=3)
        appt, _, doc = await self._seed_appt(db, "APT-011", future)
        await db.commit()
        result = await db.execute(
            select(Doctor)
            .where(Doctor.doctor_id == doc.doctor_id)
            .options(selectinload(Doctor.appointments))
        )
        loaded_doc = result.scalar_one()
        assert any(a.appointment_id == "APT-011" for a in loaded_doc.appointments)


@pytest.mark.asyncio
class TestMedicalRecord:

    async def test_insert_and_select(self, db: AsyncSession):
        from datetime import date
        from sqlalchemy import select
        from app.db.models.medical_record import MedicalRecord
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid="P-MR-001", phone="01700000001")
        rec = MedicalRecord(
            patient_id=pat.patient_id,
            doctor_id=doc.doctor_id,
            visit_date=date(2024, 3, 15),
            chief_complaint="Chest tightness",
            diagnosis="Stable angina",
            treatment_plan="Lifestyle changes + medication",
            follow_up_date=date(2024, 4, 15),
        )
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        row = (await db.execute(
            select(MedicalRecord).where(MedicalRecord.record_id == rec.record_id)
        )).scalar_one()
        assert row.diagnosis == "Stable angina"
        assert row.follow_up_date == date(2024, 4, 15)

    async def test_appointment_id_nullable(self, db: AsyncSession):
        """MedicalRecord can exist without a linked appointment (e.g. emergency)."""
        from datetime import date
        from app.db.models.medical_record import MedicalRecord
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid="P-MR-002", phone="01700000002")
        rec = MedicalRecord(
            patient_id=pat.patient_id,
            doctor_id=doc.doctor_id,
            visit_date=date(2024, 1, 10),
            appointment_id=None,  # deliberately None
        )
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        assert rec.appointment_id is None

    async def test_back_ref_patient_medical_records(self, db: AsyncSession):
        from datetime import date
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.medical_record import MedicalRecord
        from app.db.models.patient import Patient
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid="P-MR-003", phone="01700000003")
        db.add(MedicalRecord(
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            visit_date=date(2024, 2, 1),
        ))
        await db.commit()
        result = await db.execute(
            select(Patient).where(Patient.patient_id == pat.patient_id)
            .options(selectinload(Patient.medical_records))
        )
        loaded = result.scalar_one()
        assert len(loaded.medical_records) == 1

    async def test_repr(self, db: AsyncSession):
        from datetime import date
        from app.db.models.medical_record import MedicalRecord
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid="P-MR-004", phone="01700000004")
        rec = MedicalRecord(
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            visit_date=date(2024, 5, 1),
        )
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        assert "P-MR-004" in repr(rec)


@pytest.mark.asyncio
class TestLabResult:

    async def test_insert_normal_result(self, db: AsyncSession):
        from datetime import date
        from sqlalchemy import select
        from app.db.models.medical_record import LabResult
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid="P-LAB-001", phone="01800000001")
        lr = LabResult(
            patient_id=pat.patient_id,
            test_name="HbA1c",
            test_date=date(2024, 4, 10),
            result_value="5.4%",
            unit="%",
            reference_range="4.0–5.6%",
            is_abnormal=False,
            ordered_by_doctor=doc.doctor_id,
        )
        db.add(lr)
        await db.commit()
        await db.refresh(lr)
        row = (await db.execute(
            select(LabResult).where(LabResult.result_id == lr.result_id)
        )).scalar_one()
        assert row.test_name == "HbA1c"
        assert row.is_abnormal is False

    async def test_insert_abnormal_result(self, db: AsyncSession):
        from datetime import date
        from sqlalchemy import select
        from app.db.models.medical_record import LabResult
        pat = await _seed_patient(db, pid="P-LAB-002", phone="01800000002")
        lr = LabResult(
            patient_id=pat.patient_id,
            test_name="Blood Glucose (Fasting)",
            test_date=date(2024, 4, 11),
            result_value="210 mg/dL",
            unit="mg/dL",
            reference_range="70–100 mg/dL",
            is_abnormal=True,
        )
        db.add(lr)
        await db.commit()
        await db.refresh(lr)
        assert lr.is_abnormal is True
        assert "⚠ABNORMAL" in repr(lr)

    async def test_back_ref_patient_lab_results(self, db: AsyncSession):
        from datetime import date
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.medical_record import LabResult
        from app.db.models.patient import Patient
        pat = await _seed_patient(db, pid="P-LAB-003", phone="01800000003")
        db.add(LabResult(patient_id=pat.patient_id, test_name="CBC",
                         test_date=date(2024, 3, 1), is_abnormal=False))
        db.add(LabResult(patient_id=pat.patient_id, test_name="LFT",
                         test_date=date(2024, 3, 2), is_abnormal=True))
        await db.commit()
        result = await db.execute(
            select(Patient).where(Patient.patient_id == pat.patient_id)
            .options(selectinload(Patient.lab_results))
        )
        loaded = result.scalar_one()
        assert len(loaded.lab_results) == 2
        abnormal_count = sum(1 for r in loaded.lab_results if r.is_abnormal)
        assert abnormal_count == 1


@pytest.mark.asyncio
class TestPrescription:

    async def test_insert_active_prescription(self, db: AsyncSession):
        from datetime import date
        from sqlalchemy import select
        from app.db.models.medical_record import Prescription
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid="P-RX-001", phone="01900000001")
        rx = Prescription(
            patient_id=pat.patient_id,
            doctor_id=doc.doctor_id,
            prescribed_date=date(2024, 3, 1),
            medication_name="Metformin",
            dosage="500mg",
            frequency="twice daily",
            duration_days=90,
            is_active=True,
        )
        db.add(rx)
        await db.commit()
        await db.refresh(rx)
        row = (await db.execute(
            select(Prescription).where(Prescription.prescription_id == rx.prescription_id)
        )).scalar_one()
        assert row.medication_name == "Metformin"
        assert row.is_active is True

    async def test_deactivate_prescription_never_deletes(self, db: AsyncSession):
        """Stopping a prescription sets is_active=False — row must still exist."""
        from datetime import date
        from sqlalchemy import select
        from app.db.models.medical_record import Prescription
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid="P-RX-002", phone="01900000002")
        rx = Prescription(
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            prescribed_date=date(2024, 1, 1), medication_name="Aspirin",
            dosage="75mg", frequency="once daily", is_active=True,
        )
        db.add(rx)
        await db.commit()
        rx.is_active = False
        await db.commit()
        row = (await db.execute(
            select(Prescription).where(Prescription.prescription_id == rx.prescription_id)
        )).scalar_one()
        assert row is not None
        assert row.is_active is False

    async def test_active_filter(self, db: AsyncSession):
        """Only is_active=True prescriptions appear when filtering for active meds."""
        from datetime import date
        from sqlalchemy import select
        from app.db.models.medical_record import Prescription
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid="P-RX-003", phone="01900000003")
        for name, active in [("DrugA", True), ("DrugB", False), ("DrugC", True)]:
            db.add(Prescription(
                patient_id=pat.patient_id, doctor_id=doc.doctor_id,
                prescribed_date=date(2024, 1, 1), medication_name=name,
                is_active=active,
            ))
        await db.commit()
        active_rows = (await db.execute(
            select(Prescription)
            .where(Prescription.patient_id == pat.patient_id)
            .where(Prescription.is_active.is_(True))
        )).scalars().all()
        assert len(active_rows) == 2
        assert all(r.is_active for r in active_rows)

    async def test_back_refs_patient_and_doctor(self, db: AsyncSession):
        """patient.prescriptions and doctor.prescriptions both resolve."""
        from datetime import date
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.doctor import Doctor
        from app.db.models.medical_record import Prescription
        from app.db.models.patient import Patient
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid="P-RX-004", phone="01900000004")
        db.add(Prescription(
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            prescribed_date=date(2024, 2, 1), medication_name="Lisinopril",
            dosage="10mg", frequency="once daily", is_active=True,
        ))
        await db.commit()

        p_result = await db.execute(
            select(Patient).where(Patient.patient_id == pat.patient_id)
            .options(selectinload(Patient.prescriptions))
        )
        assert len(p_result.scalar_one().prescriptions) == 1

        d_result = await db.execute(
            select(Doctor).where(Doctor.doctor_id == doc.doctor_id)
            .options(selectinload(Doctor.prescriptions))
        )
        assert len(d_result.scalar_one().prescriptions) == 1

    async def test_repr_active(self, db: AsyncSession):
        from datetime import date
        from app.db.models.medical_record import Prescription
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid="P-RX-005", phone="01900000005")
        rx = Prescription(
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            prescribed_date=date(2024, 1, 1), medication_name="Atorvastatin",
            is_active=True,
        )
        db.add(rx)
        await db.commit()
        await db.refresh(rx)
        assert "Atorvastatin" in repr(rx)
        assert "ACTIVE" in repr(rx)

    async def test_repr_inactive(self, db: AsyncSession):
        from datetime import date
        from app.db.models.medical_record import Prescription
        dept = await _seed_dept(db)
        doc = await _seed_doctor(db, dept.department_id)
        pat = await _seed_patient(db, pid="P-RX-006", phone="01900000006")
        rx = Prescription(
            patient_id=pat.patient_id, doctor_id=doc.doctor_id,
            prescribed_date=date(2024, 1, 1), medication_name="OldDrug",
            is_active=False,
        )
        db.add(rx)
        await db.commit()
        await db.refresh(rx)
        assert "inactive" in repr(rx)