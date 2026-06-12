from __future__ import annotations
import json
from typing import Any
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from sqlalchemy import select

from app.agents.information.prompts import build_info_prompt
from app.agents.state import HospitalAgentState
from app.config import get_settings
from app.db.base import get_session_context
from app.db.models.medication import HospitalInfo
from app.db.repositories.doctor_repo import DoctorRepository
from app.llm.factory import LLMTier, get_llm
from app.logger import logging as logger


@tool
async def get_doctor_info(name: str = "", specialization: str = "") -> str:
    """
    Look up doctors by name and/or specialization.

    Use this when the patient asks about a specific doctor (e.g. "Dr.
    Rahman") or a type of specialist (e.g. "do you have a cardiologist?").

    Parameters:
    name: Partial, case-insensitive doctor name. Leave empty if not searching by name.
    specialization: Partial, case-insensitive specialization. Leave empty if not searching by specialization.

    Returns:
    A JSON string containing a list of matching doctors with their
    name, specialization, department, consultation fee, and
    qualification. Returns an empty list if nothing matches.
    """
    async with get_session_context() as session:
        repo = DoctorRepository(session)
        doctors = await repo.search(
            name=name or None,
            specialization=specialization or None,
            load_department=True,
        )

    results = [
        {
            "doctor_id": d.doctor_id,
            "full_name": d.full_name,
            "specialization": d.specialization,
            "department": d.department.name if d.department else None,
            "consultation_fee": float(d.consultation_fee) if d.consultation_fee is not None else None,
            "qualification": d.qualification,
            "experience_years": d.experience_years,
        }
        for d in doctors
    ]

    logger.info(
        f"get_doctor_info(name={name!r}, specialization={specialization!r}) "
        f"-> {len(results)} result(s)"
    )
    return json.dumps(results)


@tool
async def list_services() -> str:
    """
    List all hospital services.

    Use this when the patient asks what services or facilities the
    hospital offers (e.g. "what services do you provide?", "do you have
    a blood bank?").

    Returns
    -------
    A JSON string containing a list of services, each with a topic and
    content description. Returns an empty list if no services are on
    file.
    """
    async with get_session_context() as session:
        result = await session.execute(
            select(HospitalInfo).where(HospitalInfo.category == "service")
        )
        rows = result.scalars().all()

    results = [{"topic": row.topic, "content": row.content} for row in rows]

    logger.info(f"list_services() -> {len(results)} result(s)")
    return json.dumps(results)


@tool
async def get_hospital_info(topic: str) -> str:
    """
    Look up general hospital information by topic.

    Use this for questions about hours, location, parking, visiting
    policy, payment methods, insurance, FAQs, or anything not covered
    by the doctor or department tools.

    Parameters
    ----------
    topic   A short phrase describing what the patient is asking about
            (e.g. "visiting hours", "parking", "insurance plans").
            Matched as a case-insensitive partial match against the
            topic field.

    Returns
    -------
    A JSON string containing a list of matching hospital_info rows
    (category, topic, content). Returns an empty list if nothing
    matches.
    """
    async with get_session_context() as session:
        result = await session.execute(
            select(HospitalInfo).where(HospitalInfo.topic.ilike(f"%{topic}%"))
        )
        rows = result.scalars().all()

    results = [
        {"category": row.category, "topic": row.topic, "content": row.content}
        for row in rows
    ]

    logger.info(f"get_hospital_info(topic={topic!r}) -> {len(results)} result(s)")
    return json.dumps(results)


@tool
async def get_department_info(department_name: str) -> str:
    """
    Look up a hospital department by name.

    Use this when the patient asks where a department is located, its
    extension number, or general department information (e.g. "where
    is cardiology?").

    Parameters
    ----------
    department_name   Partial, case-insensitive department name (e.g.
                       "cardio", "emergency").

    Returns
    -------
    A JSON string containing a list of matching departments with name,
    floor location, phone extension, and description. Returns an empty
    list if nothing matches.
    """
    async with get_session_context() as session:
        repo = DoctorRepository(session)
        departments = await repo.search_departments(department_name)

    results = [
        {
            "department_id": d.department_id,
            "name": d.name,
            "floor_location": d.floor_location,
            "phone_extension": d.phone_extension,
            "description": d.description,
        }
        for d in departments
    ]

    logger.info(f"get_department_info(department_name={department_name!r}) -> {len(results)} result(s)")
    return json.dumps(results)


def _build_info_tools() -> list:
    """
    Build the list of tools bound to the Information Agent's LLM.

    get_doctor_info, list_services, get_hospital_info, and
    get_department_info are always included - they only depend on the
    MySQL database, which is part of the core stack.

    rag_search is included ONLY if ChromaDB is importable, checked via
    a try/import. ChromaDB is a Phase 4 dependency and may not be
    installed yet - the Information Agent must work without it.
    """
    tools: list = [get_doctor_info, list_services, get_hospital_info, get_department_info]

    try:
        import chromadb  # noqa: F401
    except ImportError:
        logger.debug("chromadb not installed - rag_search tool not bound to info_agent")
        return tools

    @tool
    async def rag_search(query: str) -> str:
        """
        Semantic search over hospital documents (policies, FAQs,
        brochures) using the ChromaDB vector store.

        Use this for open-ended questions that the other info tools
        don't directly cover (e.g. "what is your policy on second
        opinions?").

        Parameters
        ----------
        query   The patient's question, used as the semantic search
                query.

        Returns
        -------
        A JSON string containing a list of matching document chunks
        with their source and content. Returns an empty list if the
        vector store is not yet populated or ChromaDB is unreachable.
        """
        try:
            settings = get_settings()
            client = chromadb.PersistentClient(path=settings.rag.CHROMA_PERSIST_DIR)
            collection = client.get_or_create_collection(name=settings.rag.CHROMA_COLLECTION_NAME)
            query_result = collection.query(query_texts=[query], n_results=3)

            documents = query_result.get("documents", [[]])[0]
            metadatas = query_result.get("metadatas", [[]])[0]

            results = [
                {"source": meta.get("source", "unknown"), "content": doc}
                for doc, meta in zip(documents, metadatas)
            ]
            logger.info(f"rag_search(query={query!r}) -> {len(results)} result(s)")
            return json.dumps(results)
        except Exception as exc:
            logger.error(f"rag_search failed for query={query!r}: {exc}")
            return json.dumps([])

    tools.append(rag_search)
    logger.debug("chromadb available - rag_search tool bound to info_agent")
    return tools


info_tools = _build_info_tools()
info_tool_node = ToolNode(info_tools)


async def info_agent_node(state: HospitalAgentState) -> dict[str, Any]:
    """
    The Information Agent graph node.

    Flow
    ----
    1. Build the Information Agent system prompt for this hospital.
    2. Call the CAPABLE-tier LLM with tools bound, passing the system
       prompt plus the full conversation history.
    3. If the LLM's response contains tool calls, append it to
       state["messages"] and set next_action="info_tools" so the
       ToolNode (info_tool_node) executes the requested tools. The
       graph then routes back to this node so it can produce a final
       answer using the tool results.
    4. If the response contains no tool calls, it is the final answer -
       append it to state["messages"] and set next_action="end".

    Returns
    -------
    A partial state update dict.
    """
    settings = get_settings()
    system_prompt = build_info_prompt(settings.HOSPITAL_NAME)

    llm = get_llm(LLMTier.CAPABLE).bind_tools(info_tools)
    llm_messages: list[BaseMessage] = [SystemMessage(content=system_prompt), *state["messages"]]

    try:
        response: AIMessage = await llm.ainvoke(llm_messages)
    except Exception as exc:
        logger.error(f"info_agent LLM call failed for session={state['session_id']}: {exc}")
        return {
            "messages": [
                AIMessage(
                    content=(
                        "I'm having trouble looking that up right now. "
                        "Please contact reception at 16700 for assistance."
                    )
                )
            ],
            "active_agent": "info_agent",
            "next_action": "end",
            "error": "Information agent LLM call failed.",
        }

    has_tool_calls = bool(getattr(response, "tool_calls", None))
    next_action = "info_tools" if has_tool_calls else "end"

    logger.info(
        f"info_agent responded for session={state['session_id']} "
        f"(tool_calls={len(response.tool_calls) if has_tool_calls else 0})"
    )

    return {
        "messages": [response],
        "active_agent": "info_agent",
        "next_action": next_action,
    }