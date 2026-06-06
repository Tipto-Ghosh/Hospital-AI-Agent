from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import TEXT,Integer,BigInteger,DateTime,Index,String,event,func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.logger import logging
from app.exception import CustomException

class AuditLog(Base):
    """
    Maps to the `audit_log` table.

    Every row is an immutable event record.  No instance method on this
    class mutates an existing row — the only write path is log_action().
    """

    __tablename__ = "audit_log"

    __table_args__ = (
        Index("idx_patient_audit", "patient_id", "timestamp"),
        Index("idx_session_audit", "session_id"),
    )

    log_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="BIGINT to support billions of rows over the 7-year retention window.",
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Redis/DB session key. Nullable for system-level actions.",
    )
    patient_id: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment=(
            "Patient PK. Nullable: emergency logs are written before "
            "authentication is known."
        ),
    )
    agent_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Sub-agent that triggered this action, e.g. 'records_agent'.",
    )
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Snake_case action verb, e.g. 'read_lab_results', 'cancel_appointment'.",
    )
    resource_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Entity type affected, e.g. 'appointment', 'billing_invoice'.",
    )
    resource_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="PK of the resource accessed or modified. Stored as string for flexibility.",
    )
    payload_summary: Mapped[Optional[str]] = mapped_column(
        TEXT,
        nullable=True,
        comment=(
            "NON-PHI summary only. "
            "Example: 'Read 3 lab results' — NOT the result values themselves. "
            "Violation of this rule is a HIPAA/healthcare compliance breach."
        ),
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
        comment="Supports both IPv4 (15 chars) and IPv6 (39 chars) addresses.",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        index=True,
        comment="Set by the DB server at INSERT — never set by application code.",
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.log_id} "
            f"agent={self.agent_name!r} action={self.action!r} "
            f"patient={self.patient_id!r} ts={self.timestamp}>"
        )

    @classmethod
    async def log_action(
        cls,
        session: AsyncSession,
        *,
        agent_name: str,
        action: str,
        session_id: Optional[str] = None,
        patient_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        payload_summary: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> "AuditLog":
        
        entry = cls(
            agent_name=agent_name,
            action=action,
            session_id=session_id,
            patient_id=patient_id,
            resource_type=resource_type,
            resource_id=resource_id,
            payload_summary=payload_summary,
            ip_address=ip_address,
        )
        try:
            session.add(entry)
            await session.flush()
            logging.info(
                "AuditLog created: agent=%s, action=%s, patient=%s, resource=%s:%s",
                agent_name, action, patient_id, resource_type, resource_id,
            )
            return entry
        except Exception as exc:
            logging.exception("Failed to create AuditLog entry.")
            raise CustomException(
                error_message="Audit log entry creation failed.",
                error_detail=str(exc),
            ) from exc



@event.listens_for(AuditLog, "after_insert")
def _log_audit_insert(mapper, connection, target: AuditLog) -> None:
    try:
        logging.debug(
            "AuditLog after_insert: id=%d, agent=%s, action=%s, patient=%s",
            target.log_id, target.agent_name, target.action, target.patient_id,
        )
    except Exception as exc:
        logging.exception("Logging failure in AuditLog after_insert event.")
        raise CustomException(
            error_message="Failed to process AuditLog insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(AuditLog, "after_update")
def _log_audit_update(mapper, connection, target: AuditLog) -> None:
    try:
        logging.warning(
            "AuditLog updated (should never happen): id=%d, agent=%s, action=%s",
            target.log_id, target.agent_name, target.action,
        )
    except Exception as exc:
        logging.exception("Logging failure in AuditLog after_update event.")
        raise CustomException(
            error_message="Failed to process AuditLog update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(AuditLog, "after_delete")
def _log_audit_delete(mapper, connection, target: AuditLog) -> None:
    try:
        logging.warning(
            "AuditLog deleted (should never happen): id=%d, agent=%s, action=%s",
            target.log_id, target.agent_name, target.action,
        )
    except Exception as exc:
        logging.exception("Logging failure in AuditLog after_delete event.")
        raise CustomException(
            error_message="Failed to process AuditLog delete event.",
            error_detail=str(exc),
        ) from exc