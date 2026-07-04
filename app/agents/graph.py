"""
input_handler_node and load_session_memory_node
---------------------------------------------------
input_handler and load_session_memory as the first two nodes in the graph, 
ahead of the supervisor. 

  - input_handler_node: sanitizes the latest human message via
    app.utils.security.sanitize_input, and runs check_for_injection as
    a non-blocking, logged security signal. It does NOT mutate
    state["messages"] in place instead it replaces the most recent HumanMessage's
    content with the sanitized version.

  - load_session_memory_node: currently a no-op pass-through.

Checkpointer
-------------
checkpointer = None for now.

Routing logic
------------------------------
The supervisor node already resolves state["next_action"] to
the DESTINATION NODE NAME, not just the raw intent string including
the is_authenticated-based branch for patient_records ->
auth_agent vs records_agent. So the conditional edge leaving
"supervisor" is a simple, direct dispatch on state["next_action"].

Tool-call loop-backs: info_agent, records_agent, billing_agent,
medication_agent, and feedback_agent each optionally bind tools via
llm.bind_tools(...) and set next_action to a *_tools sentinel
("info_tools", "records_tools", "billing_tools", "medication_tools",
"feedback_tools") when the LLM requests a tool call. Each such ToolNode
routes back to its originating agent node so the agent can produce a
final answer using the tool results.

Mutation flow: booking_agent, cancel_agent, and reschedule_agent never
execute a write directly - they set state["pending_confirmation"] and
end their turn (next_action="end"). On the PATIENT'S NEXT MESSAGE, this
graph is expected to be invoked with conditional_entry routing already
having sent state to confirmation_handler instead of supervisor
whenever state["pending_confirmation"] is not None - that branching
decision lives in the API layer (app/api/routes/chat.py), which decides
the entry node per turn. Within this graph, confirmation_handler routes
to either action_executor (on "confirmed"), back to itself for a
re-prompt (on "end"), or to save_memory (on "aborted").
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from app.agents.billing.agent import billing_agent_node, billing_tool_node
from app.agents.booking.agent import booking_agent_node
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
from app.config import get_settings
from app.logger import logging
from app.utils.security import check_for_injection, sanitize_input

logger = logging.getLogger(__name__)

_langfuse_handler_cache: Any = None


def get_langfuse_handler() -> Any:
    global _langfuse_handler_cache

    if _langfuse_handler_cache is not None:
        return _langfuse_handler_cache

    settings = get_settings()

    if not settings.obs.langfuse_enabled:
        logger.debug("get_langfuse_handler: Langfuse not configured, tracing disabled")
        return None

    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.warning(
            "get_langfuse_handler: langfuse package not installed - tracing disabled. "
            "Install it with: pip install langfuse"
        )
        return None

    try:
        kwargs: dict[str, Any] = {
            "secret_key": settings.obs.LANGFUSE_SECRET_KEY,
            "public_key": settings.obs.LANGFUSE_PUBLIC_KEY,
        }
        if settings.obs.LANGFUSE_BASE_URL:
            kwargs["host"] = str(settings.obs.LANGFUSE_BASE_URL)

        handler = CallbackHandler(**kwargs)
        logger.info("get_langfuse_handler: Langfuse tracing enabled")
    except Exception as exc:
        logger.error(f"get_langfuse_handler: failed to construct CallbackHandler: {exc}")
        return None

    _langfuse_handler_cache = handler
    return handler


def reset_langfuse_handler_cache() -> None:
    """
    Clear the cached Langfuse handler.
    """
    global _langfuse_handler_cache
    _langfuse_handler_cache = None


def _latest_human_message_index(messages: list) -> int | None:
    """Return the index of the most recent HumanMessage in messages, or None."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return i
    return None


async def input_handler_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    Sanitize the latest patient message before it reaches any other node.

    Also runs check_for_injection as a non-blocking signal: a match is
    logged as a warning but does NOT alter routing or block the
    message.
    """
    messages = state["messages"]
    index = _latest_human_message_index(messages)

    if index is None:
        return {}

    original_message = messages[index]
    original_text = original_message.content if isinstance(original_message.content, str) else str(original_message.content)

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
    Load Redis session memory and patient long-term context into the graph state.
    """
    return {}


async def save_memory_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    Persist this turn to Redis and, periodically MySQL conversation_memory.
    """
    return {}


def _route_from_supervisor(state: HospitalAgentState) -> str:
    """
    Conditional edge function for the supervisor node.

    The supervisor already resolves state["next_action"] to
    the destination node name - including the is_authenticated-based
    patient_records -> auth_agent branch - so this is a direct dispatch.
    """
    return state.get("next_action", "fallback")


def _route_entry(state: HospitalAgentState) -> str:
    """Route to confirmation_handler if pending_confirmation exists else
    normal flow.
    """
    return "confirmation_handler" if state.get("pending_confirmation") is not None else "normal"

def _route_from_tool_capable_agent(state: HospitalAgentState) -> str:
    """
    Conditional edge function shared by info_agent, records_agent,
    billing_agent, medication_agent, and feedback_agent.

    Each of these agents sets next_action to its own *_tools sentinel
    when the LLM requested a tool call, "info_agent" for the
    medication-agent self-medication redirect, "auth_required" for the
    records-agent unauthenticated case, or "end" for a final answer.
    All five sentinels plus "end"/"auth_required"/"info_agent" are
    valid here; build_graph()'s edge mapping for each specific node
    only lists the subset that node can actually produce.
    """
    return state.get("next_action", "end")


def _route_from_confirmation_handler(state: HospitalAgentState) -> str:
    """
    Conditional edge function for confirmation_handler.

    "confirmed" -> action_executor (perform the write)
    "aborted" -> save_memory (patient declined, message already set)
    "end" -> confirmation_handler (ambiguous reply, re-prompted -
        loops back to itself since the next invocation will
        re-evaluate the patient's NEXT message against the
        same pending_confirmation)
    "fallback" -> fallback (defensive case: no pending_confirmation found)
    """
    return state.get("next_action", "fallback")


def _route_from_mutation_agent(state: HospitalAgentState) -> str:
    """
    Conditional edge function shared by booking_agent, cancel_agent,
    and reschedule_agent.
    """
    return state.get("next_action", "end")


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

    # node list
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
    graph.add_edge("input_handler", "load_session_memory")
    graph.add_edge("load_session_memory", "supervisor")
    
    graph.add_conditional_edges(
        START,
        _route_entry,
        {
            "confirmation_handler": "confirmation_handler",
            "normal": "input_handler",
        },
    )

    # Supervisor dispatches directly to the destination node named by
    # state["next_action"] (already resolved by supervisor_node itself,
    # including the patient_records auth branch and the emergency
    # fast-path / LLM-classified emergency routes).
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

    # info_agent <-> info_tools (ReAct-style tool-call loop)
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
    graph.add_conditional_edges(
        "slot_fill_handler",
        lambda state: state.get("next_action", "await_slot"),
        {"supervisor": "supervisor", "await_slot": "save_memory"},
    )

    # confirmation_handler: confirmed -> execute the write; aborted ->
    # done (message already set); end -> ambiguous reply, re-prompted
    # (stays here for the next invocation); fallback -> defensive case.
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
    logger.info("Hospital-AI-Agent StateGraph compiled successfully (checkpointer=%s)" % ("None" if checkpointer is None else type(checkpointer).__name__))
    return compiled


async def ainvoke_with_tracing(
    compiled_graph: Any,
    state: HospitalAgentState,
    extra_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Invoke a compiled graph with Langfuse tracing attached, if configured.

    Parameters
    ----------
    compiled_graph: The graph returned by build_graph().
    state: The HospitalAgentState to invoke the graph with.
    extra_config: Optional additional LangGraph run config (e.g.
                      {"configurable": {"thread_id": session_id}} once a
                      checkpointer is wired in). Merged with the
                      callbacks list this function constructs — any
                      "callbacks" key in extra_config is combined with
                      (not overwritten by) the Langfuse handler.

    Returns
    -------
    The resulting state dict from compiled_graph.ainvoke().
    """
    handler = get_langfuse_handler()

    config: dict[str, Any] = dict(extra_config or {})
    existing_callbacks = config.get("callbacks", [])
    config["callbacks"] = existing_callbacks + ([handler] if handler else [])

    return await compiled_graph.ainvoke(state, config=config)