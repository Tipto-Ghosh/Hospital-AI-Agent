"""
The state schema — the single source of truth that flows
through every node in the multi-agent graph.

Tier 1 memory (in-graph state)
-------------------------------
HospitalAgentState is Tier 1 of the three-tier memory architecture. 
It lives only for the duration of a single
graph traversal (one request/response turn). Tiers 2 (Redis) and 3
(MySQL) are populated/read by the load_session_memory and save_memory
nodes, which translate between this in-graph state and persistent
storage.

Field-by-field reference
-------------------------
messages: All conversation messages so far.
session_id: Redis/DB session key. Set once at graph entry by the input_handler node and never changed.

patient_id: Patient PK once authenticated. None for
    unauthenticated sessions.

is_authenticated:
    Mirrors PatientRepository.verify_identity() result for this
    session. Gates access to records_agent and billing_agent.

intent: 
    One of INTENT_LABELS, set by the supervisor node after LLM-based
    classification. None before the first classification.

active_agent:
    Name of the sub-agent currently handling the turn, e.g.
    "booking_agent". Used by save_memory to tag ConversationMemory
    rows with agent_name, and by the API layer to populate the
    ChatResponse.agent field.

entities:
    Free-form dict of resolved entities extracted from the
    conversation: doctor_id, appointment_id, date, time,
    specialization, medication_name, etc. Populated incrementally by
    the supervisor and sub-agents as the conversation progresses.
    Example: {"doctor_id": 3, "date": "2024-11-05", "time": "10:00"}

slot_fill_status
    Maps slot names to "filled" | "missing" for the agent currently
    running a slot-filling flow (primarily booking_agent). Example:
        {
          "patient_identity": "filled",
          "preferred_doctor": "filled",
          "preferred_date": "missing",
          "preferred_time": "missing",
          "reason_for_visit": "filled",
        }
    The slot_fill_handler node reads this to generate the next
    targeted question.

pending_confirmation
    None, or a dict describing a write operation awaiting an explicit
    yes/no from the patient before action_executor runs it. Example:
        {
          "action": "create_appointment",
          "summary": "Book Dr. Rahman on 2024-11-05 at 10:00 AM",
          "params": {"doctor_id": 3, "scheduled_at": "2024-11-05T10:00:00", ...},
        }
    Set by confirmation_handler, consumed by action_executor or
    fallback (if the patient declines).

is_emergency
    True if EMERGENCY_KEYWORDS matched the latest human message, OR
    the supervisor's LLM classification returned intent="emergency".
    Once True, the emergency_interrupt node fires immediately,
    bypassing all normal routing (Section 7.3).

error
    None, or a human-readable error message set by any node that
    encounters a recoverable failure (e.g. a tool call raised
    ValueError). The fallback node surfaces this to the patient in a
    safe, non-technical way.

tool_results
    List of raw results returned by tool/repository calls during this
    turn. Used for debugging and for the confirmation_handler to build
    pending_confirmation summaries. Each entry is a dict, e.g.
        {"tool": "get_available_slots", "result": [...]}
    NEVER contains raw PHI rows — repositories already return
    sanitised ORM objects/dataclasses, and tool wrappers convert these
    to plain dicts before appending here.

next_action
    String used by LangGraph's conditional edges to decide routing.
    Set by the supervisor (e.g. "booking_agent", "emergency_interrupt",
    "fallback") and by intermediate nodes (e.g. slot_fill_handler sets
    next_action="supervisor" to loop back for re-routing once all
    slots are filled).
"""

from __future__ import annotations
from typing import Annotated, Any, Optional, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


# HospitalAgentState
class HospitalAgentState(TypedDict):
    """
    The complete LangGraph state object for one conversation turn.

    All fields are present in every state dict (LangGraph TypedDicts
    are total by default) — optional fields use Optional[...] and are
    initialised to None / empty collections by the input_handler node
    on the first turn, and preserved/updated on subsequent turns via
    the Redis-backed checkpointer (Phase 3).
    """

    # Conversation history 
    messages: Annotated[list[BaseMessage], add_messages]

    # Session & identity
    session_id: str
    patient_id: Optional[str]
    is_authenticated: bool

    # Routing 
    intent: Optional[str]
    active_agent: Optional[str]

    # Slot filling & entity resolution 
    entities: dict[str, Any]
    slot_fill_status: dict[str, str]

    # Confirmation flow 
    pending_confirmation: Optional[dict[str, Any]]

    # Safety 
    is_emergency: bool

    # Error handling 
    error: Optional[str]

    # Tool execution trace 
    tool_results: list[dict[str, Any]]

    # Conditional-edge routing target 
    next_action: str

INTENT_LABELS: list[str] = [
    "general_info",
    "doctor_info",
    "book_appointment",
    "cancel_appointment",
    "reschedule_appointment",
    "patient_records",
    "billing",
    "medication_info",
    "feedback",
    "emergency",
    "out_of_scope",
]

EMERGENCY_KEYWORDS: list[str] = [
    "chest pain",
    "can't breathe",
    "cant breathe",        
    "cannot breathe",
    "stroke",
    "unconscious",
    "severe bleeding",
    "heart attack",
    "overdose",
    "seizure",
    "not responding",
    "emergency",
]


def contains_emergency_keyword(text: str) -> bool:
    """
    Case-insensitive substring check of `text` against EMERGENCY_KEYWORDS.

    Used by the input_handler / supervisor node as the fast pre-LLM
    emergency gate described above.

    Parameters
    ----------
    text    The latest human message content.

    Returns
    -------
    True if any keyword in EMERGENCY_KEYWORDS appears as a substring of
    `text` (case-insensitive). False if `text` is empty or no keyword
    matches.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in lowered for keyword in EMERGENCY_KEYWORDS)


# State factory helper
def create_initial_state(
    session_id: str,
    patient_id: Optional[str] = None,
    is_authenticated: bool = False,
) -> HospitalAgentState:
    """
    Build a fresh HospitalAgentState for the start of a graph traversal.

    Parameters
    ----------
    session_id: Redis/DB session key for this conversation.
    patient_id: Patient PK if already known (e.g. resumed authenticated session). None otherwise.
    is_authenticated: True if this session has already passed verify_identity() in a prior turn.
    """
    return HospitalAgentState(
        messages=[],
        session_id=session_id,
        patient_id=patient_id,
        is_authenticated=is_authenticated,
        intent=None,
        active_agent=None,
        entities={},
        slot_fill_status={},
        pending_confirmation=None,
        is_emergency=False,
        error=None,
        tool_results=[],
        next_action="supervisor",
    )