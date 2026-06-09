from __future__ import annotations
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.audit_log import AuditLog
from app.logger import logging


class AuditRepository:
    """
    Append-only write access to the audit_log table.

    Exposes a single public method: log().
    No read, update, or delete methods exist on this class by design.

    Parameters
    session: Active AsyncSession — the audit entry is flushed (not committed) within the caller's transaction.
    """
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def log(
        self,
        *,
        agent_name: str,
        action: str,
        session_id: str | None = None,
        patient_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        payload_summary: str | None = None,
        ip_address: str | None = None,
    ) -> int:
        """
        Append a single audit entry and return its log_id.

        All parameters are keyword-only to prevent accidental positional
        mismatches (important for a compliance-critical method).

        Parameters
        agent_name: Which sub-agent triggered this (required).
        action: Snake_case action verb (required).
        session_id: Redis/DB session key.
        patient_id: Patient PK (optional — omit for pre-auth
        resource_type: Entity type touched.
        resource_id: PK of the resource as a string.
        payload_summary: Non-PHI human-readable summary.
        ip_address: Client IP from FastAPI request.

        Returns
        log_id: The auto-incremented BIGINT primary key of the new row.
                Callers may log this for debugging but should not store
                it as a reference — the audit log is write-only from the
                agent's perspective.

        Raises:
        Does not raise on its own.  DB exceptions from the underlying
        flush() propagate to the caller's transaction handler.
        """
        entry = await AuditLog.log_action(
            session=self._s,
            agent_name=agent_name,
            action=action,
            session_id=session_id,
            patient_id=patient_id,
            resource_type=resource_type,
            resource_id=resource_id,
            payload_summary=payload_summary,
            ip_address=ip_address,
        )
        logging.debug(
            f"audit log_id={entry.log_id} agent={agent_name} action={action} patient={patient_id}"
        )
        return entry.log_id