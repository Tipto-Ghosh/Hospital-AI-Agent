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
