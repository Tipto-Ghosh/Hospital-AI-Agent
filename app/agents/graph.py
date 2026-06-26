"""
The central StateGraph wires every node built for our system into a single
complied graph.

input_handler and load_session_memory as the first nodes in the graph, ahead of
the supervisor node.

# input_handler_node: 
    sanitizes the latest human message via
    app.utils.security.sanitize_input, and runs check_for_injection as
    a non-blocking, logged security signal. It does not mutate
    state["messages"] in place instead it replaces the most recent HumanMessage's
    content with the sanitized version.

# load_session_memory_node:
    loads the session's memory from the database, and injects it into
    state["messages"] as a SystemMessage. This is done after input_handler_node
    so that any prompt-injection attempts in the human message are not
    persisted to memory.
"""

from __future__ import annotations
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langgraph.graph import START, END, StateGraph

from app.agents.billing.agent import billing_agent_node, billing_tool_node
from app.agents.booking.agent import booking_agent_node, booking_tools
from app.agents.cancellation.agent import cancel_agent_node
from app.agents.emergency.agent import emergency_agent_node
from app.agents.feedback.agent import feedback_agent_node, feedback_tool_node
from app.agents.information.agent import info_agent_node, info_tool_node
from app.agents.medication.agent import medication_agent_node, medication_tool_node
from app.agents.records.agent import records_agent_node, records_tool_node
from app.agents.rescheduling.agent import reschedule_agent_node
from app.agents.shared.auth_agent import auth_agent_node
from app.agents.shared.confirmation_handler import action_executor_node, confirmation_handler_node
from app.agents.shared.fallback import fallback_node, slot_fill_handler_node
from app.agents.state import HospitalAgentState
from app.agents.supervisor.agent import supervisor_node
from app.logger import logging
from app.utils.security import check_for_injection, sanitize_input


logger = logging.getLogger(__name__)

def _latest_human_message_index(messages: list) -> int | None:
    """Return the index of the most recent HumanMessage in messages, or None."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return i
    return None

async def input_handler_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    Sanitize the latest patient message before it reaches any other node.

    Replaces the most recent HumanMessage's content with the sanitized
    version (HTML tags, control characters, zero-width characters
    stripped; whitespace collapsed; length-capped) via
    app.utils.security.sanitize_input.

    Also runs check_for_injection as a non-blocking signal: a match is
    logged as a warning but does NOT alter routing or block the
    message.

    Returns
    -------
    A partial state update dict containing the sanitized HumanMessage
    (same message id as the original) or an empty dict if there is no human message 
    yet, or it needed no changes.
    """
    messages = state["messages"]
    index = _latest_human_message_index(messages)

    if index is None:
        return {}

    original_message = messages[index]
    original_text = (
        original_message.content
        if isinstance(original_message.content, str)
        else str(original_message.content)
    )

    sanitized_text = sanitize_input(original_text)

    if check_for_injection(sanitized_text):
        logger.warning(
            f"input_handler: possible prompt injection detected for session={state['session_id']}"
        )

    if sanitized_text == original_text:
        return {}

    sanitized_message = HumanMessage(content=sanitized_text, id=original_message.id)
    return {"messages": [sanitized_message]}


async def load_session_memory_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    Load Redis session memory and patient long-term
    context into the graph state.

    NOT YET IMPLEMENTED - Phase 3 work. This is currently a no-op
    pass-through: with checkpointer=None, the caller is responsible for
    supplying the full conversation history as part of the initial
    state passed to invoke()/ainvoke(), so there is nothing to load
    from Redis yet.

    Returns
    -------
    An empty partial state update dict.
    """
    return {}

async def save_memory_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    Persist this turn to Tier 2 (Redis) and, periodically, Tier 3
    (MySQL conversation_memory).

    NOT YET IMPLEMENTED - Phase 3 work. This is currently a no-op
    terminal node - every path through the graph converges here before
    END, so wiring in real persistence later requires no changes to any
    other node or edge.

    Returns
    -------
    An empty partial state update dict.
    """
    return {}

def _route_from_supervisor(state: HospitalAgentState) -> str:
    """
    Conditional edge function for the supervisor node.

    The supervisor (Step 28) already resolves state["next_action"] to
    the destination node name - including the is_authenticated-based
    patient_records -> auth_agent branch and the is_emergency fast-path
    -> emergency_interrupt - so this is a direct dispatch.
    """
    return state.get("next_action", "fallback")

def _route_from_tool_capable_agent(state: HospitalAgentState) -> str:
    """
    Conditional edge function shared by info_agent, records_agent,
    billing_agent, medication_agent, and feedback_agent.

    Each of these agents sets next_action to its own *_tools sentinel
    when the LLM requested a tool call, "info_agent" for the
    medication-agent self-medication redirect, "auth_required" for the
    records-agent unauthenticated case, or "end" for a final answer.
    build_graph()'s edge mapping for each specific node only lists the
    subset of these that node can actually produce.
    """
    return state.get("next_action", "end")

def _route_from_mutation_agent(state: HospitalAgentState) -> str:
    """
    Conditional edge function shared by booking_agent, cancel_agent,
    and reschedule_agent.

    These agents only ever set next_action to "auth_agent" (redirect to
    authentication, cancel/reschedule only) or "end" (a slot-filling
    question, a clarification request, or pending_confirmation has been
    set and the summary message asks the patient to confirm). None of
    the three binds LLM tools directly, and none of them currently
    delegates to the shared slot_fill_handler node as a separate graph
    hop - booking_agent_node (Step 31) performs its own inline
    slot-filling and asks the next question directly when a slot is
    missing, rather than routing through slot_fill_handler. That shared
    node remains wired into the graph below (reachable in principle)
    but nothing currently routes to it - a natural target for a future
    refactor of booking_agent_node.
    """
    return state.get("next_action", "end")


def _route_from_confirmation_handler(state: HospitalAgentState) -> str:
    """
    Conditional edge function for confirmation_handler.

    "confirmed"  -> action_executor (perform the write)
    "aborted"    -> save_memory (patient declined, message already set)
    "end"        -> save_memory (ambiguous reply, already re-prompted -
                    the next invocation will re-evaluate the patient's
                    NEXT message against the same pending_confirmation)
    "fallback"   -> fallback (defensive case: no pending_confirmation found)
    """
    return state.get("next_action", "fallback")


def build_graph(checkpointer: Any = None) -> Any:
    """
    Build and compile the Hospital-AI-Agent StateGraph.

    Parameters
    ----------
    checkpointer: LangGraph checkpointer for persistence across turns.
    
    Returns
    -------
    A compiled LangGraph graph (CompiledStateGraph), ready for
    .invoke() / .ainvoke() / .astream().
    """
    graph = StateGraph(HospitalAgentState)
    
    # Add all nodes to the graph
    graph.add_node("input_handler", input_handler_node)
    graph.add_node("load_session_memory", load_session_memory_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("emergency_interrupt", emergency_agent_node)
    graph.add_node("info_agent", info_agent_node)
    graph.add_node("booking_agent", booking_agent_node)
    graph.add_node("cancel_agent", cancel_agent_node)
    graph.add_node("reschedule_agent", reschedule_agent_node)
    graph.add_node("records_agent", records_agent_node)
    graph.add_node("billing_agent", billing_agent_node)
    graph.add_node("medication_agent", medication_agent_node)
    graph.add_node("feedback_agent", feedback_agent_node)
    graph.add_node("auth_agent", auth_agent_node)
    graph.add_node("slot_fill_handler", slot_fill_handler_node)
    graph.add_node("confirmation_handler", confirmation_handler_node)
    graph.add_node("action_executor", action_executor_node)
    graph.add_node("save_memory", save_memory_node)
    graph.add_node("fallback", fallback_node)

    # ToolNodes for the five agents that bind LLM tools.
    graph.add_node("info_tools", info_tool_node)
    graph.add_node("records_tools", records_tool_node)
    graph.add_node("billing_tools", billing_tool_node)
    graph.add_node("medication_tools", medication_tool_node)
    graph.add_node("feedback_tools", feedback_tool_node)

    # Entry: START -> input_handler -> load_session_memory -> supervisor
    graph.add_edge(START, "input_handler")
    graph.add_edge("input_handler", "load_session_memory")
    graph.add_edge("load_session_memory", "supervisor")

    """ 
    Supervisor dispatches directly to the destination node named by
    state["next_action"].
    """
    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "emergency_interrupt": "emergency_interrupt",
            "info_agent": "info_agent",
            "booking_agent": "booking_agent",
            "cancel_agent": "cancel_agent",
            "reschedule_agent": "reschedule_agent",
            "records_agent": "records_agent",
            "auth_agent": "auth_agent",
            "billing_agent": "billing_agent",
            "medication_agent": "medication_agent",
            "feedback_agent": "feedback_agent",
            "fallback": "fallback",
        },
    )

    # info_agent <-> info_tools 
    graph.add_conditional_edges(
        "info_agent",
        _route_from_tool_capable_agent,
        {"info_tools": "info_tools", "end": "save_memory"},
    )
    graph.add_edge("info_tools", "info_agent")

    # records_agent <-> records_tools, plus the auth_required exit
    graph.add_conditional_edges(
        "records_agent",
        _route_from_tool_capable_agent,
        {
            "records_tools": "records_tools",
            "auth_required": "auth_agent",
            "end": "save_memory",
        },
    )
    graph.add_edge("records_tools", "records_agent")

    # billing_agent <-> billing_tools
    graph.add_conditional_edges(
        "billing_agent",
        _route_from_tool_capable_agent,
        {"billing_tools": "billing_tools", "end": "save_memory"},
    )
    graph.add_edge("billing_tools", "billing_agent")

    # medication_agent <-> medication_tools, plus the self-medication
    # redirect to info_agent
    graph.add_conditional_edges(
        "medication_agent",
        _route_from_tool_capable_agent,
        {
            "medication_tools": "medication_tools",
            "info_agent": "info_agent",
            "end": "save_memory",
        },
    )
    graph.add_edge("medication_tools", "medication_agent")

    # feedback_agent <-> feedback_tools
    graph.add_conditional_edges(
        "feedback_agent",
        _route_from_tool_capable_agent,
        {"feedback_tools": "feedback_tools", "end": "save_memory"},
    )
    graph.add_edge("feedback_tools", "feedback_agent")

    # Mutation agents: booking/cancel/reschedule never call tools
    # directly - they either ask a question, redirect to auth, or set
    # pending_confirmation and ask for yes/no. Either way, the turn ends
    # here (this graph's job is done; the API layer routes the
    # patient's NEXT message to confirmation_handler instead of
    # supervisor when pending_confirmation is set).
    graph.add_conditional_edges(
        "booking_agent",
        _route_from_mutation_agent,
        {"end": "save_memory"},
    )
    graph.add_conditional_edges(
        "cancel_agent",
        _route_from_mutation_agent,
        {"auth_agent": "auth_agent", "end": "save_memory"},
    )
    graph.add_conditional_edges(
        "reschedule_agent",
        _route_from_mutation_agent,
        {"auth_agent": "auth_agent", "end": "save_memory"},
    )

    # auth_agent: either asks the next slot question (end), gives up
    # after max retries (end), or succeeds and routes back to
    # supervisor to re-route the original request now that the session
    # is authenticated.
    graph.add_conditional_edges(
        "auth_agent",
        lambda state: state.get("next_action", "end"),
        {"supervisor": "supervisor", "end": "save_memory"},
    )

    # slot_fill_handler: either asks a question (await_slot) or all
    # slots are filled and it loops back to supervisor for re-routing.
    # (Wired in and reachable; see _route_from_mutation_agent's
    # docstring above - no current node routes here yet.)
    graph.add_conditional_edges(
        "slot_fill_handler",
        lambda state: state.get("next_action", "await_slot"),
        {"supervisor": "supervisor", "await_slot": "save_memory"},
    )

    # confirmation_handler: confirmed -> execute the write; aborted ->
    # done (message already set); end -> ambiguous reply, already
    # re-prompted; fallback -> defensive case.
    graph.add_conditional_edges(
        "confirmation_handler",
        _route_from_confirmation_handler,
        {
            "confirmed": "action_executor",
            "aborted": "save_memory",
            "end": "save_memory",
            "fallback": "fallback",
        },
    )

    # All remaining terminal nodes -> save_memory -> END
    graph.add_edge("emergency_interrupt", "save_memory")
    graph.add_edge("action_executor", "save_memory")
    graph.add_edge("fallback", "save_memory")
    graph.add_edge("save_memory", END)

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info(
        f"Hospital-AI-Agent StateGraph compiled successfully "
        f"(checkpointer={'None' if checkpointer is None else type(checkpointer).__name__})"
    )
    return compiled