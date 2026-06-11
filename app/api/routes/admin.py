from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import StaffTokenData, get_current_staff, get_db, require_admin
from app.db.models.audit_log import AuditLog
from app.db.models.feedback import Feedback
from app.db.models.medication import HospitalInfo, HOSPITAL_INFO_CATEGORIES
from app.db.models.memory import ConversationMemory, ConversationSession
from app.logger import logging as logger

router = APIRouter()


# GET /admin/v1/audit-log

class AuditLogEntry(BaseModel):
    log_id: int
    session_id: str | None
    patient_id: str | None
    agent_name: str
    action: str
    resource_type: str | None
    resource_id: str | None
    payload_summary: str | None
    ip_address: str | None
    timestamp: datetime


class AuditLogResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    entries: list[AuditLogEntry]


@router.get(
    "/audit-log",
    response_model=AuditLogResponse,
    summary="Query the audit log (paginated, filterable)",
    description=(
        "Returns audit_log entries newest-first. "
        "Filterable by patient_id, agent_name, and a date range. "
        "Required for healthcare compliance reviews."
    ),
)
async def get_audit_log(
    patient_id: str | None = Query(None, description="Filter by patient PK."),
    agent_name: str | None = Query(None, description="Filter by agent name, e.g. 'records_agent'."),
    action: str | None = Query(None, description="Filter by action verb, e.g. 'read_lab_results'."),
    date_from: date | None = Query(None, description="Inclusive start date (UTC)."),
    date_to: date | None = Query(None, description="Inclusive end date (UTC)."),
    page: int = Query(1, ge=1, description="1-indexed page number."),
    page_size: int = Query(50, ge=1, le=500, description="Rows per page (max 500)."),
    staff: StaffTokenData = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> AuditLogResponse:
    filters = []

    if patient_id:
        filters.append(AuditLog.patient_id == patient_id)
    if agent_name:
        filters.append(AuditLog.agent_name == agent_name)
    if action:
        filters.append(AuditLog.action == action)
    if date_from:
        filters.append(AuditLog.timestamp >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        # Inclusive end-of-day
        filters.append(AuditLog.timestamp < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))

    # Total count for pagination metadata
    count_stmt = select(func.count()).select_from(AuditLog)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    # Page of results
    stmt = (
        select(AuditLog)
        .order_by(AuditLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        stmt = stmt.where(*filters)

    rows = (await db.execute(stmt)).scalars().all()

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    logger.info(
        f"Audit log queried by staff={staff.staff_id} role={staff.role} | filters: patient={patient_id} agent={agent_name} "
        f"action={action} from={date_from} to={date_to} | page={page}/{total_pages}"
    )

    return AuditLogResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        entries=[
            AuditLogEntry(
                log_id=r.log_id,
                session_id=r.session_id,
                patient_id=r.patient_id,
                agent_name=r.agent_name,
                action=r.action,
                resource_type=r.resource_type,
                resource_id=r.resource_id,
                payload_summary=r.payload_summary,
                ip_address=r.ip_address,
                timestamp=r.timestamp,
            )
            for r in rows
        ],
    )


# GET /admin/v1/conversations
class ConversationSummary(BaseModel):
    session_id: str
    patient_id: str | None
    channel: str
    is_active: bool
    started_at: datetime
    last_active_at: datetime | None
    message_count: int


class ConversationListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    conversations: list[ConversationSummary]


@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    summary="List chat sessions with message counts",
    description=(
        "Returns conversation_sessions with a count of archived messages "
        "per session. Does NOT return message content — only metadata. "
        "Filterable by patient_id and active status."
    ),
)
async def list_conversations(
    patient_id: str | None = Query(None, description="Filter by patient PK."),
    is_active: bool | None = Query(None, description="Filter by session active status."),
    channel: str | None = Query(None, description="Filter by channel (web/whatsapp/kiosk/api)."),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    staff: StaffTokenData = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> ConversationListResponse:
    filters = []
    if patient_id:
        filters.append(ConversationSession.patient_id == patient_id)
    if is_active is not None:
        filters.append(ConversationSession.is_active.is_(is_active))
    if channel:
        filters.append(ConversationSession.channel == channel)

    count_stmt = select(func.count()).select_from(ConversationSession)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    # Subquery: message count per session
    msg_count_subq = (
        select(
            ConversationMemory.session_id,
            func.count(ConversationMemory.memory_id).label("msg_count"),
        )
        .group_by(ConversationMemory.session_id)
        .subquery()
    )

    stmt = (
        select(ConversationSession, func.coalesce(msg_count_subq.c.msg_count, 0))
        .outerjoin(
            msg_count_subq,
            ConversationSession.session_id == msg_count_subq.c.session_id,
        )
        .order_by(ConversationSession.started_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        stmt = stmt.where(*filters)

    rows = (await db.execute(stmt)).all()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    logger.info(
        "Conversations listed by staff=%s role=%s | page=%d/%d",
        staff.staff_id, staff.role, page, total_pages,
    )

    return ConversationListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        conversations=[
            ConversationSummary(
                session_id=sess.session_id,
                patient_id=sess.patient_id,
                channel=sess.channel,
                is_active=sess.is_active,
                started_at=sess.started_at,
                last_active_at=sess.last_active_at,
                message_count=int(msg_count),
            )
            for sess, msg_count in rows
        ],
    )


# POST /admin/v1/hospital-info
class HospitalInfoUpsertRequest(BaseModel):
    """
    Request body for POST /admin/v1/hospital-info.

    If info_id is provided and exists, the row is UPDATED.
    If info_id is None (or doesn't match an existing row), a new row
    is INSERTED.
    """

    info_id: int | None = Field(
        None, description="Existing row ID to update, or omit to insert a new row."
    )
    category: str = Field(
        ...,
        description=f"One of: {', '.join(HOSPITAL_INFO_CATEGORIES)}.",
    )
    topic: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)


class HospitalInfoResponse(BaseModel):
    info_id: int
    category: str
    topic: str
    content: str
    last_updated: datetime
    action: str = Field(description="'created' or 'updated'.")


@router.post(
    "/hospital-info",
    response_model=HospitalInfoResponse,
    status_code=status.HTTP_200_OK,
    summary="Upsert a hospital_info record",
    description=(
        "Creates a new hospital_info row, or updates an existing one if "
        "info_id is provided and exists. This data is surfaced directly "
        "to patients via the Information Agent — review carefully before "
        "submitting. Requires the 'admin' role."
    ),
    responses={
        200: {"description": "Record created or updated"},
        400: {"description": "Invalid category"},
        403: {"description": "Admin role required"},
    },
)
async def upsert_hospital_info(
    body: HospitalInfoUpsertRequest,
    staff: StaffTokenData = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HospitalInfoResponse:
    if body.category not in HOSPITAL_INFO_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid category {body.category!r}. "
                f"Must be one of: {', '.join(HOSPITAL_INFO_CATEGORIES)}."
            ),
        )

    action = "created"
    record: HospitalInfo | None = None

    if body.info_id is not None:
        record = await db.get(HospitalInfo, body.info_id)

    if record is not None:
        record.category = body.category
        record.topic = body.topic
        record.content = body.content
        record.last_updated = datetime.utcnow()
        action = "updated"
    else:
        record = HospitalInfo(
            category=body.category,
            topic=body.topic,
            content=body.content,
        )
        db.add(record)
        action = "created"

    await db.commit()
    await db.refresh(record)

    logger.info(
        f"Hospital info {action} by staff={staff.staff_id} | info_id={record.info_id} category={record.category} topic={record.topic}"
    )

    return HospitalInfoResponse(
        info_id=record.info_id,
        category=record.category,
        topic=record.topic,
        content=record.content,
        last_updated=record.last_updated,
        action=action,
    )


# GET /admin/v1/feedback-report
class CategoryRatingSummary(BaseModel):
    category: str
    count: int
    average_rating: float | None
    rating_distribution: dict[str, int] = Field(
        description="Count of feedback entries per rating value 1-5."
    )


class FeedbackReportResponse(BaseModel):
    total_feedback: int
    overall_average_rating: float | None
    by_category: list[CategoryRatingSummary]


@router.get(
    "/feedback-report",
    response_model=FeedbackReportResponse,
    summary="Aggregated feedback ratings by category",
    description=(
        "Returns count, average rating, and rating distribution (1-5 stars) "
        "per feedback category. Individual feedback messages are not "
        "included — use this for dashboard summaries."
    ),
)
async def get_feedback_report(
    date_from: date | None = Query(None, description="Inclusive start date (UTC)."),
    date_to: date | None = Query(None, description="Inclusive end date (UTC)."),
    staff: StaffTokenData = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> FeedbackReportResponse:
    filters = []
    if date_from:
        filters.append(Feedback.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        filters.append(Feedback.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))

    # Overall stats
    overall_stmt = select(
        func.count(Feedback.feedback_id),
        func.avg(Feedback.rating),
    )
    if filters:
        overall_stmt = overall_stmt.where(*filters)
    total_count, overall_avg = (await db.execute(overall_stmt)).one()

    # Per-category stats
    cat_stmt = select(
        Feedback.category,
        func.count(Feedback.feedback_id),
        func.avg(Feedback.rating),
    ).group_by(Feedback.category)
    if filters:
        cat_stmt = cat_stmt.where(*filters)
    cat_rows = (await db.execute(cat_stmt)).all()

    # Rating distribution per category
    by_category: list[CategoryRatingSummary] = []
    for category, count, avg_rating in cat_rows:
        dist_stmt = (
            select(Feedback.rating, func.count(Feedback.feedback_id))
            .where(Feedback.category == category)
            .group_by(Feedback.rating)
        )
        if filters:
            dist_stmt = dist_stmt.where(*filters)
        dist_rows = (await db.execute(dist_stmt)).all()

        distribution = {str(i): 0 for i in range(1, 6)}
        for rating, rcount in dist_rows:
            if rating is not None:
                distribution[str(rating)] = rcount

        by_category.append(
            CategoryRatingSummary(
                category=category,
                count=count,
                average_rating=round(float(avg_rating), 2) if avg_rating is not None else None,
                rating_distribution=distribution,
            )
        )

    # Sort by count descending for dashboard relevance
    by_category.sort(key=lambda c: c.count, reverse=True)

    logger.info(
        "Feedback report generated by staff=%s role=%s | total=%d",
        staff.staff_id, staff.role, total_count,
    )

    return FeedbackReportResponse(
        total_feedback=total_count,
        overall_average_rating=(
            round(float(overall_avg), 2) if overall_avg is not None else None
        ),
        by_category=by_category,
    )