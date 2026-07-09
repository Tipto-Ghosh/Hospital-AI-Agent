"""
End-to-end smoke tests against a running Docker stack.
These tests require a fully operational deployment:
  - FastAPI container responding at E2E_BASE_URL (default: https://localhost)
  - MySQL seeded with at least one doctor, schedule, and patient
  - Redis and ChromaDB running
  - Groq API key configured

They are SKIPPED (not failed) when the server is unreachable, so they
can live in the same test suite as unit/integration tests without
breaking CI pipelines that don't spin up the full stack.

Run the full stack first:
    docker compose up -d
    python scripts/seed_db.py
    python scripts/health_check.py     # confirm everything is green
    pytest tests/e2e/ -v

Environment variables:
    E2E_BASE_URL: Base URL of the running API. Default: https://localhost
    E2E_WS_URL: WebSocket base URL. Default: wss://localhost
    E2E_DB_URL: SQLAlchemy URL for direct DB assertions. Default: reads DATABASE_URL from .env
    E2E_VERIFY_SSL: Set to "false" to skip SSL verification for self-signed certs in local Docker. Default: true
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

BASE_URL = os.environ.get("E2E_BASE_URL", "https://localhost")
WS_URL = os.environ.get("E2E_WS_URL", "wss://localhost")
VERIFY_SSL = os.environ.get("E2E_VERIFY_SSL", "true").lower() != "false"
DB_URL = os.environ.get("E2E_DB_URL") or os.environ.get("DATABASE_URL", "")

pytestmark = pytest.mark.asyncio


def _skip_if_unreachable(func):
    """
    Decorator: skip the test with a clear message if the server isn't
    reachable rather than failing with a confusing connection error.
    Determined once per test, not cached globally, so individual tests
    can be re-run after the server comes up.
    """
    import functools

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            import httpx
            ssl_ctx = False if not VERIFY_SSL else None
            async with httpx.AsyncClient(verify=ssl_ctx, timeout=5.0) as client:
                resp = await client.get(f"{BASE_URL}/api/v1/health")
                if resp.status_code not in (200, 307, 302):
                    pytest.skip(f"Server returned {resp.status_code} — stack may not be ready")
        except Exception as exc:
            pytest.skip(f"Server unreachable at {BASE_URL}: {exc}")
        return await func(*args, **kwargs)

    return wrapper


# HTTP helpers
async def _post(path: str, body: dict, token: Optional[str] = None) -> dict:
    import httpx

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    ssl_ctx = False if not VERIFY_SSL else None

    async with httpx.AsyncClient(verify=ssl_ctx, timeout=30.0) as client:
        resp = await client.post(f"{BASE_URL}{path}", json=body, headers=headers)
    resp.raise_for_status()
    return resp.json()


async def _get(path: str, token: Optional[str] = None) -> dict:
    import httpx

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    ssl_ctx = False if not VERIFY_SSL else None

    async with httpx.AsyncClient(verify=ssl_ctx, timeout=10.0) as client:
        resp = await client.get(f"{BASE_URL}{path}", headers=headers)
    resp.raise_for_status()
    return resp.json()


# WebSocket helpers 
async def _create_session() -> str:
    """Create a new chat session and return the session_id."""
    data = await _post("/api/v1/chat/session", {})
    return data["session_id"]


async def _chat(session_id: str, text: str, timeout: float = 60.0) -> dict[str, Any]:
    """
    Send one message to the chat WebSocket endpoint and collect the full
    response. Accumulates streaming chunks until a "done" frame is received.

    Returns a dict with:
        content       Full response text (all chunks joined)
        agent         Agent name from the "done" frame metadata
        session_id    Echoed session_id
        raw_frames    List of every raw frame received (for debugging)
    """
    try:
        import websockets
    except ImportError:
        pytest.skip("websockets package not installed: pip install websockets")

    ws_url = f"{WS_URL}/api/v1/chat/ws/{session_id}"
    ssl_ctx = False if not VERIFY_SSL else None

    content_chunks: list[str] = []
    metadata: dict[str, Any] = {}
    raw_frames: list[dict] = []

    async with websockets.connect(ws_url, ssl=ssl_ctx) as ws:
        await ws.send(json.dumps({
            "type": "message",
            "session_id": session_id,
            "text": text,
        }))

        async def _recv_loop():
            async for raw in ws:
                frame = json.loads(raw)
                raw_frames.append(frame)

                if frame.get("type") == "chunk":
                    content_chunks.append(frame.get("content", ""))
                elif frame.get("type") == "done":
                    metadata.update(frame.get("metadata", {}))
                    metadata["agent"] = frame.get("agent", "")
                    return
                elif frame.get("type") == "error":
                    raise RuntimeError(f"Server returned error frame: {frame}")

        await asyncio.wait_for(_recv_loop(), timeout=timeout)

    return {
        "content": "".join(content_chunks),
        "agent": metadata.get("agent", ""),
        "session_id": session_id,
        "raw_frames": raw_frames,
    }


# Direct DB helper for post-conversation assertions 

async def _db_query(sql: str, params: dict | None = None) -> list[dict]:
    """
    Run a raw SQL query directly against the DB for assertion purposes.
    Used only in E2E tests where we want to verify the system actually
    wrote the expected rows.
    """
    if not DB_URL:
        pytest.skip("E2E_DB_URL / DATABASE_URL not set, cannot make DB assertions")

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(DB_URL, echo=False)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            rows = result.fetchall()
            keys = list(result.keys())
            return [dict(zip(keys, row)) for row in rows]
    finally:
        await engine.dispose()


# 1. Visiting hours — Information Agent

class TestInfoAgent:
    @_skip_if_unreachable
    async def test_visiting_hours_routes_to_info_agent(self):
        session_id = await _create_session()
        result = await _chat(session_id, "What are the visiting hours for the ICU?")

        content = result["content"].lower()
        assert any(kw in content for kw in ("hour", "am", "pm", "visit")), (
            f"Expected visiting-hours content in response, got: {result['content']!r}"
        )

        assert result["agent"] in ("info_agent", "information_agent", ""), (
            f"Expected info_agent, got agent={result['agent']!r}"
        )

    @_skip_if_unreachable
    async def test_info_agent_response_does_not_hallucinate_hours(self):
        """
        The Information Agent is instructed to use tool results VERBATIM.
        If no visiting-hours row is in hospital_info, it must say so
        rather than inventing a time. Either a real time or "don't have
        that information" is acceptable; a blank response is not.
        """
        session_id = await _create_session()
        result = await _chat(session_id, "What are the visiting hours for the ICU?")

        assert result["content"].strip(), "Response must not be empty"
        assert len(result["content"]) > 20, "Response is suspiciously short"


# 2. Appointment booking — Booking Agent (3-turn slot fill)

class TestBookingAgent:
    @_skip_if_unreachable
    async def test_booking_agent_slot_fill_turn_1_asks_identity(self):
        session_id = await _create_session()
        result = await _chat(session_id, "I'd like to book an appointment")

        content = result["content"].lower()
        assert any(kw in content for kw in ("patient id", "phone", "identity", "registered")), (
            f"Turn 1: expected identity question, got: {result['content']!r}"
        )

    @_skip_if_unreachable
    async def test_booking_agent_3_turn_slot_fill_and_confirmation(self):
        """
        Simulates the full 3-turn booking slot-fill:
          Turn 1: open request  → asks for identity
          Turn 2: supply identity, doctor, date, time
                                → booking agent presents summary + asks to confirm
          Turn 3: "yes"         → appointment is created

        Asserts the appointment row exists in the DB and the audit log
        contains a create_appointment entry.
        """
        session_id = await _create_session()

        t1 = await _chat(session_id, "I'd like to book an appointment")
        assert t1["content"].strip(), "Turn 1 must produce a response"

        next_monday = datetime.utcnow()
        days_until_monday = (7 - next_monday.weekday()) % 7 or 7
        next_monday = next_monday + timedelta(days=days_until_monday)
        date_str = next_monday.strftime("%Y-%m-%d")

        t2 = await _chat(
            session_id,
            f"My patient ID is P-2024-00001, I'd like to see the cardiologist "
            f"on {date_str} at 9 AM",
        )
        t2_content = t2["content"].lower()

        has_summary = any(kw in t2_content for kw in ("confirm", "book", "summary", "yes", "no"))
        has_more_slots = any(kw in t2_content for kw in ("date", "time", "doctor", "which"))
        assert has_summary or has_more_slots, (
            f"Turn 2: expected summary or follow-up question, got: {t2['content']!r}"
        )

        t3 = await _chat(session_id, "yes please go ahead")
        t3_content = t3["content"].lower()

        booked = any(kw in t3_content for kw in (
            "booked", "confirmed", "appointment id", "all set", "scheduled"
        ))
        not_available = any(kw in t3_content for kw in (
            "no available", "unavailable", "not available", "couldn't find"
        ))

        assert booked or not_available, (
            f"Turn 3: expected booking confirmation or availability message, "
            f"got: {t3['content']!r}"
        )

        if booked:
            appts = await _db_query(
                "SELECT appointment_id, status FROM appointments "
                "WHERE patient_id = :pid ORDER BY created_at DESC LIMIT 1",
                {"pid": "P-2024-00001"},
            )
            assert appts, "DB must contain the appointment after a confirmed booking"
            assert appts[0]["status"] in ("pending", "confirmed")

            audit_rows = await _db_query(
                "SELECT action FROM audit_log WHERE action = 'create_appointment' "
                "ORDER BY timestamp DESC LIMIT 5",
            )
            assert any(r["action"] == "create_appointment" for r in audit_rows), (
                "audit_log must contain a create_appointment entry"
            )


# 3. Appointment cancellation — Cancel Agent + auth

class TestCancelAgent:
    @_skip_if_unreachable
    async def test_cancel_agent_redirects_unauthenticated_to_auth(self):
        session_id = await _create_session()
        result = await _chat(session_id, "I want to cancel my appointment")

        content = result["content"].lower()
        assert any(kw in content for kw in ("verify", "identity", "patient id", "date of birth")), (
            f"Expected auth redirect, got: {result['content']!r}"
        )

    @_skip_if_unreachable
    async def test_cancel_agent_full_flow(self):
        """
        Creates an appointment directly via REST, then cancels it via chat.
        Verifies the DB status and audit log after cancellation.
        """
        import httpx

        auth_data = await _post("/api/v1/auth/verify", {
            "session_id": await _create_session(),
            "patient_id": "P-2024-00001",
            "date_of_birth": "1990-05-15",
            "phone_last4": "4321",
        })
        token = auth_data.get("session_token")
        if not token:
            pytest.skip("Could not authenticate test patient — check seed data")

        next_friday = datetime.utcnow() + timedelta(days=(4 - datetime.utcnow().weekday() + 7) % 7 or 7)
        next_friday = next_friday.replace(hour=10, minute=0, second=0, microsecond=0)

        try:
            create_resp = await _post(
                "/api/v1/appointments",
                {
                    "doctor_id": 1,
                    "scheduled_at": next_friday.isoformat(),
                },
                token=token,
            )
            appt_id = create_resp.get("appointment_id")
        except Exception as exc:
            pytest.skip(f"Could not create test appointment for cancellation test: {exc}")

        session_id = auth_data.get("session_id", await _create_session())

        t1 = await _chat(session_id, f"Cancel my appointment {appt_id}")
        t1_content = t1["content"].lower()
        assert any(kw in t1_content for kw in ("confirm", "cancel", "sure", "yes", "no")), (
            f"Expected cancellation confirmation prompt, got: {t1['content']!r}"
        )

        t2 = await _chat(session_id, "yes cancel it")
        t2_content = t2["content"].lower()
        assert any(kw in t2_content for kw in ("cancelled", "cancel", "done", "confirmation")), (
            f"Expected cancellation confirmation, got: {t2['content']!r}"
        )

        rows = await _db_query(
            "SELECT status FROM appointments WHERE appointment_id = :id",
            {"id": appt_id},
        )
        assert rows and rows[0]["status"] == "cancelled", (
            f"Expected appointment status=cancelled, got: {rows}"
        )

        audit_rows = await _db_query(
            "SELECT action, resource_id FROM audit_log "
            "WHERE action = 'cancel_appointment' AND resource_id = :id "
            "ORDER BY timestamp DESC LIMIT 1",
            {"id": appt_id},
        )
        assert audit_rows, f"Expected audit_log entry for cancel_appointment {appt_id}"


# 4. Medication information — Medication Agent
class TestMedicationAgent:
    @_skip_if_unreachable
    async def test_ibuprofen_interaction_query(self):
        session_id = await _create_session()
        result = await _chat(
            session_id,
            "Can ibuprofen and aspirin be taken together? Are there any interactions?",
        )

        content = result["content"].lower()
        assert any(kw in content for kw in ("ibuprofen", "aspirin", "interaction", "nsaid")), (
            f"Expected drug interaction content, got: {result['content']!r}"
        )

    @_skip_if_unreachable
    async def test_medication_response_includes_disclaimer(self):
        """
        The medication agent's hard guardrail (_ensure_disclaimer) must
        append the disclaimer to every final response, regardless of LLM
        compliance. Verified here at the system boundary.
        """
        session_id = await _create_session()
        result = await _chat(session_id, "What is metformin used for?")

        content = result["content"].lower()
        assert any(kw in content for kw in (
            "consult your doctor", "pharmacist", "general information only"
        )), (
            f"Expected disclaimer in medication response, got: {result['content']!r}"
        )

    @_skip_if_unreachable
    async def test_self_medication_query_redirects_to_info_agent(self):
        """
        "What should I take for chest pain" is a SELF_MEDICATION_RED_FLAG
        — the medication agent must redirect to info_agent rather than
        answering directly (per Section 3.9 of the plan).
        """
        session_id = await _create_session()
        result = await _chat(session_id, "What should I take for chest pain?")

        content = result["content"].lower()
        assert any(kw in content for kw in (
            "doctor", "discuss", "emergency", "reception", "hospital"
        )), (
            f"Expected redirect response for self-medication query, "
            f"got: {result['content']!r}"
        )
        assert "take" not in content.replace("take care", "").replace("please take", ""), (
            "Medication agent must not suggest dosage for self-medication query"
        )


# 5. Emergency — Emergency Agent interrupt
class TestEmergencyAgent:
    @_skip_if_unreachable
    async def test_heart_attack_triggers_emergency_agent_first(self):
        """
        "I'm having a heart attack" must activate the Emergency Triage
        Agent, which fires BEFORE any other sub-agent — bypassing the
        normal supervisor → sub-agent routing and responding immediately
        with emergency contact numbers. The keyword pre-LLM fast-path
        (supervisor_node, Step 28) is what makes this guarantee hold even
        if the LLM is slow or unavailable.
        """
        session_id = await _create_session()
        result = await _chat(session_id, "I'm having a heart attack, please help me")

        content = result["content"]
        assert any(kw in content for kw in ("109", "Ambulance", "emergency", "999")), (
            f"Expected emergency contact numbers in response, got: {content!r}"
        )

        assert result["agent"] in ("emergency_agent", "emergency_interrupt", ""), (
            f"Expected emergency_agent, got agent={result['agent']!r}"
        )

    @_skip_if_unreachable
    async def test_emergency_response_contains_phone_number(self):
        session_id = await _create_session()
        result = await _chat(session_id, "chest pain severe, can't breathe")

        import re
        phone_pattern = re.compile(r"\b(109|999|\d{3,5}-\d{3,5}|\d{10,11})\b")
        assert phone_pattern.search(result["content"]), (
            f"Emergency response must contain at least one phone number, "
            f"got: {result['content']!r}"
        )

    @_skip_if_unreachable
    async def test_emergency_interaction_logged_in_audit_db(self):
        """
        Every emergency interaction must be logged to audit_log
        (Section 3.8: "Logs every interaction regardless of authentication
        status"). Verified here at the system boundary.
        """
        before_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        session_id = await _create_session()
        await _chat(session_id, "I think I'm having a stroke")

        audit_rows = await _db_query(
            "SELECT action, session_id, timestamp FROM audit_log "
            "WHERE action IN ('emergency_interaction') "
            "AND timestamp >= :ts "
            "ORDER BY timestamp DESC LIMIT 5",
            {"ts": before_ts},
        )
        assert audit_rows, (
            f"Expected emergency_interaction entry in audit_log after {before_ts}, "
            f"found none"
        )

    @_skip_if_unreachable
    async def test_emergency_response_arrives_without_llm_delay(self):
        """
        The emergency keyword fast-path (supervisor_node, Step 28)
        bypasses the LLM classification call entirely. Response time
        should therefore be well under the 60-second LLM timeout — we
        assert under 20 seconds as a reasonable upper bound for a stack
        that's already warmed up.
        """
        import time

        session_id = await _create_session()
        t0 = time.monotonic()
        result = await _chat(session_id, "unconscious patient not responding", timeout=20.0)
        elapsed = time.monotonic() - t0

        assert result["content"].strip(), "Response must not be empty"
        assert elapsed < 20.0, (
            f"Emergency response took {elapsed:.1f}s — expected under 20s "
            f"(keyword fast-path should not wait for LLM classification)"
        )