import json
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


pytestmark = pytest.mark.asyncio


def _mock_session_context(mock_session):
    """
    Build a mock async context manager matching the shape of
    app.db.base.get_session_context() - i.e. `async with get_session_context() as session:`.
    """
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestCancelAppointmentTool:
    """
    Covers app.tools.appointment_tools.cancel_appointment - the
    canonical, audit-logging version of this tool (Step 38), as
    opposed to the un-audited inline copy in
    app.agents.cancellation.agent from Step 32.
    """

    async def test_cancel_appointment_calls_audit_log_exactly_once_on_success(self):
        from app.tools.appointment_tools import cancel_appointment

        mock_appt = MagicMock()
        mock_appt.appointment_id = "APT-20241105-0001"
        mock_appt.status = "cancelled"
        mock_appt.patient_id = "P-2024-00001"

        mock_session = AsyncMock()

        with patch(
            "app.tools.appointment_tools.get_session_context",
            return_value=_mock_session_context(mock_session),
        ), patch(
            "app.tools.appointment_tools.AppointmentRepository"
        ) as MockApptRepo, patch(
            "app.tools.appointment_tools.AuditRepository"
        ) as MockAuditRepo:
            MockApptRepo.return_value.cancel = AsyncMock(return_value=mock_appt)
            mock_audit_instance = MockAuditRepo.return_value
            mock_audit_instance.log = AsyncMock()

            result_raw = await cancel_appointment.ainvoke({
                "appointment_id": "APT-20241105-0001",
                "reason": "Patient request",
            })

        result = json.loads(result_raw)
        assert result["success"] is True
        assert result["appointment_id"] == "APT-20241105-0001"

        mock_audit_instance.log.assert_awaited_once()
        call_kwargs = mock_audit_instance.log.await_args.kwargs
        assert call_kwargs["action"] == "cancel_appointment"
        assert call_kwargs["patient_id"] == "P-2024-00001"
        assert call_kwargs["resource_id"] == "APT-20241105-0001"

    async def test_cancel_appointment_does_not_audit_log_on_failure(self):
        """
        On a ValueError from the repository (e.g. cancellation policy
        violated), the tool returns success=false and must NOT write an
        audit_log entry for a mutation that never happened.
        """
        from app.tools.appointment_tools import cancel_appointment

        mock_session = AsyncMock()

        with patch(
            "app.tools.appointment_tools.get_session_context",
            return_value=_mock_session_context(mock_session),
        ), patch(
            "app.tools.appointment_tools.AppointmentRepository"
        ) as MockApptRepo, patch(
            "app.tools.appointment_tools.AuditRepository"
        ) as MockAuditRepo:
            MockApptRepo.return_value.cancel = AsyncMock(
                side_effect=ValueError("Cannot cancel within 24 hours of the appointment.")
            )
            mock_audit_instance = MockAuditRepo.return_value
            mock_audit_instance.log = AsyncMock()

            result_raw = await cancel_appointment.ainvoke({"appointment_id": "APT-20241105-0001"})

        result = json.loads(result_raw)
        assert result["success"] is False
        assert "24 hours" in result["error"]
        mock_audit_instance.log.assert_not_awaited()


class TestQueryMedicationInfoDisclaimer:
    """
    query_medication_info (app.tools.medication_tools) returns
    structured drug data, not patient-facing prose - it does NOT embed
    the disclaimer itself. The disclaimer is a hard guardrail enforced
    by _ensure_disclaimer() in app.agents.medication.agent, which wraps
    every FINAL response text the medication agent produces, regardless
    of what query_medication_info returned. This test covers that
    actual enforcement point, per Section 3.9 of the plan: "Always
    include disclaimer: 'This is general information only...'"
    """

    def test_ensure_disclaimer_appends_when_missing(self):
        from app.agents.medication.agent import _ensure_disclaimer
        from app.agents.medication.prompts import MEDICATION_DISCLAIMER

        response = "Metformin is used to treat type 2 diabetes."
        result = _ensure_disclaimer(response)

        assert MEDICATION_DISCLAIMER in result
        assert response in result

    def test_ensure_disclaimer_does_not_duplicate_when_already_present(self):
        from app.agents.medication.agent import _ensure_disclaimer
        from app.agents.medication.prompts import MEDICATION_DISCLAIMER

        response = f"Metformin is used to treat type 2 diabetes. {MEDICATION_DISCLAIMER}"
        result = _ensure_disclaimer(response)

        assert result.count(MEDICATION_DISCLAIMER) == 1

    def test_ensure_disclaimer_appends_when_dosage_language_detected(self):
        """
        Even if a disclaimer-like string is already present, dosage-
        directed language ("you should take") is a hard guardrail
        trigger - the canonical disclaimer is appended regardless.
        """
        from app.agents.medication.agent import _ensure_disclaimer
        from app.agents.medication.prompts import MEDICATION_DISCLAIMER

        response = "You should take 500mg twice daily."
        result = _ensure_disclaimer(response)

        assert MEDICATION_DISCLAIMER in result

    async def test_query_medication_info_returns_structured_data_not_prose(self):
        """
        Confirms query_medication_info itself returns a typed result
        with no disclaimer text embedded - establishing why the
        disclaimer guarantee must live at the agent layer, not here.
        """
        from app.tools.medication_tools import query_medication_info

        mock_medication = MagicMock()
        mock_medication.generic_name = "Metformin"
        mock_medication.brand_names = "Glucophage"
        mock_medication.drug_class = "Biguanide"
        mock_medication.common_uses = "Type 2 diabetes"
        mock_medication.side_effects = "Nausea, diarrhea"
        mock_medication.general_dosage = "500mg twice daily"
        mock_medication.requires_prescription = True

        mock_session = AsyncMock()

        with patch(
            "app.tools.medication_tools.get_session_context",
            return_value=_mock_session_context(mock_session),
        ), patch(
            "app.tools.medication_tools.MedicationRepository"
        ) as MockRepo:
            MockRepo.return_value.get_by_generic_name = AsyncMock(return_value=mock_medication)

            result = await query_medication_info.ainvoke({"drug_name": "metformin"})

        assert result.found is True
        assert result.generic_name == "Metformin"
        assert "consult your doctor" not in (result.general_dosage or "").lower()


class TestGetEmergencyContactsTool:
    """app.tools.emergency_tools.get_emergency_contacts must never raise."""

    async def test_returns_database_contacts_when_available(self):
        from app.tools.emergency_tools import get_emergency_contacts

        mock_row = MagicMock()
        mock_row.content = "Hospital Emergency Hotline (24/7): 109"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.tools.emergency_tools.get_session_context",
            return_value=_mock_session_context(mock_session),
        ):
            result = await get_emergency_contacts.ainvoke({})

        assert result.source == "database"
        assert "109" in result.contacts

    async def test_falls_back_to_hardcoded_contacts_on_db_error(self):
        from app.tools.emergency_tools import get_emergency_contacts, FALLBACK_EMERGENCY_CONTACTS

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("connection refused"))

        with patch(
            "app.tools.emergency_tools.get_session_context",
            return_value=_mock_session_context(mock_session),
        ):
            result = await get_emergency_contacts.ainvoke({})

        assert result.source == "fallback"
        assert result.contacts == FALLBACK_EMERGENCY_CONTACTS


class TestLogFeedbackTool:
    """app.tools.feedback_tools.log_feedback auto-escalation logic."""

    async def test_low_rating_triggers_escalation(self):
        from app.tools.feedback_tools import log_feedback

        mock_feedback_row = MagicMock()
        mock_feedback_row.feedback_id = 42

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        def _add_side_effect(obj):
            if hasattr(obj, "feedback_id"):
                pass

        with patch(
            "app.tools.feedback_tools.get_session_context",
            return_value=_mock_session_context(mock_session),
        ), patch(
            "app.tools.feedback_tools.Feedback"
        ) as MockFeedback, patch(
            "app.tools.feedback_tools.ComplaintTicket"
        ) as MockTicket, patch(
            "app.tools.feedback_tools._generate_ticket_id",
            new=AsyncMock(return_value="TKT-20241101-0001"),
        ), patch(
            "app.tools.feedback_tools.escalate_to_manager"
        ) as mock_escalate:
            MockFeedback.return_value = mock_feedback_row
            mock_escalate.ainvoke = AsyncMock()

            result = await log_feedback.ainvoke({
                "category": "doctor",
                "message": "Long wait time",
                "rating": 1,
                "patient_id": "P-2024-00001",
            })

        assert result.escalated is True
        assert result.ticket_id == "TKT-20241101-0001"
        mock_escalate.ainvoke.assert_awaited_once()

    async def test_good_rating_does_not_escalate(self):
        from app.tools.feedback_tools import log_feedback

        mock_feedback_row = MagicMock()
        mock_feedback_row.feedback_id = 43

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch(
            "app.tools.feedback_tools.get_session_context",
            return_value=_mock_session_context(mock_session),
        ), patch(
            "app.tools.feedback_tools.Feedback"
        ) as MockFeedback, patch(
            "app.tools.feedback_tools.escalate_to_manager"
        ) as mock_escalate:
            MockFeedback.return_value = mock_feedback_row
            mock_escalate.ainvoke = AsyncMock()

            result = await log_feedback.ainvoke({
                "category": "general",
                "message": "Great service!",
                "rating": 5,
                "patient_id": None,
            })

        assert result.escalated is False
        assert result.ticket_id is None
        mock_escalate.ainvoke.assert_not_awaited()


class TestValidateDateFormatTool:
    """app.tools.utility_tools.validate_date_format never raises."""

    async def test_valid_iso_date(self):
        from app.tools.utility_tools import validate_date_format

        result = await validate_date_format.ainvoke({"date_str": "2024-11-05"})
        assert result.valid is True
        assert result.normalized_date == "2024-11-05"

    async def test_invalid_date_does_not_raise(self):
        from app.tools.utility_tools import validate_date_format

        result = await validate_date_format.ainvoke({"date_str": "not a date at all"})
        assert result.valid is False
        assert result.error is not None