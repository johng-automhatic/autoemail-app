"""CSV import, validation, and recipient job expansion."""

import csv
import io
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import CsvImport, EmailRecipientJob, EmailFlow, JobStatus

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"to_email"}
OPTIONAL_COLUMNS = {"first_name", "last_name", "company", "attachment_ref"}
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


@dataclass
class ValidationResult:
    """Result of CSV validation."""
    is_valid: bool = True
    row_count: int = 0
    valid_rows: int = 0
    error_rows: int = 0
    errors: list[dict] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)


def validate_csv(file_content: bytes) -> ValidationResult:
    """Parse and validate a CSV file.

    Required columns: to_email
    All other columns become merge fields available in the email template.
    """
    result = ValidationResult()

    try:
        text = file_content.decode("utf-8-sig")  # Handle BOM
    except UnicodeDecodeError:
        try:
            text = file_content.decode("latin-1")
        except UnicodeDecodeError:
            result.is_valid = False
            result.errors.append({"row": 0, "field": "file", "error": "Cannot decode file. Use UTF-8 encoding."})
            return result

    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        result.is_valid = False
        result.errors.append({"row": 0, "field": "file", "error": "CSV file is empty or has no headers."})
        return result

    # Normalize headers to lowercase
    headers = [h.strip().lower().replace(" ", "_") for h in reader.fieldnames]
    result.headers = headers

    # Check required columns
    if "to_email" not in headers:
        # Also accept 'toemail' or 'email' as the recipient column
        email_col = None
        for candidate in ["toemail", "email", "recipient_email", "recipient"]:
            if candidate in headers:
                email_col = candidate
                break
        if not email_col:
            result.is_valid = False
            result.errors.append({
                "row": 0,
                "field": "headers",
                "error": f"Missing required column 'to_email'. Found: {', '.join(headers)}"
            })
            return result
    else:
        email_col = "to_email"

    # Validate each row
    for row_num, raw_row in enumerate(reader, start=2):
        result.row_count += 1
        # Normalize row keys
        row = {k.strip().lower().replace(" ", "_"): (v.strip() if v else "") for k, v in raw_row.items()}

        email = row.get(email_col, "").strip()
        row_errors = []

        if not email:
            row_errors.append({"row": row_num, "field": "to_email", "error": "Email address is blank"})
        elif not EMAIL_REGEX.match(email):
            row_errors.append({"row": row_num, "field": "to_email", "error": f"Invalid email: {email}"})

        if row_errors:
            result.error_rows += 1
            result.errors.extend(row_errors)
        else:
            result.valid_rows += 1
            # Normalize: ensure to_email key is present
            normalized = dict(row)
            if email_col != "to_email":
                normalized["to_email"] = normalized.pop(email_col, email)
            result.rows.append(normalized)

    if result.row_count == 0:
        result.is_valid = False
        result.errors.append({"row": 0, "field": "file", "error": "CSV has headers but no data rows."})

    if result.valid_rows == 0 and result.row_count > 0:
        result.is_valid = False

    return result


async def expand_csv_to_jobs(
    db: AsyncSession,
    flow: EmailFlow,
    csv_import: CsvImport,
    validated_rows: list[dict],
) -> int:
    """Create EmailRecipientJob records from validated CSV rows.

    Returns the count of jobs created.
    """
    jobs_created = 0

    for row in validated_rows:
        to_email = row.pop("to_email")
        attachment_ref = row.pop("attachment_ref", None)

        job = EmailRecipientJob(
            flow_id=flow.id,
            csv_import_id=csv_import.id,
            to_email=to_email,
            merge_fields=row if row else None,  # Everything else becomes merge fields
            attachment_refs=[attachment_ref] if attachment_ref else None,
            status=JobStatus.PENDING,
            scheduled_at=flow.send_at,
        )
        db.add(job)
        jobs_created += 1

    await db.flush()
    logger.info("Created %d recipient jobs for flow %d", jobs_created, flow.id)
    return jobs_created
