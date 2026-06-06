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
from decimal import Decimal
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
    from app.db.models.patient import Patient
    from app.db.models.doctor import Department, Doctor, DoctorSchedule
    from app.db.models.appointment import Appointment
    from app.db.models.medical_record import MedicalRecord, LabResult, Prescription
    from app.db.models.billing import BillingInvoice, InvoiceItem
    from app.db.models.medication import Medication, DrugInteraction, HospitalInfo
    from app.db.base import Base
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _drop_tables() -> None:
    from app.db.base import Base
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _seed_dept(s):
    from app.db.models.doctor import Department
    d = Department(name="Cardiology", is_active=True)
    s.add(d); await s.flush(); return d

async def _seed_doctor(s, dept_id):
    from app.db.models.doctor import Doctor
    d = Doctor(full_name="Dr. Rahman", specialization="Cardiologist",
               department_id=dept_id, is_active=True)
    s.add(d); await s.flush(); return d

async def _seed_patient(s, pid="P-0001", phone="01987654321"):
    from datetime import date
    from app.db.models.patient import Patient
    p = Patient(patient_id=pid, full_name="Tipto Ghosh",
                date_of_birth=date(1990, 5, 15), gender="Male",
                phone=phone, is_active=True)
    s.add(p); await s.flush(); return p

async def _seed_appt(s, appt_id, scheduled_at, patient_id, doctor_id, status="pending"):
    from app.db.models.appointment import Appointment
    a = Appointment(appointment_id=appt_id, patient_id=patient_id,
                    doctor_id=doctor_id, scheduled_at=scheduled_at,
                    duration_min=20, status=status, booked_via="ai_agent")
    s.add(a); await s.flush(); return a


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

    def test_db_async_url(self):
        from app.config import get_settings
        assert "://" in get_settings().db.DATABASE_URL_ASYNC

    def test_db_sync_url(self):
        from app.config import get_settings
        assert isinstance(get_settings().db.DATABASE_URL_SYNC, str)

    def test_llm_models(self):
        from app.config import get_settings
        s = get_settings().llm
        assert s.LLM_FAST_MODEL and s.LLM_CAPABLE_MODEL and s.LLM_HEAVY_MODEL

    def test_redis_ttl(self):
        from app.config import get_settings
        assert get_settings().redis.SESSION_TTL_MINUTES > 0

    def test_jwt_key_length(self):
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
        assert s.is_development and not s.is_production

    def test_singleton(self):
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
            "billing_invoices", "invoice_items",
            "medications", "drug_interactions", "hospital_info",
        }
        assert expected <= names, f"Missing: {expected - names}"
        await _drop_tables()

    async def test_session_yields_async_session(self):
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

    def test_all_exports(self):
        import app.db.session as m
        for n in ("get_db", "session_context", "AsyncSessionLocal"):
            assert n in m.__all__


@pytest_asyncio.fixture(scope="function")
async def db():
    await _create_tables()
    async with _TestSession() as session:
        yield session
    await _drop_tables()


@pytest.mark.asyncio
class TestPatient:

    async def test_insert_select(self, db):
        from sqlalchemy import select
        from app.db.models.patient import Patient
        p = await _seed_patient(db)
        await db.commit()
        row = (await db.execute(select(Patient).where(Patient.patient_id == p.patient_id))).scalar_one()
        assert row.full_name == "Tipto Ghosh"

    async def test_phone_unique(self, db):
        from datetime import date
        from sqlalchemy.exc import IntegrityError
        from app.db.models.patient import Patient
        db.add(Patient(patient_id="PA", full_name="A", date_of_birth=date(1990,1,1), gender="Male",  phone="01111111111"))
        await db.flush()
        db.add(Patient(patient_id="PB", full_name="B", date_of_birth=date(1991,1,1), gender="Female",phone="01111111111"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_soft_delete(self, db):
        from sqlalchemy import select
        from app.db.models.patient import Patient
        p = await _seed_patient(db, pid="P-SD", phone="01999000001")
        p.is_active = False
        await db.commit()
        row = (await db.execute(select(Patient).where(Patient.patient_id == "P-SD"))).scalar_one()
        assert row.is_active is False

    async def test_repr(self, db):
        p = await _seed_patient(db)
        assert "Tipto Ghosh" in repr(p)


@pytest.mark.asyncio
class TestDoctor:

    async def test_insert_fk(self, db):
        from sqlalchemy import select
        from app.db.models.doctor import Doctor
        dept = await _seed_dept(db)
        doc  = await _seed_doctor(db, dept.department_id)
        await db.commit()
        row = (await db.execute(select(Doctor).where(Doctor.doctor_id == doc.doctor_id))).scalar_one()
        assert row.specialization == "Cardiologist"

    async def test_schedule_insert(self, db):
        from datetime import time
        from app.db.models.doctor import DoctorSchedule
        dept = await _seed_dept(db)
        doc  = await _seed_doctor(db, dept.department_id)
        sched = DoctorSchedule(doctor_id=doc.doctor_id, day_of_week="Monday",
                               start_time=time(9,0), end_time=time(13,0),
                               slot_duration_min=20, max_appointments=15, is_active=True)
        db.add(sched); await db.commit(); await db.refresh(sched)
        assert sched.schedule_id is not None


@pytest.mark.asyncio
class TestAppointment:

    async def _appt(self, db, appt_id, days_from_now, status="pending"):
        from datetime import datetime, timedelta
        dept = await _seed_dept(db)
        doc  = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid=f"P-{appt_id}", phone=f"019{appt_id[:8].zfill(8)}")
        return await _seed_appt(db, appt_id, datetime.utcnow() + timedelta(days=days_from_now),
                                pat.patient_id, doc.doctor_id, status), pat, doc

    async def test_insert_select(self, db):
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from app.db.models.appointment import Appointment
        dept = await _seed_dept(db)
        doc  = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-APT001", phone="01901010101")
        a = await _seed_appt(db, "APT001", datetime.utcnow()+timedelta(days=3),
                             pat.patient_id, doc.doctor_id)
        await db.commit()
        row = (await db.execute(select(Appointment).where(Appointment.appointment_id == "APT001"))).scalar_one()
        assert row.status == "pending"

    async def test_composite_indexes(self, db):
        from app.db.base import Base
        idx = {i.name for i in Base.metadata.tables["appointments"].indexes}
        assert "idx_doctor_datetime" in idx
        assert "idx_patient_status"  in idx

    async def test_is_cancellable_future(self, db):
        from datetime import datetime, timedelta
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-CAN1", phone="01902020202")
        a = await _seed_appt(db, "ACAN1", datetime.utcnow()+timedelta(days=5), pat.patient_id, doc.doctor_id)
        assert a.is_cancellable() is True

    async def test_is_cancellable_within_24h(self, db):
        from datetime import datetime, timedelta
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-CAN2", phone="01903030303")
        a = await _seed_appt(db, "ACAN2", datetime.utcnow()+timedelta(hours=6), pat.patient_id, doc.doctor_id)
        assert a.is_cancellable() is False

    async def test_is_cancellable_already_cancelled(self, db):
        from datetime import datetime, timedelta
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-CAN3", phone="01904040404")
        a = await _seed_appt(db, "ACAN3", datetime.utcnow()+timedelta(days=3), pat.patient_id, doc.doctor_id, "cancelled")
        assert a.is_cancellable() is False

    async def test_soft_cancel(self, db):
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from app.db.models.appointment import Appointment
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-CAN4", phone="01905050505")
        a = await _seed_appt(db, "ACAN4", datetime.utcnow()+timedelta(days=5), pat.patient_id, doc.doctor_id)
        a.status = "cancelled"; a.cancellation_reason = "Patient request"
        await db.commit()
        row = (await db.execute(select(Appointment).where(Appointment.appointment_id == "ACAN4"))).scalar_one()
        assert row.status == "cancelled" and row.cancellation_reason == "Patient request"

    async def test_back_ref_patient(self, db):
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.patient import Patient
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-BR1", phone="01906060606")
        await _seed_appt(db, "ABR1", datetime.utcnow()+timedelta(days=2), pat.patient_id, doc.doctor_id)
        await db.commit()
        loaded = (await db.execute(
            select(Patient).where(Patient.patient_id == pat.patient_id)
            .options(selectinload(Patient.appointments))
        )).scalar_one()
        assert len(loaded.appointments) == 1


@pytest.mark.asyncio
class TestMedicalRecord:

    async def test_insert_select(self, db):
        from datetime import date
        from sqlalchemy import select
        from app.db.models.medical_record import MedicalRecord
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-MR1", phone="01910000001")
        rec  = MedicalRecord(patient_id=pat.patient_id, doctor_id=doc.doctor_id,
                             visit_date=date(2024,3,15), diagnosis="Stable angina")
        db.add(rec); await db.commit(); await db.refresh(rec)
        row = (await db.execute(select(MedicalRecord).where(MedicalRecord.record_id == rec.record_id))).scalar_one()
        assert row.diagnosis == "Stable angina"

    async def test_nullable_appointment_id(self, db):
        from datetime import date
        from app.db.models.medical_record import MedicalRecord
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-MR2", phone="01910000002")
        rec  = MedicalRecord(patient_id=pat.patient_id, doctor_id=doc.doctor_id,
                             visit_date=date(2024,1,10), appointment_id=None)
        db.add(rec); await db.commit(); await db.refresh(rec)
        assert rec.appointment_id is None

    async def test_repr(self, db):
        from datetime import date
        from app.db.models.medical_record import MedicalRecord
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-MR3", phone="01910000003")
        rec  = MedicalRecord(patient_id=pat.patient_id, doctor_id=doc.doctor_id, visit_date=date(2024,5,1))
        db.add(rec); await db.commit(); await db.refresh(rec)
        assert "P-MR3" in repr(rec)


@pytest.mark.asyncio
class TestLabResult:

    async def test_normal_result(self, db):
        from datetime import date
        from app.db.models.medical_record import LabResult
        pat = await _seed_patient(db, pid="P-LB1", phone="01920000001")
        lr  = LabResult(patient_id=pat.patient_id, test_name="HbA1c",
                        test_date=date(2024,4,10), result_value="5.4%", is_abnormal=False)
        db.add(lr); await db.commit(); await db.refresh(lr)
        assert lr.is_abnormal is False

    async def test_abnormal_flag_and_repr(self, db):
        from datetime import date
        from app.db.models.medical_record import LabResult
        pat = await _seed_patient(db, pid="P-LB2", phone="01920000002")
        lr  = LabResult(patient_id=pat.patient_id, test_name="Glucose",
                        test_date=date(2024,4,11), is_abnormal=True)
        db.add(lr); await db.commit(); await db.refresh(lr)
        assert lr.is_abnormal is True
        assert "⚠ABNORMAL" in repr(lr)

    async def test_back_ref_patient(self, db):
        from datetime import date
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.medical_record import LabResult
        from app.db.models.patient import Patient
        pat = await _seed_patient(db, pid="P-LB3", phone="01920000003")
        db.add(LabResult(patient_id=pat.patient_id, test_name="CBC",  test_date=date(2024,3,1), is_abnormal=False))
        db.add(LabResult(patient_id=pat.patient_id, test_name="LFT",  test_date=date(2024,3,2), is_abnormal=True))
        await db.commit()
        loaded = (await db.execute(
            select(Patient).where(Patient.patient_id == pat.patient_id)
            .options(selectinload(Patient.lab_results))
        )).scalar_one()
        assert len(loaded.lab_results) == 2


@pytest.mark.asyncio
class TestPrescription:

    async def test_insert_active(self, db):
        from datetime import date
        from sqlalchemy import select
        from app.db.models.medical_record import Prescription
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-RX1", phone="01930000001")
        rx   = Prescription(patient_id=pat.patient_id, doctor_id=doc.doctor_id,
                            prescribed_date=date(2024,3,1), medication_name="Metformin",
                            dosage="500mg", frequency="twice daily", is_active=True)
        db.add(rx); await db.commit(); await db.refresh(rx)
        row = (await db.execute(select(Prescription).where(Prescription.prescription_id == rx.prescription_id))).scalar_one()
        assert row.medication_name == "Metformin" and row.is_active is True

    async def test_deactivate_never_deletes(self, db):
        from datetime import date
        from sqlalchemy import select
        from app.db.models.medical_record import Prescription
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-RX2", phone="01930000002")
        rx   = Prescription(patient_id=pat.patient_id, doctor_id=doc.doctor_id,
                            prescribed_date=date(2024,1,1), medication_name="Aspirin", is_active=True)
        db.add(rx); await db.commit()
        rx.is_active = False; await db.commit()
        row = (await db.execute(select(Prescription).where(Prescription.prescription_id == rx.prescription_id))).scalar_one()
        assert row is not None and row.is_active is False

    async def test_active_filter(self, db):
        from datetime import date
        from sqlalchemy import select
        from app.db.models.medical_record import Prescription
        dept = await _seed_dept(db); doc = await _seed_doctor(db, dept.department_id)
        pat  = await _seed_patient(db, pid="P-RX3", phone="01930000003")
        for name, active in [("DrugA", True), ("DrugB", False), ("DrugC", True)]:
            db.add(Prescription(patient_id=pat.patient_id, doctor_id=doc.doctor_id,
                                prescribed_date=date(2024,1,1), medication_name=name, is_active=active))
        await db.commit()
        rows = (await db.execute(
            select(Prescription)
            .where(Prescription.patient_id == pat.patient_id, Prescription.is_active.is_(True))
        )).scalars().all()
        assert len(rows) == 2


@pytest.mark.asyncio
class TestBillingInvoice:

    async def _invoice(self, db, inv_id, patient_id, total, paid, status="unpaid"):
        from app.db.models.billing import BillingInvoice
        inv = BillingInvoice(invoice_id=inv_id, patient_id=patient_id,
                             total_amount=Decimal(str(total)),
                             paid_amount=Decimal(str(paid)), status=status)
        db.add(inv); await db.flush(); return inv

    async def test_insert_and_select(self, db):
        from sqlalchemy import select
        from app.db.models.billing import BillingInvoice
        pat = await _seed_patient(db, pid="P-INV1", phone="01940000001")
        inv = await self._invoice(db, "INV-001", pat.patient_id, 1200, 0)
        await db.commit()
        row = (await db.execute(select(BillingInvoice).where(BillingInvoice.invoice_id == "INV-001"))).scalar_one()
        assert row.total_amount == Decimal("1200")
        assert row.status == "unpaid"

    async def test_amount_due(self, db):
        pat = await _seed_patient(db, pid="P-INV2", phone="01940000002")
        inv = await self._invoice(db, "INV-002", pat.patient_id, 5000, 2000, "partial")
        assert inv.amount_due() == Decimal("3000")

    async def test_amount_due_fully_paid(self, db):
        pat = await _seed_patient(db, pid="P-INV3", phone="01940000003")
        inv = await self._invoice(db, "INV-003", pat.patient_id, 800, 800, "paid")
        assert inv.amount_due() == Decimal("0")

    async def test_is_settled_paid(self, db):
        pat = await _seed_patient(db, pid="P-INV4", phone="01940000004")
        inv = await self._invoice(db, "INV-004", pat.patient_id, 600, 600, "paid")
        assert inv.is_settled() is True

    async def test_is_settled_waived(self, db):
        pat = await _seed_patient(db, pid="P-INV5", phone="01940000005")
        inv = await self._invoice(db, "INV-005", pat.patient_id, 400, 0, "waived")
        assert inv.is_settled() is True

    async def test_is_settled_unpaid(self, db):
        pat = await _seed_patient(db, pid="P-INV6", phone="01940000006")
        inv = await self._invoice(db, "INV-006", pat.patient_id, 1000, 0, "unpaid")
        assert inv.is_settled() is False

    async def test_all_status_values(self, db):
        from app.db.models.billing import BillingInvoice, INVOICE_STATUSES
        pat = await _seed_patient(db, pid="P-INV7", phone="01940000007")
        for i, status in enumerate(INVOICE_STATUSES):
            inv = BillingInvoice(invoice_id=f"INV-S{i:02d}", patient_id=pat.patient_id,
                                 total_amount=Decimal("100"), paid_amount=Decimal("0"),
                                 status=status)
            db.add(inv)
        await db.commit()

    async def test_repr(self, db):
        pat = await _seed_patient(db, pid="P-INV8", phone="01940000008")
        inv = await self._invoice(db, "INV-008", pat.patient_id, 3200, 1000, "partial")
        r = repr(inv)
        assert "INV-008" in r and "partial" in r and "2200" in r

    async def test_invoice_index_exists(self, db):
        from app.db.base import Base
        idx = {i.name for i in Base.metadata.tables["billing_invoices"].indexes}
        assert "idx_invoice_patient_status" in idx


@pytest.mark.asyncio
class TestInvoiceItem:

    async def test_insert_and_relationship(self, db):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.billing import BillingInvoice, InvoiceItem
        pat = await _seed_patient(db, pid="P-ITEM1", phone="01950000001")
        inv = BillingInvoice(invoice_id="INV-IT1", patient_id=pat.patient_id,
                             total_amount=Decimal("1150"), paid_amount=Decimal("0"), status="unpaid")
        db.add(inv); await db.flush()
        items = [
            InvoiceItem(invoice_id="INV-IT1", description="Cardiology Consultation",
                        quantity=1, unit_price=Decimal("800"), total_price=Decimal("800")),
            InvoiceItem(invoice_id="INV-IT1", description="HbA1c Lab Test",
                        quantity=1, unit_price=Decimal("350"), total_price=Decimal("350")),
        ]
        db.add_all(items); await db.commit()
        loaded = (await db.execute(
            select(BillingInvoice).where(BillingInvoice.invoice_id == "INV-IT1")
            .options(selectinload(BillingInvoice.items))
        )).scalar_one()
        assert len(loaded.items) == 2
        descs = {i.description for i in loaded.items}
        assert "Cardiology Consultation" in descs
        assert "HbA1c Lab Test" in descs

    async def test_item_total_price(self, db):
        from app.db.models.billing import BillingInvoice, InvoiceItem
        pat = await _seed_patient(db, pid="P-ITEM2", phone="01950000002")
        inv = BillingInvoice(invoice_id="INV-IT2", patient_id=pat.patient_id,
                             total_amount=Decimal("240"), paid_amount=Decimal("0"), status="unpaid")
        db.add(inv); await db.flush()
        item = InvoiceItem(invoice_id="INV-IT2", description="Metformin 500mg x30",
                           quantity=2, unit_price=Decimal("120"), total_price=Decimal("240"))
        db.add(item); await db.commit(); await db.refresh(item)
        assert item.quantity == 2
        assert item.unit_price == Decimal("120")
        assert item.total_price == Decimal("240")

    async def test_cascade_delete_items_with_invoice(self, db):
        from sqlalchemy import select
        from app.db.models.billing import BillingInvoice, InvoiceItem
        pat  = await _seed_patient(db, pid="P-ITEM3", phone="01950000003")
        inv  = BillingInvoice(invoice_id="INV-IT3", patient_id=pat.patient_id,
                              total_amount=Decimal("500"), paid_amount=Decimal("0"), status="unpaid")
        db.add(inv); await db.flush()
        db.add(InvoiceItem(invoice_id="INV-IT3", description="Test",
                           quantity=1, unit_price=Decimal("500"), total_price=Decimal("500")))
        await db.commit()
        await db.delete(inv); await db.commit()
        remaining = (await db.execute(
            select(InvoiceItem).where(InvoiceItem.invoice_id == "INV-IT3")
        )).scalars().all()
        assert len(remaining) == 0

    async def test_back_ref_patient_billing_invoices(self, db):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.billing import BillingInvoice
        from app.db.models.patient import Patient
        pat = await _seed_patient(db, pid="P-ITEM4", phone="01950000004")
        db.add(BillingInvoice(invoice_id="INV-IT4", patient_id=pat.patient_id,
                              total_amount=Decimal("300"), paid_amount=Decimal("0"), status="unpaid"))
        await db.commit()
        loaded = (await db.execute(
            select(Patient).where(Patient.patient_id == pat.patient_id)
            .options(selectinload(Patient.billing_invoices))
        )).scalar_one()
        assert len(loaded.billing_invoices) == 1

    async def test_repr(self, db):
        from app.db.models.billing import BillingInvoice, InvoiceItem
        pat  = await _seed_patient(db, pid="P-ITEM5", phone="01950000005")
        inv  = BillingInvoice(invoice_id="INV-IT5", patient_id=pat.patient_id,
                              total_amount=Decimal("800"), paid_amount=Decimal("0"), status="unpaid")
        db.add(inv); await db.flush()
        item = InvoiceItem(invoice_id="INV-IT5", description="Consultation",
                           quantity=1, unit_price=Decimal("800"), total_price=Decimal("800"))
        db.add(item); await db.commit(); await db.refresh(item)
        assert "Consultation" in repr(item) and "800" in repr(item)


@pytest.mark.asyncio
class TestMedication:

    async def test_insert_and_select(self, db):
        from sqlalchemy import select
        from app.db.models.medication import Medication
        med = Medication(
            generic_name="metformin",
            brand_names="Glucophage, Fortamet",
            drug_class="biguanide antidiabetic",
            common_uses="Type 2 diabetes management",
            side_effects="Nausea, diarrhoea, lactic acidosis (rare)",
            contraindications="Renal impairment (eGFR < 30)",
            general_dosage="500–2000 mg/day in divided doses",
            requires_prescription=True,
        )
        db.add(med); await db.commit(); await db.refresh(med)
        row = (await db.execute(
            select(Medication).where(Medication.generic_name == "metformin")
        )).scalar_one()
        assert row.drug_class == "biguanide antidiabetic"
        assert row.requires_prescription is True

    async def test_otc_medication(self, db):
        from app.db.models.medication import Medication
        med = Medication(generic_name="paracetamol", drug_class="analgesic",
                         requires_prescription=False)
        db.add(med); await db.commit(); await db.refresh(med)
        assert med.requires_prescription is False
        assert "OTC" in repr(med)

    async def test_rx_flag_in_repr(self, db):
        from app.db.models.medication import Medication
        med = Medication(generic_name="atorvastatin", requires_prescription=True)
        db.add(med); await db.commit(); await db.refresh(med)
        assert "Rx" in repr(med)

    async def test_generic_name_unique(self, db):
        from sqlalchemy.exc import IntegrityError
        from app.db.models.medication import Medication
        db.add(Medication(generic_name="aspirin", requires_prescription=False))
        await db.flush()
        db.add(Medication(generic_name="aspirin", requires_prescription=False))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_nullable_fields(self, db):
        from app.db.models.medication import Medication
        med = Medication(generic_name="testdrug_minimal", requires_prescription=True)
        db.add(med); await db.commit(); await db.refresh(med)
        assert med.brand_names is None
        assert med.drug_class is None
        assert med.common_uses is None


@pytest.mark.asyncio
class TestDrugInteraction:

    async def test_insert_and_select(self, db):
        from sqlalchemy import select
        from app.db.models.medication import DrugInteraction
        di = DrugInteraction(drug_a="warfarin", drug_b="aspirin",
                             severity="severe",
                             description="Increased bleeding risk when co-administered.")
        db.add(di); await db.commit(); await db.refresh(di)
        row = (await db.execute(
            select(DrugInteraction).where(DrugInteraction.drug_a == "warfarin")
        )).scalar_one()
        assert row.drug_b == "aspirin"
        assert row.severity == "severe"

    async def test_all_severity_values(self, db):
        from app.db.models.medication import DrugInteraction, INTERACTION_SEVERITIES
        for i, sev in enumerate(INTERACTION_SEVERITIES):
            db.add(DrugInteraction(drug_a=f"drug{i}a", drug_b=f"drug{i}b",
                                   severity=sev, description=f"{sev} interaction."))
        await db.commit()

    async def test_is_contraindicated(self, db):
        from app.db.models.medication import DrugInteraction
        di = DrugInteraction(drug_a="monoamine_oxidase_inhibitor", drug_b="serotonin",
                             severity="contraindicated", description="Serotonin syndrome risk.")
        db.add(di); await db.commit(); await db.refresh(di)
        assert di.is_contraindicated is True
        assert di.requires_immediate_advisory is True

    async def test_requires_immediate_advisory_severe(self, db):
        from app.db.models.medication import DrugInteraction
        di = DrugInteraction(drug_a="lithium", drug_b="ibuprofen",
                             severity="severe", description="Lithium toxicity risk.")
        db.add(di); await db.commit(); await db.refresh(di)
        assert di.is_contraindicated is False
        assert di.requires_immediate_advisory is True

    async def test_mild_no_immediate_advisory(self, db):
        from app.db.models.medication import DrugInteraction
        di = DrugInteraction(drug_a="caffeine", drug_b="paracetamol",
                             severity="mild", description="Minor interaction.")
        db.add(di); await db.commit(); await db.refresh(di)
        assert di.requires_immediate_advisory is False

    async def test_repr(self, db):
        from app.db.models.medication import DrugInteraction
        di = DrugInteraction(drug_a="drugX", drug_b="drugY",
                             severity="moderate", description="Moderate effect.")
        db.add(di); await db.commit(); await db.refresh(di)
        r = repr(di)
        assert "drugX" in r and "drugY" in r and "moderate" in r


@pytest.mark.asyncio
class TestHospitalInfo:

    async def test_insert_and_select(self, db):
        from sqlalchemy import select
        from app.db.models.medication import HospitalInfo
        hi = HospitalInfo(category="hours", topic="ICU Visiting Hours",
                          content="ICU visiting hours are 8 AM – 10 AM and 4 PM – 6 PM daily.")
        db.add(hi); await db.commit(); await db.refresh(hi)
        row = (await db.execute(
            select(HospitalInfo).where(HospitalInfo.topic == "ICU Visiting Hours")
        )).scalar_one()
        assert "8 AM" in row.content
        assert row.category == "hours"

    async def test_all_category_values(self, db):
        from app.db.models.medication import HospitalInfo, HOSPITAL_INFO_CATEGORIES
        for i, cat in enumerate(HOSPITAL_INFO_CATEGORIES):
            db.add(HospitalInfo(category=cat, topic=f"Test topic {i}",
                                content=f"Content for {cat}"))
        await db.commit()

    async def test_last_updated_auto_set(self, db):
        from app.db.models.medication import HospitalInfo
        hi = HospitalInfo(category="location", topic="Radiology Floor",
                          content="Radiology is on the 2nd floor, East Wing.")
        db.add(hi); await db.commit(); await db.refresh(hi)
        assert hi.last_updated is not None

    async def test_repr(self, db):
        from app.db.models.medication import HospitalInfo
        hi = HospitalInfo(category="faq", topic="Parking",
                          content="Free parking is available for patients.")
        db.add(hi); await db.commit(); await db.refresh(hi)
        r = repr(hi)
        assert "faq" in r and "Parking" in r

    async def test_multiple_entries_same_category(self, db):
        from sqlalchemy import select
        from app.db.models.medication import HospitalInfo
        for topic in ["OPD Hours", "Emergency Hours", "Lab Hours"]:
            db.add(HospitalInfo(category="hours", topic=topic, content="..."))
        await db.commit()
        rows = (await db.execute(
            select(HospitalInfo).where(HospitalInfo.category == "hours")
        )).scalars().all()
        assert len(rows) == 3

    async def test_content_update_refreshes_last_updated(self, db):
        from sqlalchemy import select
        from app.db.models.medication import HospitalInfo
        hi = HospitalInfo(category="policy", topic="Cancellation Policy",
                          content="Original content.")
        db.add(hi); await db.commit(); await db.refresh(hi)
        original_ts = hi.last_updated
        hi.content = "Updated content."; hi.last_updated = __import__("datetime").datetime.utcnow()
        await db.commit(); await db.refresh(hi)
        assert hi.content == "Updated content."
        assert hi.last_updated >= original_ts