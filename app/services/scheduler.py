"""Background scheduler for processing queued email jobs.

Runs on APScheduler within the FastAPI process. Picks up EmailRecipientJob
records that are due (scheduled_at <= now) and sends them through ACS.
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import _get_session_maker
from app.models import (
    EmailRecipientJob, EmailSendAttempt, EmailFlow, EmailFlowAttachment,
    JobStatus, FlowStatus,
)
from app.services.email_sender import EmailSenderService, render_template
from app.services.blob_storage import BlobStorageService
from app.config import get_settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def process_pending_jobs():
    """Pick and process email jobs that are due for sending.

    Runs every 60 seconds. Processes up to 50 jobs per cycle to avoid
    overwhelming ACS rate limits.
    """
    now = datetime.now(timezone.utc)
    batch_size = 50

    async with _get_session_maker()() as db:
        try:
            # Find jobs that are due
            stmt = (
                select(EmailRecipientJob)
                .where(
                    EmailRecipientJob.status.in_([JobStatus.PENDING, JobStatus.SCHEDULED]),
                    EmailRecipientJob.scheduled_at <= now,
                )
                .order_by(EmailRecipientJob.scheduled_at.asc())
                .limit(batch_size)
            )
            result = await db.execute(stmt)
            jobs = result.scalars().all()

            if not jobs:
                return

            logger.info("Processing %d pending email jobs", len(jobs))
            email_service = EmailSenderService()
            blob_service = BlobStorageService()
            settings = get_settings()

            for job in jobs:
                await _send_single_job(db, job, email_service, blob_service, settings)

            await db.commit()

            # Check if any flows are now complete
            await _update_flow_statuses(db)
            await db.commit()

        except Exception as e:
            logger.error("Scheduler error: %s", str(e), exc_info=True)
            await db.rollback()


async def _send_single_job(
    db: AsyncSession,
    job: EmailRecipientJob,
    email_service: EmailSenderService,
    blob_service: BlobStorageService,
    settings,
):
    """Send one email job and record the attempt."""
    try:
        # Mark as sending
        job.status = JobStatus.SENDING
        await db.flush()

        # Load the flow for template and from address
        flow_result = await db.execute(
            select(EmailFlow).where(EmailFlow.id == job.flow_id)
        )
        flow = flow_result.scalar_one_or_none()
        if not flow:
            job.status = JobStatus.FAILED
            job.error_message = "Flow not found"
            return

        # Render the HTML body with merge fields
        rendered_body = render_template(
            flow.body_html,
            job.merge_fields or {},
        )

        # Gather attachments
        attachments = []

        # Flow-level attachments (shared, no recipient_job_id)
        att_result = await db.execute(
            select(EmailFlowAttachment).where(
                EmailFlowAttachment.flow_id == flow.id,
                EmailFlowAttachment.recipient_job_id.is_(None),
            )
        )
        flow_attachments = att_result.scalars().all()

        for att in flow_attachments:
            try:
                content = await blob_service.download_blob(
                    settings.blob_container_attachments, att.blob_path
                )
                attachments.append({
                    "name": att.filename,
                    "content_type": att.mime_type,
                    "content_bytes": content,
                })
            except Exception as e:
                logger.warning("Could not load attachment %s: %s", att.blob_path, e)

        # Per-row attachment references
        if job.attachment_refs:
            for ref in job.attachment_refs:
                try:
                    content = await blob_service.download_blob(
                        settings.blob_container_attachments, ref
                    )
                    filename = ref.rsplit("/", 1)[-1]
                    attachments.append({
                        "name": filename,
                        "content_type": "application/octet-stream",
                        "content_bytes": content,
                    })
                except Exception as e:
                    logger.warning("Could not load per-row attachment %s: %s", ref, e)

        # Send the email
        send_result = email_service.send_email(
            from_email=flow.from_email,
            to_email=job.to_email,
            subject=flow.subject,
            body_html=rendered_body,
            attachments=attachments if attachments else None,
        )

        # Handle if send_email is async
        if hasattr(send_result, "__await__"):
            send_result = await send_result

        # Record the send attempt
        attempt = EmailSendAttempt(
            recipient_job_id=job.id,
            operation_id=send_result.get("operation_id"),
            provider_status=send_result.get("status"),
            error_message=send_result.get("error"),
        )
        db.add(attempt)

        # Update job status
        if send_result["status"] in ("Succeeded", "Running"):
            job.status = JobStatus.SENT
            job.sent_at = datetime.now(timezone.utc)
            job.error_message = None
        else:
            job.retry_count += 1
            if job.retry_count >= 3:
                job.status = JobStatus.FAILED
                job.error_message = send_result.get("error", "Max retries exceeded")
            else:
                job.status = JobStatus.PENDING  # Will retry next cycle
                job.error_message = send_result.get("error")

        await db.flush()

    except Exception as e:
        logger.error("Error sending job %d: %s", job.id, str(e), exc_info=True)
        job.status = JobStatus.FAILED
        job.error_message = str(e)
        await db.flush()


async def _update_flow_statuses(db: AsyncSession):
    """Check flows that are Processing and mark Completed if all jobs are done."""
    stmt = select(EmailFlow).where(EmailFlow.status == FlowStatus.PROCESSING)
    result = await db.execute(stmt)
    flows = result.scalars().all()

    for flow in flows:
        # Count jobs still in progress
        pending_stmt = select(func.count()).where(
            EmailRecipientJob.flow_id == flow.id,
            EmailRecipientJob.status.in_([JobStatus.PENDING, JobStatus.SCHEDULED, JobStatus.SENDING]),
        )
        pending_result = await db.execute(pending_stmt)
        pending_count = pending_result.scalar()

        if pending_count == 0:
            flow.status = FlowStatus.COMPLETED
            logger.info("Flow %d completed", flow.id)

    await db.flush()


def start_scheduler():
    """Start the background job scheduler."""
    scheduler.add_job(
        process_pending_jobs,
        "interval",
        seconds=60,
        id="process_pending_jobs",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Email job scheduler started (60-second interval)")


def stop_scheduler():
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Email job scheduler stopped")
