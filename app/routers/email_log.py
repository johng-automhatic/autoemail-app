"""Email log routes — row-level delivery audit trail."""

import logging
from fastapi import APIRouter, Depends, Request, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user, require_viewer, CurrentUser
from app.database import get_db
from app.models import EmailRecipientJob, EmailSendAttempt, EmailFlow, JobStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/logs", tags=["logs"])
templates = Jinja2Templates(directory="app/templates")


@router.get("")
async def email_log(
    request: Request,
    status_filter: str = Query(None, alias="status"),
    flow_id: int = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_viewer),
):
    """Show email delivery log with filtering and pagination."""

    # Base query
    stmt = (
        select(EmailRecipientJob)
        .options(selectinload(EmailRecipientJob.send_attempts))
        .join(EmailFlow, EmailRecipientJob.flow_id == EmailFlow.id)
    )

    # Apply filters
    if status_filter:
        try:
            status_enum = JobStatus(status_filter)
            stmt = stmt.where(EmailRecipientJob.status == status_enum)
        except ValueError:
            pass

    if flow_id:
        stmt = stmt.where(EmailRecipientJob.flow_id == flow_id)

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar()

    # Paginate
    stmt = stmt.order_by(EmailRecipientJob.updated_at.desc())
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    # Load flow names for display
    flow_ids = list(set(j.flow_id for j in jobs))
    if flow_ids:
        flows_stmt = select(EmailFlow).where(EmailFlow.id.in_(flow_ids))
        flows_result = await db.execute(flows_stmt)
        flows_map = {f.id: f.name for f in flows_result.scalars().all()}
    else:
        flows_map = {}

    total_pages = (total + per_page - 1) // per_page

    return templates.TemplateResponse("email_log.html", {
        "request": request,
        "user": user,
        "jobs": jobs,
        "flows_map": flows_map,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "status_filter": status_filter,
        "flow_id_filter": flow_id,
        "statuses": [s.value for s in JobStatus],
    })
