import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


def _supervisor_response(intent: str, entities: dict | None = None) -> AIMessage:
    return AIMessage(content=json.dumps({
        "intent": intent,
        "entities": entities or {},
        "reasoning": f"Test routing to {intent}.",
    }))


def _get_next_monday() -> datetime:
    from datetime import date, timedelta
    today = date.today()
    days = (7 - today.weekday()) % 7 or 7
    next_monday = today + timedelta(days=days)
    return datetime(next_monday.year, next_monday.month, next_monday.day, 9, 0, 0)


class TestBookingFlow:
    """
    Full multi-turn booking conversation: slot filling → confirmation →
    appointment creation. Runs against a real SQLite DB with a real
    doctor and schedule seeded via conftest.py. Only the supervisor LLM
    and the booking agent LLM are mocked - all DB writes are real.
    """

    async def test_full_booking_flow_creates_appointment_in_db(
        self, compiled_graph, seeded_db, mock_redis
    ):
        """
        Simulates:
          Turn 1: "I want to book an appointment"
                  → supervisor routes to booking_agent
                  → booking_agent asks for patient identity
          Turn 2: patient supplies all slots
                  → booking_agent resolves doctor and availability
                  → sets pending_confirmation
          Turn 3: patient replies "yes"
                  → confirmation_handler sets next_action="confirmed"
                  → action_executor creates the appointment
          Assert: appointment row exists in the DB.
        """
        from app.agents.state import create_initial_state

        supervisor_book = _supervisor_response("book_appointment", {})
        next_monday_dt = _get_next_monday()

        with patch("app.agents.supervisor.agent.get_llm") as mock_sup_llm, \
             patch("app.memory.mysql_archive.get_redis_pool", new=AsyncMock(return_value=mock_redis)), \
             patch("app.memory.session_manager.get_redis_pool", new=AsyncMock(return_value=mock_redis)):

            mock_sup = AsyncMock()
            mock_sup.ainvoke = AsyncMock(return_value=supervisor_book)
            mock_sup_llm.return_value = mock_sup

            state1 = create_initial_state("sess_book_integration_01")
            state1["messages"] = [HumanMessage(content="I want to book an appointment")]

            result1 = await compiled_graph.ainvoke(state1)

        ai_messages_1 = [m for m in result1["messages"] if isinstance(m, AIMessage)]
        assert ai_messages_1, "Booking agent should have asked a slot question"
        first_question = ai_messages_1[-1].content
        assert any(kw in first_question.lower() for kw in ("patient id", "phone", "identity")), \
            f"Expected patient identity question, got: {first_question!r}"

        with patch("app.agents.supervisor.agent.get_llm") as mock_sup_llm, \
             patch("app.agents.booking.agent.get_llm") as mock_booking_llm, \
             patch("app.memory.mysql_archive.get_redis_pool", new=AsyncMock(return_value=mock_redis)), \
             patch("app.memory.session_manager.get_redis_pool", new=AsyncMock(return_value=mock_redis)):

            supervisor_book2 = _supervisor_response("book_appointment", {
                "specialization": "cardiologist",
                "date": next_monday_dt.date().isoformat(),
                "time": "9:00 AM",
            })
            mock_sup2 = AsyncMock()
            mock_sup2.ainvoke = AsyncMock(return_value=supervisor_book2)
            mock_sup_llm.return_value = mock_sup2

            summary_text = (
                f"Book Dr. Kamal Rahman (Cardiologist) on "
                f"{next_monday_dt.strftime('%A, %d %B %Y')} at 09:00 AM. "
                "Shall I go ahead? (yes/no)"
            )
            booking_summary_response = AIMessage(content=summary_text)
            mock_booking = AsyncMock()
            mock_booking.ainvoke = AsyncMock(return_value=booking_summary_response)
            mock_booking_llm.return_value = mock_booking

            state2 = create_initial_state(
                "sess_book_integration_01",
                patient_id="P-2024-00001",
                is_authenticated=True,
            )
            state2["messages"] = result1["messages"] + [HumanMessage(content="P-2024-00001")]
            state2["entities"] = {
                "specialization": "cardiologist",
                "date": next_monday_dt.date().isoformat(),
                "time": "9:00 AM",
            }
            state2["slot_fill_status"] = {
                "patient_identity": True,
                "preferred_doctor": True,
                "preferred_date": True,
                "preferred_time": True,
            }

            result2 = await compiled_graph.ainvoke(state2)

        ai_messages_2 = [m for m in result2["messages"] if isinstance(m, AIMessage)]
        assert result2.get("pending_confirmation") is not None, \
            "booking_agent should have set pending_confirmation"
        pending = result2["pending_confirmation"]
        assert pending["action"] == "create_appointment"
        assert pending["params"]["patient_id"] == "P-2024-00001"

        with patch("app.memory.mysql_archive.get_redis_pool", new=AsyncMock(return_value=mock_redis)), \
             patch("app.memory.session_manager.get_redis_pool", new=AsyncMock(return_value=mock_redis)):

            state3 = create_initial_state(
                "sess_book_integration_01",
                patient_id="P-2024-00001",
                is_authenticated=True,
            )
            state3["messages"] = result2["messages"] + [HumanMessage(content="yes please")]
            state3["pending_confirmation"] = pending

            result3 = await compiled_graph.ainvoke(state3)

        ai_messages_3 = [m for m in result3["messages"] if isinstance(m, AIMessage)]
        final_text = " ".join(m.content for m in ai_messages_3)

        assert any(kw in final_text.lower() for kw in ("booked", "appointment id", "all set")), \
            f"Expected booking confirmation in final response, got: {final_text!r}"

        async with seeded_db() as session:
            from app.db.models.appointment import Appointment
            result = await session.execute(
                select(Appointment).where(Appointment.patient_id == "P-2024-00001")
            )
            appointments = result.scalars().all()

        assert len(appointments) == 1, "Exactly one appointment should have been created"
        appt = appointments[0]
        assert appt.patient_id == "P-2024-00001"
        assert appt.scheduled_at.date() == next_monday_dt.date()
        assert appt.status in ("pending", "confirmed")

    async def test_booking_flow_does_not_create_appointment_on_no_reply(
        self, compiled_graph, seeded_db, mock_redis
    ):
        """
        If the patient says "no" to the confirmation summary, no
        appointment row should exist in the DB.
        """
        from app.agents.state import create_initial_state
        from app.db.models.appointment import Appointment

        next_monday_dt = _get_next_monday()

        state = create_initial_state(
            "sess_book_integration_02",
            patient_id="P-2024-00001",
            is_authenticated=True,
        )
        state["messages"] = [HumanMessage(content="no, cancel that")]
        state["pending_confirmation"] = {
            "action": "create_appointment",
            "summary": "Book Dr. Kamal Rahman on Monday at 09:00 AM",
            "params": {
                "patient_id": "P-2024-00001",
                "doctor_id": 1,
                "scheduled_at": next_monday_dt.isoformat(),
            },
        }

        with patch("app.memory.mysql_archive.get_redis_pool", new=AsyncMock(return_value=mock_redis)), \
             patch("app.memory.session_manager.get_redis_pool", new=AsyncMock(return_value=mock_redis)):
            result = await compiled_graph.ainvoke(state)

        async with seeded_db() as session:
            rows = (await session.execute(
                select(Appointment).where(Appointment.patient_id == "P-2024-00001")
            )).scalars().all()

        assert len(rows) == 0, "No appointment should be created when patient says no"
        assert result.get("pending_confirmation") is None