import json
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

pytestmark = pytest.mark.asyncio


class TestSupervisorEmergencyRouting:
    """
    Section 3.1 / 3.8: "if any emergency keyword is present, intent
    must be 'emergency' regardless of other content." This is the
    fast, pre-LLM keyword path in supervisor_node - no LLM call should
    even occur for this case.
    """

    async def test_chest_pain_routes_to_emergency_without_llm_call(self):
        from app.agents.state import create_initial_state
        from app.agents.supervisor.agent import supervisor_node

        state = create_initial_state("sess_test_001")
        state["messages"] = [HumanMessage(content="I have severe chest pain right now")]

        with patch("app.agents.supervisor.agent.get_llm") as mock_get_llm:
            result = await supervisor_node(state)

        mock_get_llm.assert_not_called()
        assert result["intent"] == "emergency"
        assert result["is_emergency"] is True
        assert result["next_action"] == "emergency_interrupt"

    async def test_non_emergency_message_does_not_set_emergency(self):
        from app.agents.state import create_initial_state
        from app.agents.supervisor.agent import supervisor_node

        state = create_initial_state("sess_test_002")
        state["messages"] = [HumanMessage(content="What are your visiting hours?")]

        fake_response = AIMessage(content=json.dumps({
            "intent": "general_info",
            "entities": {},
            "reasoning": "Patient asked about visiting hours.",
        }))

        with patch("app.agents.supervisor.agent.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=fake_response)
            mock_get_llm.return_value = mock_llm

            result = await supervisor_node(state)

        assert result["intent"] == "general_info"
        assert result["is_emergency"] is False
        assert result["next_action"] == "info_agent"

    async def test_llm_classified_emergency_also_sets_is_emergency(self):
        """
        The LLM-based classification is a second safety net beyond the
        keyword scan - e.g. "my dad just collapsed" contains no listed
        keyword but should still classify as emergency.
        """
        from app.agents.state import create_initial_state
        from app.agents.supervisor.agent import supervisor_node

        state = create_initial_state("sess_test_003")
        state["messages"] = [HumanMessage(content="my dad just collapsed and isn't moving")]

        fake_response = AIMessage(content=json.dumps({
            "intent": "emergency",
            "entities": {},
            "reasoning": "Possible medical emergency described.",
        }))

        with patch("app.agents.supervisor.agent.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=fake_response)
            mock_get_llm.return_value = mock_llm

            result = await supervisor_node(state)

        assert result["intent"] == "emergency"
        assert result["is_emergency"] is True
        assert result["next_action"] == "emergency_interrupt"


class TestSlotFillHandler:
    """
    slot_fill_handler_node reads state["slot_fill_status"] (NOT
    state["entities"] directly) to find the first missing required slot.
    """

    async def test_empty_slot_status_asks_about_patient_identity_first(self):
        from app.agents.state import create_initial_state
        from app.agents.shared.fallback import slot_fill_handler_node

        state = create_initial_state("sess_test_004")
        state["slot_fill_status"] = {}
        state["entities"] = {}

        result = await slot_fill_handler_node(state)

        assert result["next_action"] == "await_slot"
        question = result["messages"][0].content
        assert "patient ID" in question or "phone" in question

    async def test_all_slots_filled_routes_back_to_supervisor(self):
        from app.agents.state import create_initial_state
        from app.agents.shared.fallback import slot_fill_handler_node

        state = create_initial_state("sess_test_005")
        state["slot_fill_status"] = {
            "patient_identity": True,
            "preferred_doctor": True,
            "preferred_date": True,
            "preferred_time": True,
        }

        result = await slot_fill_handler_node(state)

        assert result["next_action"] == "supervisor"
        assert "messages" not in result

    async def test_partial_slots_asks_about_first_missing_one(self):
        from app.agents.state import create_initial_state
        from app.agents.shared.fallback import slot_fill_handler_node

        state = create_initial_state("sess_test_006")
        state["slot_fill_status"] = {
            "patient_identity": True,
            "preferred_doctor": False,
            "preferred_date": False,
            "preferred_time": False,
        }
        state["entities"] = {"patient_id": "P-2024-00001"}

        result = await slot_fill_handler_node(state)

        assert result["next_action"] == "await_slot"
        question = result["messages"][0].content
        assert "doctor" in question.lower() or "specialist" in question.lower()


class TestConfirmationHandler:
    """
    confirmation_handler_node reads state["pending_confirmation"] and
    the latest patient reply to decide next_action.
    """

    async def test_yes_reply_sets_next_action_confirmed(self):
        from app.agents.state import create_initial_state
        from app.agents.shared.confirmation_handler import confirmation_handler_node

        state = create_initial_state("sess_test_007")
        state["pending_confirmation"] = {
            "action": "create_appointment",
            "summary": "Book Dr. Rahman on Friday at 2pm",
            "params": {
                "patient_id": "P-2024-00001",
                "doctor_id": 1,
                "scheduled_at": "2024-11-08T14:00:00",
            },
        }
        state["messages"] = [HumanMessage(content="yes")]

        result = await confirmation_handler_node(state)

        assert result["next_action"] == "confirmed"

    async def test_no_reply_aborts_and_clears_pending_confirmation(self):
        from app.agents.state import create_initial_state
        from app.agents.shared.confirmation_handler import confirmation_handler_node

        state = create_initial_state("sess_test_008")
        state["pending_confirmation"] = {
            "action": "cancel_appointment",
            "summary": "Cancel appointment APT-001",
            "params": {"appointment_id": "APT-001"},
        }
        state["messages"] = [HumanMessage(content="no, don't cancel it")]

        result = await confirmation_handler_node(state)

        assert result["next_action"] == "aborted"
        assert result["pending_confirmation"] is None

    async def test_ambiguous_reply_reprompts_without_changing_pending_confirmation(self):
        from app.agents.state import create_initial_state
        from app.agents.shared.confirmation_handler import confirmation_handler_node

        state = create_initial_state("sess_test_009")
        pending = {
            "action": "create_appointment",
            "summary": "Book Dr. Rahman on Friday at 2pm",
            "params": {},
        }
        state["pending_confirmation"] = pending
        state["messages"] = [HumanMessage(content="hmm what was that again")]

        result = await confirmation_handler_node(state)

        assert result["next_action"] == "end"
        assert "Just to confirm" in result["messages"][0].content
        assert "pending_confirmation" not in result

    async def test_no_pending_confirmation_routes_to_fallback(self):
        from app.agents.state import create_initial_state
        from app.agents.shared.confirmation_handler import confirmation_handler_node

        state = create_initial_state("sess_test_010")
        state["pending_confirmation"] = None
        state["messages"] = [HumanMessage(content="yes")]

        result = await confirmation_handler_node(state)

        assert result["next_action"] == "fallback"
        assert result["error"] is not None


class TestConfirmedReplyTriggersActionExecutor:
    """
    The step's exact scenario: "given state['pending_confirmation']
    set, a 'yes' reply triggers action_executor" - i.e. the
    confirmation_handler's "confirmed" output is exactly the signal
    action_executor_node acts on. This test exercises that handoff
    directly (action_executor_node's own tool-calling internals are
    mocked - the assertion here is about the next_action contract
    between the two nodes, not the appointment-creation logic itself,
    which is covered in test_tools.py).
    """

    async def test_confirmed_next_action_causes_action_executor_to_run(self):
        from app.agents.state import create_initial_state
        from app.agents.shared.confirmation_handler import action_executor_node

        state = create_initial_state("sess_test_011")
        state["pending_confirmation"] = {
            "action": "create_appointment",
            "summary": "Book Dr. Rahman on Friday at 2pm",
            "params": {
                "patient_id": "P-2024-00001",
                "doctor_id": 1,
                "scheduled_at": "2024-11-08T14:00:00",
            },
        }
        state["next_action"] = "confirmed"

        fake_tool_result = json.dumps({
            "success": True,
            "appointment_id": "APT-20241108-0001",
            "scheduled_at": "2024-11-08T14:00:00",
            "status": "pending",
        })

        with patch(
            "app.agents.shared.confirmation_handler.create_appointment"
        ) as mock_create, patch(
            "app.agents.shared.confirmation_handler.get_session_context"
        ), patch(
            "app.agents.shared.confirmation_handler.AuditRepository"
        ) as MockAuditRepo, patch(
            "app.agents.shared.confirmation_handler.AppointmentRepository"               
        ) as MockAppointmentRepo:
            mock_create.ainvoke = AsyncMock(return_value=fake_tool_result)
            MockAuditRepo.return_value.log = AsyncMock()
            
            mock_appt_repo = MockAppointmentRepo.return_value
            mock_appt_repo.confirm = AsyncMock()
            
            result = await action_executor_node(state)

        mock_create.ainvoke.assert_awaited_once()
        assert result["next_action"] == "end"
        assert result["pending_confirmation"] is None
        assert "APT-20241108-0001" in result["messages"][0].content

    async def test_action_executor_is_noop_when_not_confirmed(self):
        """
        action_executor_node must not perform any write unless
        next_action is exactly 'confirmed' - a defensive guard against
        being reached via an unexpected graph path.
        """
        from app.agents.state import create_initial_state
        from app.agents.shared.confirmation_handler import action_executor_node

        state = create_initial_state("sess_test_012")
        state["pending_confirmation"] = {
            "action": "create_appointment",
            "summary": "...",
            "params": {},
        }
        state["next_action"] = "end"

        with patch(
            "app.agents.shared.confirmation_handler.create_appointment"
        ) as mock_create:
            mock_create.ainvoke = AsyncMock()
            result = await action_executor_node(state)

        mock_create.ainvoke.assert_not_awaited()
        assert result == {}