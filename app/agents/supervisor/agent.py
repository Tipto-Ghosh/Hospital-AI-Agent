from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from app.logger import logging as logger
from app.agents.state import (
    EMERGENCY_KEYWORDS,
    INTENT_LABELS,
    HospitalAgentState,
    contains_emergency_keyword,
)
from app.agents.supervisor.prompts import build_supervisor_prompt
from app.config import get_settings
from app.llm.factory import LLMTier, get_llm

INTENT_TO_NEXT_ACTION: dict[str, str] = {
    "general_info": "info_agent",
    "doctor_info": "info_agent",
    "book_appointment": "booking_agent",
    "cancel_appointment": "cancel_agent",
    "reschedule_appointment": "reschedule_agent",
    "patient_records": "records_agent",  
    "billing": "billing_agent",
    "medication_info": "medication_agent",
    "feedback": "feedback_agent",
    "emergency": "emergency_interrupt",
    "out_of_scope": "fallback",
}


def _latest_human_text(messages: list[BaseMessage]) -> str:
    """
    Return the content of the most recent HumanMessage in `messages`,
    or "" if there isn't one.

    Used both for the pre-LLM emergency keyword scan and for logging.
    """
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """
    Extract the first JSON object from `text` and parse it.

    The Supervisor prompt asks for a bare JSON object, but LLMs
    occasionally wrap responses in markdown code fences or add stray
    text. This helper handles:
      - A clean JSON object (fast path: json.loads directly).
      - ```json ... ``` or ``` ... ``` fenced blocks.
      - A JSON object embedded among other text, by taking the
        substring from the first '{' to the matching last '}'.

    Returns
    -------
    The parsed dict, or None if no valid JSON object could be found.
    Never raises — callers treat None as a parse failure and fall back
    to intent="unknown".
    """
    text = text.strip()

    # Fast path: the whole string is valid JSON.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    return None


async def supervisor_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Supervisor graph node.

    Flow
    ----
    1. Pre-LLM emergency check: scan the latest human message against
       EMERGENCY_KEYWORDS. If matched, set is_emergency=True,
       intent="emergency", next_action="emergency_interrupt", and
       return immediately WITHOUT calling the LLM. This is the fast
       path described in Section 7.3 — every millisecond matters for
       a genuine emergency.

    2. Otherwise, call the FAST-tier LLM with the Supervisor system
       prompt plus the conversation history. Parse the JSON response
       for "intent", "entities", and "reasoning".

    3. Validate "intent" against INTENT_LABELS. If the LLM returned
       "emergency" (its own safety-net classification, separate from
       step 1's keyword scan), also set is_emergency=True.

    4. Resolve next_action from INTENT_TO_NEXT_ACTION, with a special
       case for "patient_records": route to "auth_agent" instead of
       "records_agent" if the session is not yet authenticated.

    5. On any JSON parse failure or invalid intent, set
       intent="unknown", next_action="fallback", and record a
       human-readable message in state["error"] (the fallback node
       uses this to apologise to the patient without exposing internals).

    Returns
    -------
    A partial state update dict. LangGraph merges this into the
    existing HospitalAgentState. This node never modifies
    state["messages"] — classification is silent from the patient's
    perspective.
    """
    messages = state["messages"]
    latest_text = _latest_human_text(messages)

    # Step 1: fast pre-LLM emergency keyword scan
    if contains_emergency_keyword(latest_text):
        logger.warning(
            f'Emergency keyword matched | session={state["session_id"][:8]}... text_preview={latest_text[:50]}'
        )
        return {
            "is_emergency": True,
            "intent": "emergency",
            "active_agent": "emergency_agent",
            "next_action": "emergency_interrupt",
        }

    # Step 2: LLM-based classification 
    settings = get_settings()
    system_prompt = build_supervisor_prompt(settings.HOSPITAL_NAME)

    llm = get_llm(LLMTier.FAST)
    llm_messages: list[BaseMessage] = [SystemMessage(content=system_prompt), *messages]

    try:
        response = await llm.ainvoke(llm_messages)
        raw_content = response.content if isinstance(response.content, str) else str(response.content)
    except Exception as exc:
        logger.error(
            "Supervisor LLM call failed | session=%s... error=%s",
            state["session_id"][:8], exc,
        )
        return {
            "intent": "unknown",
            "active_agent": "fallback",
            "next_action": "fallback",
            "error": (
                "I'm having trouble understanding right now. "
                "Could you please rephrase that?"
            ),
        }

    # Step 3: parse and validate the JSON response 
    parsed = _extract_json_object(raw_content)

    if parsed is None:
        logger.warning(
            "Supervisor JSON parse failed | session=%s... raw=%r",
            state["session_id"][:8], raw_content[:200],
        )
        return {
            "intent": "unknown",
            "active_agent": "fallback",
            "next_action": "fallback",
            "error": (
                "I'm having trouble understanding right now. "
                "Could you please rephrase that?"
            ),
        }

    intent = parsed.get("intent")
    entities: dict[str, Any] = parsed.get("entities") or {}
    reasoning = parsed.get("reasoning", "")

    if intent not in INTENT_LABELS:
        logger.warning(
            "Supervisor returned invalid intent=%r | session=%s... raw=%r",
            intent, state["session_id"][:8], raw_content[:200],
        )
        return {
            "intent": "unknown",
            "active_agent": "fallback",
            "next_action": "fallback",
            "error": (
                "I'm having trouble understanding right now. "
                "Could you please rephrase that?"
            ),
        }

    logger.info(
        "Supervisor classified | session=%s... intent=%s reasoning=%r",
        state["session_id"][:8], intent, reasoning,
    )

    # Step 4: resolve next_action 
    is_emergency = intent == "emergency"

    if intent == "patient_records" and not state.get("is_authenticated", False):
        next_action = "auth_agent"
    else:
        next_action = INTENT_TO_NEXT_ACTION.get(intent, "fallback")

    # Step 5: merge extracted entities into existing state
    merged_entities = {**state.get("entities", {}), **entities}

    return {
        "intent": intent,
        "entities": merged_entities,
        "is_emergency": is_emergency,
        "active_agent": next_action,
        "next_action": next_action,
        "error": None,
    }