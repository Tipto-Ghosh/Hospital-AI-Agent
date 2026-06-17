"""
The Medication Information Agent node and its tools.

Hard Guardrails
1. _ensure_disclaimer(): every response is scanned for the exact
   MEDICATION_DISCLAIMER text. If missing, it is appended
   automatically - the prompt asks the LLM to include it, but this
   guarantees it regardless of LLM behaviour.
 
2. _contains_self_medication_red_flag(): the LATEST PATIENT MESSAGE is
   scanned (before any LLM call) for SELF_MEDICATION_RED_FLAGS. If
   matched, this node does NOT call the LLM at all - it returns
   immediately with next_action="info_agent", redirecting the
   conversation per Section 3.9 of the plan ("Flag any query that
   sounds like self-medication for dangerous conditions -> route to
   Info Agent").
"""

from __future__ import annotations
 
import json
from typing import Any
 
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from sqlalchemy import select
 
from app.agents.medication.prompts import (
    DOSAGE_LANGUAGE_PATTERNS,
    MEDICATION_DISCLAIMER,
    SELF_MEDICATION_RED_FLAGS,
    build_medication_prompt,
)
from app.agents.state import HospitalAgentState
from app.config import get_settings
from app.db.base import get_session_context
from app.db.models.medication import HospitalInfo
from app.db.repositories.medication_repo import MedicationRepository
from app.llm.factory import LLMTier, get_llm
from app.logger import logging
 
logger = logging.getLogger(__name__)

@tool
async def query_medication_info(drug_name: str) -> str:
    """
    Look up general information about a medication by generic or brand
    name.
 
    Parameters
    ----------
    drug_name   Generic or brand name, e.g. "metformin" or "Glucophage".
                Fuzzy, case-insensitive matching.
 
    Returns
    -------
    A JSON string: {"found": true, "generic_name": str,
    "brand_names": str, "drug_class": str, "common_uses": str,
    "side_effects": str, "general_dosage": str,
    "requires_prescription": bool} for the best match, or
    {"found": false, "suggestions": [str, ...]} if multiple partial
    matches exist but none is exact, or {"found": false,
    "suggestions": []} if nothing matches at all.
    """
    
    async with get_session_context() as session:
        repo = MedicationRepository(session)
        
        exact = await repo.get_by_generic_name(drug_name)
        if exact is not None:
            logger.info(
                f"query_medication_info(drug_name={drug_name}) -> exact match: {exact.generic_name}"
            )
            
            return json.dumps({
                "found": True,
                "generic_name": exact.generic_name,
                "brand_names": exact.brand_names,
                "drug_class": exact.drug_class,
                "common_uses": exact.common_uses,
                "side_effects": exact.side_effects,
                "general_dosage:": exact.general_dosage,
                "reqires_prescription": exact.requires_prescription,
            })
        
        matchs = await repo.search(drug_name)
        if len(matchs) == 1:
            m = matchs[0]
            logger.info(
                f"query_medication_info(drug_name={drug_name}) -> single match: {m.generic_name}"
            )
            return json.dumps({
                "found": True,
                "generic_name": m.generic_name,
                "brand_names": m.brand_names,
                "drug_class": m.drug_class,
                "common_uses": m.common_uses,
                "side_effects": m.side_effects,
                "general_dosage:": m.general_dosage,
                "reqires_prescription": m.requires_prescription,
            })
    
    suggestions = [m.generic_name for m in matchs]
    logger.info(
        f"query_medication_info(drug_name={drug_name}) -> no exact match, suggestions: {suggestions}"
    )
    return json.dumps({
        "found": False,
        "suggestions": suggestions,
    })
    
@tool
async def check_drug_interaction(drug_a: str, drug_b: str) -> str:
    """
    Check for known interactions between two medications.
 
    Parameters
    ----------
    drug_a   Generic name of the first drug.
    drug_b   Generic name of the second drug.
 
    Returns
    -------
    A JSON string: {"interactions": [{"drug_a": str, "drug_b": str,
    "severity": str, "description": str}, ...]}. Empty list means no
    known interaction is on file - this does NOT mean the combination
    is safe, only that nothing is recorded.
    """
    async with get_session_context() as session:
        repo = MedicationRepository(session)
        results = await repo.get_interactions(drug_a, drug_b)
 
    results_out = [
        {
            "drug_a": r.drug_a,
            "drug_b": r.drug_b,
            "severity": r.severity,
            "description": r.description,
        }
        for r in results
    ]
 
    logger.info(f"check_drug_interaction(drug_a={drug_a!r}, drug_b={drug_b!r}) -> {len(results_out)} interaction(s)")
    return json.dumps({"interactions": results_out})


@tool
async def get_medication_faq(query: str) -> str:
    """
    Semantic-ish search over medication FAQ content stored in
    hospital_info (category='faq').
 
    Parameters
    ----------
    query   The patient's question, matched as a case-insensitive
            partial match against the FAQ topic and content.
 
    Returns
    -------
    A JSON string: {"results": [{"topic": str, "content": str}, ...]}.
    Returns an empty list if nothing matches.
    """
    async with get_session_context() as session:
        result = await session.execute(
            select(HospitalInfo).where(
                HospitalInfo.category == "faq",
                (HospitalInfo.topic.ilike(f"%{query}%") | HospitalInfo.content.ilike(f"%{query}%")),
            )
        )
        rows = result.scalars().all()
 
    results_out = [{"topic": r.topic, "content": r.content} for r in rows]
    logger.info(f"get_medication_faq(query={query!r}) -> {len(results_out)} result(s)")
    return json.dumps({"results": results_out})
 
 
medication_tools = [query_medication_info, check_drug_interaction, get_medication_faq]
medication_tool_node = ToolNode(medication_tools)

def _latest_human_text(messages: list[BaseMessage]) -> str:
    """Return the content of the most recent HumanMessage, or ''."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""

def _contains_self_medication_red_flag(text: str) -> bool:
    """
    Case-insensitive substring check of `text` against
    SELF_MEDICATION_RED_FLAGS.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(flag in lowered for flag in SELF_MEDICATION_RED_FLAGS)

def _ensure_disclaimer(response_text: str) -> str:
    """
    Guarantee MEDICATION_DISCLAIMER appears in the response.
 
    The prompt instructs the LLM to include the disclaimer verbatim,
    but this is a hard guardrail independent of LLM compliance: if the
    disclaimer text is not found (case-insensitive), it is appended on
    its own line.
 
    Additionally, if any DOSAGE_LANGUAGE_PATTERNS phrase is present
    (the LLM addressed the patient directly about their own dosage,
    which the prompt forbids), the disclaimer is appended even if some
    other disclaimer-like text was already present - dosage-specific
    language always gets the full, exact disclaimer appended.
 
    Parameters
    ----------
    response_text   The raw LLM response text.
 
    Returns
    -------
    response_text, with MEDICATION_DISCLAIMER guaranteed present.
    """
    lowered = response_text.lower()
    disclaimer_present = MEDICATION_DISCLAIMER.lower() in lowered
    has_dosage_language = any(p in lowered for p in DOSAGE_LANGUAGE_PATTERNS)
 
    if disclaimer_present and not has_dosage_language:
        return response_text
 
    if has_dosage_language:
        logger.warning("medication_agent: dosage-specific language detected in response, appending disclaimer")
 
    separator = "\n\n" if response_text.strip() else ""
    return f"{response_text}{separator}{MEDICATION_DISCLAIMER}"


async def medication_agent_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Medication Information Agent graph node.
 
    Flow
    ----
    1. Scan the latest patient message for SELF_MEDICATION_RED_FLAGS
       BEFORE calling the LLM. If matched, redirect to info_agent
       immediately (next_action="info_agent") - no medication
       information is provided.
    2. Otherwise, call the CAPABLE-tier LLM with the three medication
       tools bound, passing the medication system prompt plus
       conversation history.
    3. If the response contains tool calls, append it and set
       next_action="medication_tools" so medication_tool_node executes
       them - the graph routes back to this node for a final answer.
    4. If the response is final (no tool calls), run it through
       _ensure_disclaimer() before appending - guaranteeing the
       required disclaimer is present regardless of LLM output.
 
    Returns
    -------
    A partial state update dict.
    """
    session_id = state["session_id"]
    latest_text = _latest_human_text(state["messages"])
 
    if _contains_self_medication_red_flag(latest_text):
        logger.warning(
            f"medication_agent: self-medication red flag detected for session={session_id}, "
            f"redirecting to info_agent"
        )
        return {
            "messages": [AIMessage(content="That sounds like something best discussed with a doctor rather than answered here. Let me connect you with general hospital information - if this feels urgent, please contact the Emergency Department or call 109.")],
            "active_agent": "info_agent",
            "next_action": "info_agent",
        }
 
    settings = get_settings()
    system_prompt = build_medication_prompt(settings.HOSPITAL_NAME)
 
    llm = get_llm(LLMTier.CAPABLE).bind_tools(medication_tools)
    llm_messages: list[BaseMessage] = [SystemMessage(content=system_prompt), *state["messages"]]
 
    try:
        response: AIMessage = await llm.ainvoke(llm_messages)
    except Exception as exc:
        logger.error(f"medication_agent LLM call failed for session={session_id}: {exc}")
        fallback_text = _ensure_disclaimer(
            "I'm having trouble looking that up right now. Please contact a pharmacist or your doctor for medication questions."
        )
        return {
            "messages": [AIMessage(content=fallback_text)],
            "active_agent": "medication_agent",
            "next_action": "end",
            "error": "Medication agent LLM call failed.",
        }
 
    has_tool_calls = bool(getattr(response, "tool_calls", None))
 
    if has_tool_calls:
        logger.info(f"medication_agent responded for session={session_id} (tool_calls={len(response.tool_calls)})")
        return {
            "messages": [response],
            "active_agent": "medication_agent",
            "next_action": "medication_tools",
        }
 
    response_text = response.content if isinstance(response.content, str) else str(response.content)
    final_text = _ensure_disclaimer(response_text)
 
    logger.info(f"medication_agent final response for session={session_id}")
 
    return {
        "messages": [AIMessage(content=final_text)],
        "active_agent": "medication_agent",
        "next_action": "end",
    }