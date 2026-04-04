"""Initial schema - all tables

Revision ID: 001_initial
Revises:
Create Date: 2026-04-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # EmailFlows
    op.create_table(
        "email_flows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("from_email", sa.String(length=320), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="America/New_York"),
        sa.Column("status", sa.Enum("Draft", "Scheduled", "Processing", "Completed", "Cancelled", name="flowstatus"), nullable=False, server_default="Draft"),
        sa.Column("created_by", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # CsvImports
    op.create_table(
        "csv_imports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("flow_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("blob_path", sa.String(length=1000), nullable=False),
        sa.Column("row_count", sa.Integer(), server_default="0"),
        sa.Column("valid_rows", sa.Integer(), server_default="0"),
        sa.Column("error_rows", sa.Integer(), server_default="0"),
        sa.Column("validation_errors", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("uploaded_by", sa.String(length=320), nullable=True),
        sa.ForeignKeyConstraint(["flow_id"], ["email_flows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # EmailRecipientJobs
    op.create_table(
        "email_recipient_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("flow_id", sa.Integer(), nullable=False),
        sa.Column("csv_import_id", sa.Integer(), nullable=True),
        sa.Column("to_email", sa.String(length=320), nullable=False),
        sa.Column("merge_fields", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("attachment_refs", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Enum("Pending", "Scheduled", "Sending", "Sent", "Failed", "Cancelled", name="jobstatus"), nullable=False, server_default="Pending"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["flow_id"], ["email_flows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["csv_import_id"], ["csv_imports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recipient_jobs_status_scheduled", "email_recipient_jobs", ["status", "scheduled_at"])
    op.create_index("ix_recipient_jobs_flow_id", "email_recipient_jobs", ["flow_id"])

    # EmailFlowAttachments
    op.create_table(
        "email_flow_attachments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("flow_id", sa.Integer(), nullable=False),
        sa.Column("recipient_job_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("blob_path", sa.String(length=1000), nullable=False),
        sa.Column("file_size", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["flow_id"], ["email_flows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_job_id"], ["email_recipient_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # EmailSendAttempts
    op.create_table(
        "email_send_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recipient_job_id", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.String(length=255), nullable=True),
        sa.Column("provider_status", sa.String(length=50), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["recipient_job_id"], ["email_recipient_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_send_attempts_job_id", "email_send_attempts", ["recipient_job_id"])


def downgrade() -> None:
    op.drop_table("email_send_attempts")
    op.drop_table("email_flow_attachments")
    op.drop_table("email_recipient_jobs")
    op.drop_table("csv_imports")
    op.drop_table("email_flows")
    op.execute("DROP TYPE IF EXISTS flowstatus")
    op.execute("DROP TYPE IF EXISTS jobstatus")
