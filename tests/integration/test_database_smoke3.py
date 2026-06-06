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
    from app.db.models.feedback import Feedback, ComplaintTicket
    from app.db.models.audit_log import AuditLog
    from app.db.models.memory import (
        ConversationSession, ConversationMemory, PatientLongTermContext
    )
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


@pytest_asyncio.fixture(scope="function")
async def db():
    await _create_tables()
    async with _TestSession() as session:
        yield session
    await _drop_tables()


class TestConfig:
    def setup_method(self):
        from app.config import get_settings; get_settings.cache_clear()
    def test_load(self):
        from app.config import get_settings; assert get_settings() is not None
    def test_llm(self):
        from app.config import get_settings
        s = get_settings().llm
        assert s.LLM_FAST_MODEL and s.LLM_CAPABLE_MODEL
    def test_singleton(self):
        from app.config import get_settings
        assert get_settings() is get_settings()

@pytest.mark.asyncio
class TestAllTablesPresent:
    async def test_all_13_step_tables(self, db):
        from app.db.base import Base
        names = set(Base.metadata.tables.keys())
        expected = {
            "patients", "doctors", "departments", "doctor_schedules",
            "appointments", "medical_records", "lab_results", "prescriptions",
            "billing_invoices", "invoice_items",
            "medications", "drug_interactions", "hospital_info",
            "feedback", "complaint_tickets", "audit_log",
            "conversation_sessions", "conversation_memory",
            "patient_long_term_context",
        }
        missing = expected - names
        assert not missing, f"Missing tables: {missing}"


@pytest.mark.asyncio
class TestFeedback:

    async def test_insert_with_patient(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.feedback import Feedback
        pat = await _seed_patient(db, pid="P-FB1", phone="01810000001")
        fb = Feedback(patient_id=pat.patient_id, category="doctor",
                      message="Dr. Rahman was excellent.", rating=5)
        db.add(fb); await db.commit(); await db.refresh(fb)
        row = (await db.execute(
            select(Feedback).where(Feedback.feedback_id == fb.feedback_id)
        )).scalar_one()
        assert row.rating == 5
        assert row.category == "doctor"

    async def test_anonymous_feedback(self, db: AsyncSession):
        from app.db.models.feedback import Feedback
        fb = Feedback(patient_id=None, category="facilities",
                      message="The waiting area was clean.", rating=4)
        db.add(fb); await db.commit(); await db.refresh(fb)
        assert fb.patient_id is None
        assert fb.feedback_id is not None

    async def test_all_category_values(self, db: AsyncSession):
        from app.db.models.feedback import Feedback, FEEDBACK_CATEGORIES
        for i, cat in enumerate(FEEDBACK_CATEGORIES):
            db.add(Feedback(category=cat, message=f"Test msg {i}", rating=3))
        await db.commit()

    async def test_rating_check_constraint_valid(self, db: AsyncSession):
        from app.db.models.feedback import Feedback
        for r in range(1, 6):
            db.add(Feedback(category="general", message="msg", rating=r))
        await db.commit()

    async def test_null_rating_allowed(self, db: AsyncSession):
        from app.db.models.feedback import Feedback
        fb = Feedback(category="staff", message="Staff were helpful.", rating=None)
        db.add(fb); await db.commit(); await db.refresh(fb)
        assert fb.rating is None

    async def test_repr_with_rating(self, db: AsyncSession):
        from app.db.models.feedback import Feedback
        fb = Feedback(category="ai_agent", message="Very helpful.", rating=5)
        db.add(fb); await db.commit(); await db.refresh(fb)
        r = repr(fb)
        assert "ai_agent" in r and "★5" in r

    async def test_repr_no_rating(self, db: AsyncSession):
        from app.db.models.feedback import Feedback
        fb = Feedback(category="billing", message="Confusing bill.")
        db.add(fb); await db.commit(); await db.refresh(fb)
        assert "billing" in repr(fb)

    async def test_back_ref_patient_feedback(self, db: AsyncSession):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.feedback import Feedback
        from app.db.models.patient import Patient
        pat = await _seed_patient(db, pid="P-FB2", phone="01810000002")
        db.add(Feedback(patient_id=pat.patient_id, category="general",
                        message="Good experience.", rating=4))
        await db.commit()
        loaded = (await db.execute(
            select(Patient).where(Patient.patient_id == pat.patient_id)
            .options(selectinload(Patient.feedback))
        )).scalar_one()
        assert len(loaded.feedback) == 1
        assert loaded.feedback[0].rating == 4


@pytest.mark.asyncio
class TestComplaintTicket:

    async def test_insert_and_select(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.feedback import ComplaintTicket
        pat = await _seed_patient(db, pid="P-TKT1", phone="01820000001")
        tkt = ComplaintTicket(
            ticket_id="TKT-001",
            patient_id=pat.patient_id,
            department="Billing",
            description="Was charged twice for the same consultation.",
            status="open",
            priority="high",
        )
        db.add(tkt); await db.commit()
        row = (await db.execute(
            select(ComplaintTicket).where(ComplaintTicket.ticket_id == "TKT-001")
        )).scalar_one()
        assert row.status == "open"
        assert row.priority == "high"

    async def test_anonymous_ticket(self, db: AsyncSession):
        from app.db.models.feedback import ComplaintTicket
        tkt = ComplaintTicket(ticket_id="TKT-ANON", patient_id=None,
                              description="Rude staff at reception.",
                              status="open", priority="medium")
        db.add(tkt); await db.commit(); await db.refresh(tkt)
        assert tkt.patient_id is None

    async def test_all_status_values(self, db: AsyncSession):
        from app.db.models.feedback import ComplaintTicket, TICKET_STATUSES
        for i, st in enumerate(TICKET_STATUSES):
            db.add(ComplaintTicket(ticket_id=f"TKT-S{i}", description="test",
                                   status=st, priority="low"))
        await db.commit()

    async def test_all_priority_values(self, db: AsyncSession):
        from app.db.models.feedback import ComplaintTicket, TICKET_PRIORITIES
        for i, pri in enumerate(TICKET_PRIORITIES):
            db.add(ComplaintTicket(ticket_id=f"TKT-P{i}", description="test",
                                   status="open", priority=pri))
        await db.commit()

    async def test_escalation_pattern(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.feedback import ComplaintTicket
        tkt = ComplaintTicket(ticket_id="TKT-ESC", description="Serious issue.",
                              status="open", priority="medium")
        db.add(tkt); await db.commit()
        tkt.status = "escalated"
        tkt.priority = "critical"
        await db.commit()
        row = (await db.execute(
            select(ComplaintTicket).where(ComplaintTicket.ticket_id == "TKT-ESC")
        )).scalar_one()
        assert row.status == "escalated"
        assert row.priority == "critical"

    async def test_resolution_never_by_agent(self, db: AsyncSession):
        from datetime import datetime
        from sqlalchemy import select
        from app.db.models.feedback import ComplaintTicket
        tkt = ComplaintTicket(ticket_id="TKT-RES", description="Billing dispute.",
                              status="open", priority="low")
        db.add(tkt); await db.commit()
        tkt.status = "resolved"
        tkt.resolution_note = "Duplicate charge reversed. Refund processed."
        tkt.resolved_at = datetime.utcnow()
        await db.commit()
        row = (await db.execute(
            select(ComplaintTicket).where(ComplaintTicket.ticket_id == "TKT-RES")
        )).scalar_one()
        assert row.is_resolved is True
        assert row.resolution_note is not None

    async def test_is_open_statuses(self, db: AsyncSession):
        for i, (st, expected) in enumerate([
            ("open", True), ("in_review", True), ("escalated", True), ("resolved", False)
        ]):
            from app.db.models.feedback import ComplaintTicket
            tkt = ComplaintTicket(ticket_id=f"TKT-OPEN{i}", description="test",
                                  status=st, priority="low")
            db.add(tkt); await db.flush()
            assert tkt.is_open == expected, f"Failed for status={st!r}"
        await db.commit()

    async def test_repr(self, db: AsyncSession):
        from app.db.models.feedback import ComplaintTicket
        tkt = ComplaintTicket(ticket_id="TKT-REPR", description="Issue.",
                              status="open", priority="high")
        db.add(tkt); await db.commit()
        r = repr(tkt)
        assert "TKT-REPR" in r and "open" in r and "high" in r


@pytest.mark.asyncio
class TestAuditLog:

    async def test_log_action_classmethod(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.audit_log import AuditLog
        entry = await AuditLog.log_action(
            session=db,
            agent_name="records_agent",
            action="read_lab_results",
            session_id="sess_abc123",
            patient_id="P-AUDIT1",
            resource_type="lab_results",
            resource_id="42",
            payload_summary="Read 3 lab results",
            ip_address="192.168.1.1",
        )
        await db.commit()
        assert entry.log_id is not None
        row = (await db.execute(
            select(AuditLog).where(AuditLog.log_id == entry.log_id)
        )).scalar_one()
        assert row.agent_name == "records_agent"
        assert row.action == "read_lab_results"
        assert row.resource_type == "lab_results"
        assert row.resource_id == "42"
        assert row.ip_address == "192.168.1.1"

    async def test_log_action_minimal_params(self, db: AsyncSession):
        from app.db.models.audit_log import AuditLog
        entry = await AuditLog.log_action(
            session=db,
            agent_name="emergency_agent",
            action="get_emergency_contacts",
        )
        await db.commit()
        assert entry.log_id is not None
        assert entry.patient_id is None
        assert entry.session_id is None

    async def test_multiple_log_entries_different_ids(self, db: AsyncSession):
        from app.db.models.audit_log import AuditLog
        ids = []
        for action in ["read_profile", "read_history", "read_prescriptions"]:
            e = await AuditLog.log_action(
                session=db, agent_name="records_agent", action=action,
                patient_id="P-AUDIT2",
            )
            ids.append(e.log_id)
        await db.commit()
        assert len(set(ids)) == 3

    async def test_bigint_pk(self, db: AsyncSession):
        from app.db.models.audit_log import AuditLog
        entry = await AuditLog.log_action(
            session=db, agent_name="supervisor", action="route_intent"
        )
        await db.commit()
        assert isinstance(entry.log_id, int)
        assert entry.log_id > 0

    async def test_no_update_method_exists(self):
        from app.db.models.audit_log import AuditLog
        instance = AuditLog(agent_name="test", action="test_action")
        assert not hasattr(instance, "update")
        assert not hasattr(instance, "delete")

    async def test_composite_indexes_exist(self, db: AsyncSession):
        from app.db.base import Base
        idx_names = {i.name for i in Base.metadata.tables["audit_log"].indexes}
        assert "idx_patient_audit" in idx_names
        assert "idx_session_audit" in idx_names

    async def test_repr(self, db: AsyncSession):
        from app.db.models.audit_log import AuditLog
        entry = await AuditLog.log_action(
            session=db, agent_name="billing_agent", action="read_invoice",
            patient_id="P-REPR"
        )
        await db.commit()
        r = repr(entry)
        assert "billing_agent" in r and "read_invoice" in r

    async def test_payload_summary_non_phi(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.audit_log import AuditLog
        entry = await AuditLog.log_action(
            session=db,
            agent_name="records_agent",
            action="read_medical_history",
            patient_id="P-PHI",
            payload_summary="Read 2 medical records (2024-Q1)",
        )
        await db.commit()
        row = (await db.execute(
            select(AuditLog).where(AuditLog.log_id == entry.log_id)
        )).scalar_one()
        assert "Read 2 medical records" in row.payload_summary
        assert "Diagnosis" not in row.payload_summary


@pytest.mark.asyncio
class TestConversationSession:

    async def test_insert_and_select(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.memory import ConversationSession
        sess = ConversationSession(session_id="sess_001", channel="web", is_active=True)
        db.add(sess); await db.commit()
        row = (await db.execute(
            select(ConversationSession).where(ConversationSession.session_id == "sess_001")
        )).scalar_one()
        assert row.channel == "web"
        assert row.is_active is True

    async def test_anonymous_session(self, db: AsyncSession):
        from app.db.models.memory import ConversationSession
        sess = ConversationSession(session_id="sess_ANON", channel="web",
                                   patient_id=None, is_active=True)
        db.add(sess); await db.commit(); await db.refresh(sess)
        assert sess.patient_id is None

    async def test_patient_set_mid_session(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.memory import ConversationSession
        pat = await _seed_patient(db, pid="P-SESS1", phone="01830000001")
        sess = ConversationSession(session_id="sess_002", channel="whatsapp", is_active=True)
        db.add(sess); await db.commit()
        sess.patient_id = pat.patient_id
        await db.commit()
        row = (await db.execute(
            select(ConversationSession).where(ConversationSession.session_id == "sess_002")
        )).scalar_one()
        assert row.patient_id == "P-SESS1"

    async def test_all_channel_values(self, db: AsyncSession):
        from app.db.models.memory import ConversationSession, SESSION_CHANNELS
        for i, ch in enumerate(SESSION_CHANNELS):
            db.add(ConversationSession(session_id=f"sess_CH{i}", channel=ch, is_active=True))
        await db.commit()

    async def test_session_deactivation(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.memory import ConversationSession
        sess = ConversationSession(session_id="sess_003", channel="kiosk", is_active=True)
        db.add(sess); await db.commit()
        sess.is_active = False; await db.commit()
        row = (await db.execute(
            select(ConversationSession).where(ConversationSession.session_id == "sess_003")
        )).scalar_one()
        assert row.is_active is False

    async def test_metadata_json_stored(self, db: AsyncSession):
        import json
        from sqlalchemy import select
        from app.db.models.memory import ConversationSession
        meta = json.dumps({"device": "mobile", "language": "bn", "ab_flag": "v2"})
        sess = ConversationSession(session_id="sess_META", channel="api",
                                   is_active=True, metadata_json=meta)
        db.add(sess); await db.commit()
        row = (await db.execute(
            select(ConversationSession).where(ConversationSession.session_id == "sess_META")
        )).scalar_one()
        loaded = json.loads(row.metadata_json)
        assert loaded["language"] == "bn"

    async def test_repr(self, db: AsyncSession):
        from app.db.models.memory import ConversationSession
        sess = ConversationSession(session_id="sess_REPR", channel="web", is_active=True)
        db.add(sess); await db.commit()
        r = repr(sess)
        assert "sess_REPR" in r and "web" in r


@pytest.mark.asyncio
class TestConversationMemory:

    async def _seed_session(self, db, sid="sess_MEM1"):
        from app.db.models.memory import ConversationSession
        s = ConversationSession(session_id=sid, channel="web", is_active=True)
        db.add(s); await db.flush(); return s

    async def test_insert_human_and_ai_turns(self, db: AsyncSession):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.memory import ConversationSession, ConversationMemory
        sess = await self._seed_session(db)
        turns = [
            ConversationMemory(session_id=sess.session_id, role="human",
                               content="I want to book an appointment."),
            ConversationMemory(session_id=sess.session_id, role="ai",
                               content="Sure! Which doctor would you prefer?",
                               agent_name="booking_agent"),
        ]
        db.add_all(turns); await db.commit()
        loaded = (await db.execute(
            select(ConversationSession).where(ConversationSession.session_id == sess.session_id)
            .options(selectinload(ConversationSession.messages))
        )).scalar_one()
        assert len(loaded.messages) == 2
        roles = {m.role for m in loaded.messages}
        assert "human" in roles and "ai" in roles

    async def test_all_role_values(self, db: AsyncSession):
        from app.db.models.memory import ConversationMemory, MESSAGE_ROLES
        sess = await self._seed_session(db, sid="sess_ROLES")
        for role in MESSAGE_ROLES:
            db.add(ConversationMemory(session_id=sess.session_id, role=role,
                                      content=f"Content for {role}"))
        await db.commit()

    async def test_agent_name_null_for_human(self, db: AsyncSession):
        from app.db.models.memory import ConversationMemory
        sess = await self._seed_session(db, sid="sess_NULL_AGENT")
        msg = ConversationMemory(session_id=sess.session_id, role="human",
                                 content="Hello.", agent_name=None)
        db.add(msg); await db.commit(); await db.refresh(msg)
        assert msg.agent_name is None

    async def test_cascade_delete_with_session(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.memory import ConversationSession, ConversationMemory
        sess = await self._seed_session(db, sid="sess_CASCADE")
        db.add(ConversationMemory(session_id=sess.session_id, role="human",
                                  content="Will this be deleted?"))
        await db.commit()
        await db.delete(sess); await db.commit()
        remaining = (await db.execute(
            select(ConversationMemory).where(ConversationMemory.session_id == "sess_CASCADE")
        )).scalars().all()
        assert len(remaining) == 0

    async def test_ordered_by_created_at(self, db: AsyncSession):
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.memory import ConversationSession, ConversationMemory
        sess = await self._seed_session(db, sid="sess_ORDER")
        base = datetime.utcnow()
        for i, content in enumerate(["first", "second", "third"]):
            db.add(ConversationMemory(session_id=sess.session_id, role="human",
                                      content=content,
                                      created_at=base + timedelta(seconds=i)))
        await db.commit()
        loaded = (await db.execute(
            select(ConversationSession).where(ConversationSession.session_id == "sess_ORDER")
            .options(selectinload(ConversationSession.messages))
        )).scalar_one()
        contents = [m.content for m in loaded.messages]
        assert contents == ["first", "second", "third"]

    async def test_repr(self, db: AsyncSession):
        from app.db.models.memory import ConversationMemory
        sess = await self._seed_session(db, sid="sess_REPR2")
        msg = ConversationMemory(session_id=sess.session_id, role="ai",
                                 content="How can I help?", agent_name="info_agent")
        db.add(msg); await db.commit(); await db.refresh(msg)
        r = repr(msg)
        assert "ai" in r and "info_agent" in r


@pytest.mark.asyncio
class TestPatientLongTermContext:

    async def test_insert_and_select(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.memory import PatientLongTermContext
        pat = await _seed_patient(db, pid="P-LTC1", phone="01840000001")
        ctx = PatientLongTermContext(
            patient_id=pat.patient_id,
            language_preference="bn",
            preferred_time_slot="morning",
            communication_opt_in=True,
            last_concern="asked about appointment reschedule",
        )
        db.add(ctx); await db.commit(); await db.refresh(ctx)
        row = (await db.execute(
            select(PatientLongTermContext).where(
                PatientLongTermContext.patient_id == "P-LTC1"
            )
        )).scalar_one()
        assert row.language_preference == "bn"
        assert row.preferred_time_slot == "morning"
        assert "reschedule" in row.last_concern

    async def test_one_row_per_patient_unique(self, db: AsyncSession):
        from sqlalchemy.exc import IntegrityError
        from app.db.models.memory import PatientLongTermContext
        pat = await _seed_patient(db, pid="P-LTC2", phone="01840000002")
        db.add(PatientLongTermContext(patient_id=pat.patient_id, language_preference="en"))
        await db.flush()
        db.add(PatientLongTermContext(patient_id=pat.patient_id, language_preference="bn"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_opt_out(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.memory import PatientLongTermContext
        pat = await _seed_patient(db, pid="P-LTC3", phone="01840000003")
        ctx = PatientLongTermContext(patient_id=pat.patient_id,
                                     communication_opt_in=False)
        db.add(ctx); await db.commit()
        row = (await db.execute(
            select(PatientLongTermContext).where(
                PatientLongTermContext.patient_id == "P-LTC3"
            )
        )).scalar_one()
        assert row.communication_opt_in is False

    async def test_preferred_doctor_fk(self, db: AsyncSession):
        from app.db.models.memory import PatientLongTermContext
        pat = await _seed_patient(db, pid="P-LTC4", phone="01840000004")
        dept = await _seed_dept(db)
        doc  = await _seed_doctor(db, dept.department_id)
        ctx = PatientLongTermContext(patient_id=pat.patient_id,
                                     preferred_doctor=doc.doctor_id)
        db.add(ctx); await db.commit(); await db.refresh(ctx)
        assert ctx.preferred_doctor == doc.doctor_id

    async def test_all_time_slot_values(self, db: AsyncSession):
        from app.db.models.memory import PatientLongTermContext, TIME_SLOT_PREFERENCES
        phones = iter(f"018400001{i:02d}" for i in range(10))
        pids   = iter(f"P-TS{i:02d}" for i in range(10))
        for slot in TIME_SLOT_PREFERENCES:
            pat = await _seed_patient(db, pid=next(pids), phone=next(phones))
            db.add(PatientLongTermContext(patient_id=pat.patient_id,
                                          preferred_time_slot=slot))
        await db.commit()

    async def test_upsert_pattern(self, db: AsyncSession):
        from sqlalchemy import select
        from app.db.models.memory import PatientLongTermContext
        pat = await _seed_patient(db, pid="P-LTC5", phone="01840000005")
        ctx = PatientLongTermContext(patient_id=pat.patient_id,
                                     language_preference="en",
                                     last_concern="initial concern")
        db.add(ctx); await db.commit()
        ctx.language_preference = "bn"
        ctx.last_concern = "updated concern"
        await db.commit()
        row = (await db.execute(
            select(PatientLongTermContext).where(
                PatientLongTermContext.patient_id == "P-LTC5"
            )
        )).scalar_one()
        assert row.language_preference == "bn"
        assert row.last_concern == "updated concern"

    async def test_back_ref_patient_context(self, db: AsyncSession):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.memory import PatientLongTermContext
        from app.db.models.patient import Patient
        pat = await _seed_patient(db, pid="P-LTC6", phone="01840000006")
        db.add(PatientLongTermContext(patient_id=pat.patient_id,
                                      language_preference="en"))
        await db.commit()
        loaded = (await db.execute(
            select(Patient).where(Patient.patient_id == "P-LTC6")
            .options(selectinload(Patient.long_term_context))
        )).scalar_one()
        assert loaded.long_term_context is not None
        assert loaded.long_term_context.language_preference == "en"

    async def test_repr(self, db: AsyncSession):
        from app.db.models.memory import PatientLongTermContext
        pat = await _seed_patient(db, pid="P-LTC7", phone="01840000007")
        ctx = PatientLongTermContext(patient_id=pat.patient_id,
                                     language_preference="bn",
                                     communication_opt_in=True)
        db.add(ctx); await db.commit(); await db.refresh(ctx)
        r = repr(ctx)
        assert "P-LTC7" in r and "bn" in r