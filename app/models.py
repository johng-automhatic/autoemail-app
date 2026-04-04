"""SQLAlchemy models for the Email Flow Manager."""

import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Enum, ForeignKey,
    Boolean, JSON, func,
)
from sqlalchemy.orm import relationship
from app.database import Base


# ── Enums ──────────────────────────────────────────────────────────────────────

class FlowStatus(str, enum.Enum):
    DRAFT = "Draft"
    SCHEDULED = "Scheduled"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class JobStatus(str, enum.Enum):
    PENDING = "Pending"
    SCHEDULED = "Scheduled"
    SENDING = "Sending"
    SENT = "Sent"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class UserRole(str, enum.Enum):
    ADMIN = "EmailFlow.Admin"
    OPERATOR = "EmailFlow.Operator"
    VIEWER = "EmailFlow.Viewer"


# ── Models ─────────────────────────────────────────────────────────────────────

class EmailFlow(Base):
    """An email campaign/flow with subject, sender, template, and schedule."""
    __tablename__ = "email_flows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    from_email = Column(String(320), nullable=False)
    body_html = Column(Text, nullable=False, default="")
    send_at = Column(DateTime(timezone=True), nullable=True)
    timezone = Column(String(64), default="America/New_York")
    status = Column(Enum(FlowStatus), default=FlowStatus.DRAFT, nullable=False)
    created_by = Column(String(320), nullable=True)  # Entra ID user email/OID
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    attachments = relationship("EmailFlowAttachment", back_populates="flow", cascade="all, delete-orphan")
    recipient_jobs = relationship("EmailRecipientJob", back_populates="flow", cascade="all, delete-orphan")
    csv_imports = relationship("CsvImport", back_populates="flow", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<EmailFlow id={self.id} name='{self.name}' status={self.status}>"


class EmailFlowAttachment(Base):
    """File attachment linked to a flow (shared) or to a specific recipient job."""
    __tablename__ = "email_flow_attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    flow_id = Column(Integer, ForeignKey("email_flows.id", ondelete="CASCADE"), nullable=False)
    recipient_job_id = Column(Integer, ForeignKey("email_recipient_jobs.id", ondelete="SET NULL"), nullable=True)
    filename = Column(String(500), nullable=False)
    mime_type = Column(String(255), nullable=False)
    blob_path = Column(String(1000), nullable=False)  # Path in Azure Blob Storage
    file_size = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    flow = relationship("EmailFlow", back_populates="attachments")
    recipient_job = relationship("EmailRecipientJob", back_populates="per_row_attachments")


class CsvImport(Base):
    """Record of each CSV file upload with validation results."""
    __tablename__ = "csv_imports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    flow_id = Column(Integer, ForeignKey("email_flows.id", ondelete="CASCADE"), nullable=False)
    original_filename = Column(String(500), nullable=False)
    blob_path = Column(String(1000), nullable=False)
    row_count = Column(Integer, default=0)
    valid_rows = Column(Integer, default=0)
    error_rows = Column(Integer, default=0)
    validation_errors = Column(JSON, nullable=True)  # List of {row, field, error}
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    uploaded_by = Column(String(320), nullable=True)

    # Relationships
    flow = relationship("EmailFlow", back_populates="csv_imports")


class EmailRecipientJob(Base):
    """One queued email per CSV row, with merge fields and status tracking."""
    __tablename__ = "email_recipient_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    flow_id = Column(Integer, ForeignKey("email_flows.id", ondelete="CASCADE"), nullable=False)
    csv_import_id = Column(Integer, ForeignKey("csv_imports.id", ondelete="SET NULL"), nullable=True)
    to_email = Column(String(320), nullable=False)
    merge_fields = Column(JSON, nullable=True)  # {"FirstName": "John", "Company": "Acme", ...}
    attachment_refs = Column(JSON, nullable=True)  # Per-row attachment blob paths if applicable
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    flow = relationship("EmailFlow", back_populates="recipient_jobs")
    send_attempts = relationship("EmailSendAttempt", back_populates="recipient_job", cascade="all, delete-orphan")
    per_row_attachments = relationship("EmailFlowAttachment", back_populates="recipient_job")

    def __repr__(self):
        return f"<EmailRecipientJob id={self.id} to='{self.to_email}' status={self.status}>"


class EmailSendAttempt(Base):
    """Individual send attempt record for audit and troubleshooting."""
    __tablename__ = "email_send_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    recipient_job_id = Column(Integer, ForeignKey("email_recipient_jobs.id", ondelete="CASCADE"), nullable=False)
    operation_id = Column(String(255), nullable=True)  # ACS operation ID
    provider_status = Column(String(50), nullable=True)  # Running, Succeeded, Failed
    http_status_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    attempted_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    recipient_job = relationship("EmailRecipientJob", back_populates="send_attempts")
