from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Optional

from app.db.base import get_session_context
from app.db.repositories.audit_repo import AuditRepository
from app.logger import logging

logger = logging.getLogger(__name__)


def _extract_call_arg(
    func: Callable,
    args: tuple,
    kwargs: dict,
    param_name: str,
    explicit_value: Optional[Any] = None,
) -> Optional[Any]:
    """
    Resolve a parameter's value from a function call's args/kwargs by
    name, using inspect.signature to map positional args correctly.

    Parameters
    ----------
    func: The wrapped function (used to introspect its signature).
    args: Positional arguments the function was called with.
    kwargs: Keyword arguments the function was called with.
    param_name: The parameter name to look up (e.g. "patient_id").
    explicit_value: If provided (not None), this value is returned
                    directly without inspecting the call - lets the decorator factory accept a static override.

    Returns
    -------
    The resolved value, or None if param_name isn't a parameter of
    func or wasn't supplied in this call.
    """
    if explicit_value is not None:
        return explicit_value

    if param_name in kwargs:
        return kwargs[param_name]

    try:
        signature = inspect.signature(func)
        param_names = list(signature.parameters.keys())
        if param_name in param_names:
            index = param_names.index(param_name)
            if index < len(args):
                return args[index]
    except (ValueError, TypeError):
        pass

    return None


def audit_tool_call(
    agent_name: str,
    tool_name: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    patient_id: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """
    Decorator factory that wraps an async tool function with automatic
    audit_log writing.

    Parameters
    ----------
    agent_name      The agent attributed for this audit entry, e.g.
                    "billing_tools" or "records_agent". Static - always
                    the same value for a given tool.
    tool_name       The tool's name, used to build the audit
                    action string as f"{tool_name}" (kept distinct from
                    agent_name so the log shows exactly which function
                    ran).
    resource_type   Static override for the audit resource_type field
                    (e.g. "billing_invoice"). If None, no resource_type
                    is recorded unless the wrapped call supplies a
                    "resource_type" keyword argument matching this name.
    resource_id     Static override for the audit resource_id field.
                    If None, the decorator looks for a call argument
                    named "resource_id", then falls back to common
                    ID-like parameter names: "appointment_id",
                    "invoice_id", "ticket_id".
    patient_id      Static override for the audit patient_id field.
                    If None, the decorator looks for a call argument
                    named "patient_id".
    session_id      Static override for the audit session_id field.
                    If None, the decorator looks for a call argument
                    named "session_id".

    Returns
    -------
    A decorator that wraps an async function, calling it normally and
    then writing an audit_log entry via AuditRepository - on both
    success and failure (the entry's payload_summary notes whether the
    call succeeded or raised).

    The decorator never lets an audit-logging failure mask the
    original function's result or exception: if the audit write itself
    fails, that failure is logged via the application logger and
    swallowed, and the wrapped function's original return value or
    exception is what the caller ultimately sees.

    Apply this decorator BELOW @tool (i.e. closer to the function) so
    LangChain's tool-schema introspection still sees the original
    function signature:

        @tool
        @audit_tool_call(agent_name="...", tool_name="...")
        async def my_tool(...): ...
    """
    _id_fallback_params = ["resource_id", "appointment_id", "invoice_id", "ticket_id"]

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            resolved_patient_id = _extract_call_arg(func, args, kwargs, "patient_id", patient_id)
            resolved_session_id = _extract_call_arg(func, args, kwargs, "session_id", session_id)

            resolved_resource_id = resource_id
            if resolved_resource_id is None:
                for candidate_param in _id_fallback_params:
                    value = _extract_call_arg(func, args, kwargs, candidate_param)
                    if value is not None:
                        resolved_resource_id = value
                        break

            outcome = "succeeded"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception:
                outcome = "raised an exception"
                raise
            finally:
                try:
                    async with get_session_context() as session:
                        audit_repo = AuditRepository(session)
                        await audit_repo.log(
                            agent_name=agent_name,
                            action=tool_name,
                            session_id=resolved_session_id,
                            patient_id=resolved_patient_id,
                            resource_type=resource_type,
                            resource_id=str(resolved_resource_id) if resolved_resource_id is not None else None,
                            payload_summary=f"Tool call {tool_name} {outcome}.",
                        )
                except Exception as audit_exc:
                    logger.error(f"audit_tool_call: failed to write audit log for {tool_name}: {audit_exc}")

        return wrapper

    return decorator