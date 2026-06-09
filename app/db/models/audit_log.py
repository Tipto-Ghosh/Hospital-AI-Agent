from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import TEXT,BigInteger,DateTime,Index,Integer,String,func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base



class AuditLog(Base):
    """
    Maps to the `audit_log` table.

    Every row is an immutable event record.  No instance method on this
    class mutates an existing row — the only write path is log_action().

    Column design
    -------------
    log_id          BIGINT AUTO_INCREMENT — supports billions of rows over
                    the 7-year retention window without overflow.
    session_id      VARCHAR(64) — matches the Redis/DB session key format.
    patient_id      VARCHAR(20) — nullable; emergency logs have no patient.
    agent_name      VARCHAR(50) — which sub-agent produced this log entry.
    action          VARCHAR(100) — snake_case verb, e.g. 'read_medical_history'.
    resource_type   VARCHAR(50) — entity type, e.g. 'appointment', 'lab_result'.
    resource_id     VARCHAR(50) — PK of the accessed/modified resource.
    payload_summary TEXT — non-PHI human-readable summary (see PHI rules above).
    ip_address      VARCHAR(45) — IPv4 or IPv6; populated by FastAPI middleware.
    timestamp       DATETIME — DB server time at INSERT, never application time.
    """

    __tablename__ = "audit_log"

    __table_args__ = (
        Index("idx_patient_audit", "patient_id", "timestamp"),
        Index("idx_session_audit", "session_id"),
    )

    log_id: Mapped[int] = mapped_column(
        Integer,  # SQLite compat; migration DDL explicitly uses BIGINT in MySQL
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

    # No update/delete methods — append-only contract
    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.log_id} "
            f"agent={self.agent_name!r} action={self.action!r} "
            f"patient={self.patient_id!r} ts={self.timestamp}>"
        )

    # Convenience factory
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
        """
        Append a single audit event and flush it to the DB.

        Parameters
        ----------
        session         AsyncSession — caller's active session; this method
                        does NOT commit so the caller retains transaction control.
        agent_name      Which sub-agent is logging (required).
        action          Snake_case action verb (required).
        session_id      Redis/DB session key (optional).
        patient_id      Patient PK (optional — omit for pre-auth emergency logs).
        resource_type   Entity type affected (optional).
        resource_id     PK of the affected resource as a string (optional).
        payload_summary Non-PHI human-readable summary (optional).
        ip_address      Client IP from FastAPI request (optional).

        Returns
        -------
        The newly created AuditLog instance (already flushed, log_id populated).

        Example
        -------
            entry = await AuditLog.log_action(
                session       = db,
                agent_name    = "records_agent",
                action        = "read_medical_history",
                session_id    = "sess_abc123",
                patient_id    = "P-2024-00001",
                resource_type = "medical_record",
                resource_id   = "42",
                payload_summary = "Read 2 medical records (2024-01 to 2024-03)",
                ip_address    = "192.168.1.100",
            )
            print(entry.log_id)  # available after flush
        """
        entry = cls(
            agent_name=agent_name,
            action=action,
            session_id=session_id,
            patient_id=patient_id,
            resource_type=resource_type,
            resource_id=resource_id,
            payload_summary=payload_summary,
            ip_address=ip_address,
            # timestamp is set by the DB server_default — not passed here
        )
        session.add(entry)
        await session.flush()  # populates log_id without committing
        return entry