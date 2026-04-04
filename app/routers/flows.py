"""Email Flow CRUD and management routes."""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user, require_operator, require_viewer, CurrentUser
from app.database import get_db
from app.models import (
    EmailFlow, EmailFlowAttachment, EmailRecipientJob, CsvImport,
    EmailSendAttempt, FlowStatus, JobStatus,
)
from app.services.csv_processor import validate_csv, expand_csv_to_jobs
from app.services.blob_storage import get_blob_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/flows", tags=["flows"])
templates = Jinja2Templates(directory="app/templates")


# ── List all flows ─────────────────────────────────────────────────────────────

@router.get("")
async def list_flows(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_viewer),
):
    """Show all email flows."""
    stmt = select(EmailFlow).order_by(EmailFlow.created_at.desc())
    result = await db.execute(stmt)
    flows = result.scalars().all()

    # Get job counts per flow
    flow_stats = {}
    for flow in flows:
        stats_stmt = (
            select(
                EmailRecipientJob.status,
                func.count(EmailRecipientJob.id),
            )
            .where(EmailRecipientJob.flow_id == flow.id)
            .group_by(EmailRecipientJob.status)
        )
        stats_result = await db.execute(stats_stmt)
        counts = {row[0]: row[1] for row in stats_result.all()}
        flow_stats[flow.id] = {
            "total": sum(counts.values()),
            "pending": counts.get(JobStatus.PENDING, 0) + counts.get(JobStatus.SCHEDULED, 0),
            "sent": counts.get(JobStatus.SENT, 0),
            "failed": counts.get(JobStatus.FAILED, 0),
        }

    return templates.TemplateResponse("flows_list.html", {
        "request": request,
        "flows": flows,
        "flow_stats": flow_stats,
        "user": user,
    })


# ── Create new flow ────────────────────────────────────────────────────────────

@router.get("/new")
async def new_flow_form(
    request: Request,
    user: CurrentUser = Depends(require_operator),
):
    """Show the create flow form."""
    return templates.TemplateResponse("flow_form.html", {
        "request": request,
        "flow": None,
        "user": user,
    })


@router.post("/new")
async def create_flow(
    request: Request,
    name: str = Form(...),
    subject: str = Form(...),
    from_email: str = Form(...),
    body_html: str = Form(""),
    send_at: Optional[str] = Form(None),
    timezone_str: str = Form("America/New_York"),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_operator),
):
    """Create a new email flow."""
    flow = EmailFlow(
        name=name,
        subject=subject,
        from_email=from_email,
        body_html=body_html,
        send_at=datetime.fromisoformat(send_at) if send_at else None,
        timezone=timezone_str,
        status=FlowStatus.DRAFT,
        created_by=user.email,
    )
    db.add(flow)
    await db.flush()

    logger.info("Flow created: id=%d name='%s' by=%s", flow.id, flow.name, user.email)
    return RedirectResponse(url=f"/flows/{flow.id}", status_code=303)


# ── Flow detail ────────────────────────────────────────────────────────────────

@router.get("/{flow_id}")
async def flow_detail(
    request: Request,
    flow_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_viewer),
):
    """Show flow details including recipients and status."""
    stmt = (
        select(EmailFlow)
        .options(
            selectinload(EmailFlow.attachments),
            selectinload(EmailFlow.csv_imports),
        )
        .where(EmailFlow.id == flow_id)
    )
    result = await db.execute(stmt)
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    # Get recipient jobs with pagination
    jobs_stmt = (
        select(EmailRecipientJob)
        .where(EmailRecipientJob.flow_id == flow_id)
        .order_by(EmailRecipientJob.id)
        .limit(100)
    )
    jobs_result = await db.execute(jobs_stmt)
    jobs = jobs_result.scalars().all()

    # Job stats
    stats_stmt = (
        select(
            EmailRecipientJob.status,
            func.count(EmailRecipientJob.id),
        )
        .where(EmailRecipientJob.flow_id == flow_id)
        .group_by(EmailRecipientJob.status)
    )
    stats_result = await db.execute(stats_stmt)
    job_counts = {row[0]: row[1] for row in stats_result.all()}

    return templates.TemplateResponse("flow_detail.html", {
        "request": request,
        "flow": flow,
        "jobs": jobs,
        "job_counts": job_counts,
        "user": user,
    })


# ── Edit flow ──────────────────────────────────────────────────────────────────

@router.get("/{flow_id}/edit")
async def edit_flow_form(
    request: Request,
    flow_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_operator),
):
    stmt = select(EmailFlow).where(EmailFlow.id == flow_id)
    result = await db.execute(stmt)
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    if flow.status not in (FlowStatus.DRAFT, FlowStatus.SCHEDULED):
        raise HTTPException(status_code=400, detail="Cannot edit a flow that is processing or completed")

    return templates.TemplateResponse("flow_form.html", {
        "request": request,
        "flow": flow,
        "user": user,
    })


@router.post("/{flow_id}/edit")
async def update_flow(
    request: Request,
    flow_id: int,
    name: str = Form(...),
    subject: str = Form(...),
    from_email: str = Form(...),
    body_html: str = Form(""),
    send_at: Optional[str] = Form(None),
    timezone_str: str = Form("America/New_York"),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_operator),
):
    stmt = select(EmailFlow).where(EmailFlow.id == flow_id)
    result = await db.execute(stmt)
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    flow.name = name
    flow.subject = subject
    flow.from_email = from_email
    flow.body_html = body_html
    flow.send_at = datetime.fromisoformat(send_at) if send_at else None
    flow.timezone = timezone_str

    await db.flush()
    return RedirectResponse(url=f"/flows/{flow.id}", status_code=303)


# ── Upload CSV ─────────────────────────────────────────────────────────────────

@router.post("/{flow_id}/upload-csv")
async def upload_csv(
    request: Request,
    flow_id: int,
    csv_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_operator),
):
    """Upload and process a CSV file for a flow."""
    stmt = select(EmailFlow).where(EmailFlow.id == flow_id)
    result = await db.execute(stmt)
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    # Read file content
    content = await csv_file.read()

    # Validate CSV
    validation = validate_csv(content)

    # Upload to blob storage
    blob_service = get_blob_service()
    blob_path = await blob_service.upload_csv(content, csv_file.filename, flow_id)

    # Create CSV import record
    csv_import = CsvImport(
        flow_id=flow_id,
        original_filename=csv_file.filename,
        blob_path=blob_path,
        row_count=validation.row_count,
        valid_rows=validation.valid_rows,
        error_rows=validation.error_rows,
        validation_errors=validation.errors if validation.errors else None,
        uploaded_by=user.email,
    )
    db.add(csv_import)
    await db.flush()

    # Expand valid rows into recipient jobs
    if validation.valid_rows > 0:
        await expand_csv_to_jobs(db, flow, csv_import, validation.rows)

    await db.commit()

    logger.info(
        "CSV uploaded for flow %d: %d valid, %d errors",
        flow_id, validation.valid_rows, validation.error_rows,
    )

    return RedirectResponse(url=f"/flows/{flow_id}", status_code=303)


# ── Upload attachments ─────────────────────────────────────────────────────────

@router.post("/{flow_id}/upload-attachments")
async def upload_attachments(
    request: Request,
    flow_id: int,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_operator),
):
    """Upload attachment files for a flow (shared across all recipients)."""
    stmt = select(EmailFlow).where(EmailFlow.id == flow_id)
    result = await db.execute(stmt)
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    blob_service = get_blob_service()

    for file in files:
        content = await file.read()
        blob_path = await blob_service.upload_attachment(
            content, file.filename, flow_id, file.content_type or "application/octet-stream"
        )

        attachment = EmailFlowAttachment(
            flow_id=flow_id,
            recipient_job_id=None,  # Shared attachment
            filename=file.filename,
            mime_type=file.content_type or "application/octet-stream",
            blob_path=blob_path,
            file_size=len(content),
        )
        db.add(attachment)

    await db.commit()

    logger.info("Uploaded %d attachments for flow %d", len(files), flow_id)
    return RedirectResponse(url=f"/flows/{flow_id}", status_code=303)


# ── Schedule / Start sending ───────────────────────────────────────────────────

@router.post("/{flow_id}/schedule")
async def schedule_flow(
    request: Request,
    flow_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_operator),
):
    """Move a Draft flow to Scheduled status, making it eligible for processing."""
    stmt = select(EmailFlow).where(EmailFlow.id == flow_id)
    result = await db.execute(stmt)
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    if flow.status != FlowStatus.DRAFT:
        raise HTTPException(status_code=400, detail=f"Flow is {flow.status.value}, can only schedule Draft flows")

    # Check there are recipient jobs
    count_stmt = select(func.count()).where(EmailRecipientJob.flow_id == flow_id)
    count_result = await db.execute(count_stmt)
    job_count = count_result.scalar()

    if job_count == 0:
        raise HTTPException(status_code=400, detail="No recipients. Upload a CSV first.")

    # Update flow and jobs status
    flow.status = FlowStatus.SCHEDULED

    await db.execute(
        update(EmailRecipientJob)
        .where(
            EmailRecipientJob.flow_id == flow_id,
            EmailRecipientJob.status == JobStatus.PENDING,
        )
        .values(status=JobStatus.SCHEDULED, scheduled_at=flow.send_at)
    )

    await db.commit()
    logger.info("Flow %d scheduled by %s", flow_id, user.email)

    return RedirectResponse(url=f"/flows/{flow_id}", status_code=303)


@router.post("/{flow_id}/start")
async def start_flow(
    request: Request,
    flow_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_operator),
):
    """Move a Scheduled flow to Processing (immediate send)."""
    stmt = select(EmailFlow).where(EmailFlow.id == flow_id)
    result = await db.execute(stmt)
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    if flow.status not in (FlowStatus.DRAFT, FlowStatus.SCHEDULED):
        raise HTTPException(status_code=400, detail=f"Cannot start a {flow.status.value} flow")

    flow.status = FlowStatus.PROCESSING

    # Set all pending/scheduled jobs to pending with immediate schedule
    now = datetime.now(timezone.utc)
    await db.execute(
        update(EmailRecipientJob)
        .where(
            EmailRecipientJob.flow_id == flow_id,
            EmailRecipientJob.status.in_([JobStatus.PENDING, JobStatus.SCHEDULED]),
        )
        .values(status=JobStatus.PENDING, scheduled_at=now)
    )

    await db.commit()
    logger.info("Flow %d started (immediate) by %s", flow_id, user.email)

    return RedirectResponse(url=f"/flows/{flow_id}", status_code=303)


# ── Cancel flow ────────────────────────────────────────────────────────────────

@router.post("/{flow_id}/cancel")
async def cancel_flow(
    request: Request,
    flow_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_operator),
):
    """Cancel a flow, preventing unsent jobs from being processed."""
    stmt = select(EmailFlow).where(EmailFlow.id == flow_id)
    result = await db.execute(stmt)
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    flow.status = FlowStatus.CANCELLED

    await db.execute(
        update(EmailRecipientJob)
        .where(
            EmailRecipientJob.flow_id == flow_id,
            EmailRecipientJob.status.in_([JobStatus.PENDING, JobStatus.SCHEDULED]),
        )
        .values(status=JobStatus.CANCELLED)
    )

    await db.commit()
    logger.info("Flow %d cancelled by %s", flow_id, user.email)

    return RedirectResponse(url=f"/flows/{flow_id}", status_code=303)
