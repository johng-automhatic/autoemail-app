"""Dashboard route — overview of all email flows and job statuses."""

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, CurrentUser
from app.database import get_db
from app.models import EmailFlow, EmailRecipientJob, FlowStatus, JobStatus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Main dashboard with summary counts."""

    # Overall job counts
    job_stats_stmt = (
        select(
            EmailRecipientJob.status,
            func.count(EmailRecipientJob.id),
        )
        .group_by(EmailRecipientJob.status)
    )
    job_stats_result = await db.execute(job_stats_stmt)
    job_counts = {row[0]: row[1] for row in job_stats_result.all()}

    total_jobs = sum(job_counts.values())
    pending_count = job_counts.get(JobStatus.PENDING, 0) + job_counts.get(JobStatus.SCHEDULED, 0)
    sent_count = job_counts.get(JobStatus.SENT, 0)
    failed_count = job_counts.get(JobStatus.FAILED, 0)
    sending_count = job_counts.get(JobStatus.SENDING, 0)

    # Flow counts by status
    flow_stats_stmt = (
        select(EmailFlow.status, func.count(EmailFlow.id))
        .group_by(EmailFlow.status)
    )
    flow_stats_result = await db.execute(flow_stats_stmt)
    flow_counts = {row[0]: row[1] for row in flow_stats_result.all()}

    # Recent flows
    recent_flows_stmt = (
        select(EmailFlow)
        .order_by(EmailFlow.updated_at.desc())
        .limit(10)
    )
    recent_result = await db.execute(recent_flows_stmt)
    recent_flows = recent_result.scalars().all()

    # Next scheduled batch
    next_scheduled_stmt = (
        select(EmailFlow)
        .where(EmailFlow.status.in_([FlowStatus.SCHEDULED, FlowStatus.PROCESSING]))
        .order_by(EmailFlow.send_at.asc())
        .limit(1)
    )
    next_result = await db.execute(next_scheduled_stmt)
    next_scheduled = next_result.scalar_one_or_none()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "total_jobs": total_jobs,
        "pending_count": pending_count,
        "sent_count": sent_count,
        "failed_count": failed_count,
        "sending_count": sending_count,
        "flow_counts": flow_counts,
        "recent_flows": recent_flows,
        "next_scheduled": next_scheduled,
    })
