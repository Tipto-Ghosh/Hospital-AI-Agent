import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _insert_test_appointment(db_session_factory) -> str:
    """
    Insert a cancellable appointment (4 days in the future) and return
    its appointment_id. Uses doctor_id=1 from the conftest seed.
    """
    from app.db.repositories.appointment_repo import AppointmentRepository

    scheduled_at = datetime.utcnow().replace(
        hour=10, minute=0, second=0, microsecond=0
    ) + timedelta(days=4)

    async with db_session_factory() as session:
        repo = AppointmentRepository(session)
        appt = await repo.create(
            patient_id="P-2024-00001",
            doctor_id=1,
            scheduled_at=scheduled_at,
            reason="Integration test",
            booked_via="ai_agent",
        )
        return appt.appointment_id


class TestCancelFlow:
    """
    Full cancellation flow: authenticated session → cancel_agent finds
    appointment → sets pending_confirmation → patient confirms →
    action_executor cancels → audit log written. All DB writes are
    real; only the supervisor LLM is mocked.
    """

    async def test_cancellation_sets_appointment_status_to_cancelled(
        self, compiled_graph, seeded_db, mock_redis
    ):
        from app.agents.state import create_initial_state
        from app.db.models.appointment import Appointment

        appt_id = await _insert_test_appointment(seeded_db)

        supervisor_response = AIMessage(content=json.dumps({
            "intent": "cancel_appointment",
            "entities": {"appointment_id": appt_id},
            "reasoning": "Patient wants to cancel.",
        }))

        # Only patch the source of get_redis_pool – works for all local imports
        with patch("app.agents.supervisor.agent.get_llm") as mock_sup_llm, \
             patch("app.api.dependencies.get_redis_pool", new=AsyncMock(return_value=mock_redis)):

            mock_sup = AsyncMock()
            mock_sup.ainvoke = AsyncMock(return_value=supervisor_response)
            mock_sup_llm.return_value = mock_sup

            state1 = create_initial_state(
                "sess_cancel_integration_01",
                patient_id="P-2024-00001",
                is_authenticated=True,
            )
            state1["messages"] = [HumanMessage(content=f"Cancel my appointment {appt_id}")]
            state1["entities"] = {"appointment_id": appt_id}

            result1 = await compiled_graph.ainvoke(state1)

        assert result1.get("pending_confirmation") is not None, \
            "cancel_agent should set pending_confirmation"
        pending = result1["pending_confirmation"]
        assert pending["action"] == "cancel_appointment"
        assert pending["params"]["appointment_id"] == appt_id

        # Second invocation – also only need the single patch
        with patch("app.api.dependencies.get_redis_pool", new=AsyncMock(return_value=mock_redis)):
            state2 = create_initial_state(
                "sess_cancel_integration_01",
                patient_id="P-2024-00001",
                is_authenticated=True,
            )
            state2["messages"] = result1["messages"] + [HumanMessage(content="yes")]
            state2["pending_confirmation"] = pending

            result2 = await compiled_graph.ainvoke(state2)

        async with seeded_db() as session:
            appt = (await session.execute(
                select(Appointment).where(Appointment.appointment_id == appt_id)
            )).scalar_one_or_none()

        assert appt is not None
        assert appt.status == "cancelled", f"Expected 'cancelled', got {appt.status!r}"

    async def test_cancellation_writes_audit_log_entry(
        self, compiled_graph, seeded_db, mock_redis
    ):
        from app.agents.state import create_initial_state
        from app.db.models.audit_log import AuditLog

        appt_id = await _insert_test_appointment(seeded_db)

        state = create_initial_state(
            "sess_cancel_integration_02",
            patient_id="P-2024-00001",
            is_authenticated=True,
        )
        state["messages"] = [HumanMessage(content="yes cancel it")]
        state["pending_confirmation"] = {
            "action": "cancel_appointment",
            "summary": f"Cancel appointment {appt_id}",
            "params": {"appointment_id": appt_id, "reason": None},
        }
        state["next_action"] = "confirmed"

        with patch("app.api.dependencies.get_redis_pool", new=AsyncMock(return_value=mock_redis)):
            result = await compiled_graph.ainvoke(state)

        async with seeded_db() as session:
            rows = (await session.execute(
                select(AuditLog).where(AuditLog.action == "cancel_appointment")
            )).scalars().all()

        assert len(rows) >= 1, "At least one audit_log entry for cancel_appointment expected"
        assert any(r.resource_id == appt_id for r in rows), \
            f"Expected audit row for appointment_id={appt_id}, got: {[r.resource_id for r in rows]}"

    async def test_cancelled_slot_appears_available_again(
        self, compiled_graph, seeded_db, mock_redis
    ):
        """
        After cancellation, the doctor's slot should no longer appear
        in the DB as an active appointment - which means
        AppointmentRepository.get_available_slots() can offer it again.
        The cancellation was a soft-delete (status=cancelled), so this
        verifies the slot is "freed" by confirming get_available_slots
        sees more open slots after cancellation than before.
        """
        from app.agents.state import create_initial_state
        from app.db.repositories.appointment_repo import AppointmentRepository

        appt_id = await _insert_test_appointment(seeded_db)

        async with seeded_db() as session:
            repo = AppointmentRepository(session)
            appt = (await session.execute(
                __import__("sqlalchemy", fromlist=["select"]).select(
                    __import__("app.db.models.appointment", fromlist=["Appointment"]).Appointment
                ).where(
                    __import__("app.db.models.appointment", fromlist=["Appointment"]).Appointment.appointment_id == appt_id
                )
            )).scalar_one()
            scheduled_date = appt.scheduled_at.date()
            slots_before = await repo.get_available_slots(doctor_id=1, target_date=scheduled_date)
            count_before = len(slots_before)

        state = create_initial_state(
            "sess_cancel_integration_03",
            patient_id="P-2024-00001",
            is_authenticated=True,
        )
        state["messages"] = [HumanMessage(content="yes")]
        state["pending_confirmation"] = {
            "action": "cancel_appointment",
            "summary": f"Cancel {appt_id}",
            "params": {"appointment_id": appt_id},
        }
        state["next_action"] = "confirmed"

        with patch("app.api.dependencies.get_redis_pool", new=AsyncMock(return_value=mock_redis)):
            await compiled_graph.ainvoke(state)

        async with seeded_db() as session:
            repo = AppointmentRepository(session)
            slots_after = await repo.get_available_slots(doctor_id=1, target_date=scheduled_date)
            count_after = len(slots_after)

        assert count_after > count_before, \
            f"Slot count should increase after cancellation: before={count_before}, after={count_after}"