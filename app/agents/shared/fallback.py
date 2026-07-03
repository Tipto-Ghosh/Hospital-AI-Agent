""" 
out of scope handler and slot filling agent

Fallback node reached when the supervisor classifies intent as "unknown" or "out of 
scope". Returns a friendly message summarizing what the system can help with and points 
the patient to reception for anything else.
"""

from __future__ import annotations
from typing import Any
from langchain_core.messages import AIMessage

from app.agents.booking.slot_filler import generate_slot_question, get_next_missing_slot
from app.agents.state import HospitalAgentState
from app.config import get_settings
from app.logger import logging

logger = logging.getLogger(__name__)

""" 
The list of things the system can help with, shown to the patient
when their request falls outside the supported intents.
"""
SUPPORTED_TOPICS = [
    "General hospital information - hours, locations, departments, and doctors",
    "Booking, cancelling, or rescheduling appointments",
    "Your medical records, lab results, and prescriptions (after identity verification)",
    "Billing, invoices, and insurance questions",
    "General medication information",
    "Feedback or complaints",
]

def _format_fallback_message() -> str:
    """Build the friendly "here's what I can help with" fallback message."""
    topics = "\n".join(f"- {topic}" for topic in SUPPORTED_TOPICS)
    return (
        "I'm not sure I can help with that directly, but here's what I "
        f"can do:\n{topics}\n\n"
        "For anything else, please contact reception at 16700 "
        "(8:00 AM - 10:00 PM, Saturday to Thursday)."
    )
    

async def fallback_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Fallback graph node.
 
    Reached when state["intent"] is "unknown" or "out_of_scope" (or
    when next_action="fallback" is set defensively by another node,
    e.g. on an LLM parse failure).
 
    Returns
    -------
    A partial state update dict: appends the fallback message and sets
    next_action="end".
    """
    session_id = state["session_id"]
    intent = state.get("intent")
 
    logger.info(f"fallback_node: session={session_id} intent={intent!r}")
 
    return {
        "messages": [AIMessage(content=_format_fallback_message())],
        "active_agent": "fallback",
        "next_action": "end",
    }

async def slot_fill_handler_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The shared Slot Fill Handler graph node.
 
    Flow
    ----
    1. Read state["slot_fill_status"] (populated by an agent such as
       booking_agent_node via check_slots()) and find the first missing
       slot via get_next_missing_slot().
    2. If a slot is missing, generate a targeted question via
       generate_slot_question() and set next_action="await_slot" - the
       graph loops back to wait for the patient's next message, then
       re-enters this part of the flow on their reply.
    3. If no slot is missing, all required information has been
       collected - set next_action="supervisor" to re-route the now-
       complete request.
 
    Returns
    -------
    A partial state update dict.
    """
    
    session_id = state["session_id"]
    slot_status = state.get("slot_fill_status", {})
    entities = state.get("entities", {})
    
    missing_slot = get_next_missing_slot(slot_status)
    
    if missing_slot is None:
        logger.info(
            f"slot_fill_handler: session={session_id} all slots filled, routing to supervisor"
        )
        return {
            "active_agent": "slot_fill_handler",
            "next_action": "supervisor",
        }
    
    question = generate_slot_question(missing_slot, entities)
    logger.info(
        f"slot_fill_handler: session={session_id} missing_slot={missing_slot}"
    )
    
    return {
        "messages": [AIMessage(content=question)],
        "active_agent": "slot_fill_handler",
        "next_action": "await_slot",
    }
    