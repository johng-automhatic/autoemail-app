"""Azure Communication Services Email sender."""

import base64
import logging
from typing import Optional

from azure.communication.email import EmailClient
from azure.communication.email.aio import EmailClient as AsyncEmailClient

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmailSenderService:
    """Send emails through Azure Communication Services."""

    def __init__(self):
        settings = get_settings()
        self._conn_str = settings.acs_connection_string

    def _get_client(self) -> EmailClient:
        """Get a synchronous ACS Email client."""
        return EmailClient.from_connection_string(self._conn_str)

    async def send_email(
        self,
        from_email: str,
        to_email: str,
        subject: str,
        body_html: str,
        attachments: Optional[list[dict]] = None,
    ) -> dict:
        """Send a single email via ACS.

        Args:
            from_email: Verified sender address (e.g., do-not-reply@yourdomain.com)
            to_email: Recipient email address
            subject: Email subject line
            body_html: HTML body content
            attachments: List of dicts with keys: name, content_type, content_bytes

        Returns:
            dict with 'operation_id', 'status', and optionally 'error'
        """
        message = {
            "senderAddress": from_email,
            "recipients": {
                "to": [{"address": to_email}],
            },
            "content": {
                "subject": subject,
                "html": body_html,
            },
        }

        # Add attachments if present
        if attachments:
            message["attachments"] = []
            for att in attachments:
                message["attachments"].append({
                    "name": att["name"],
                    "contentType": att["content_type"],
                    "contentInBase64": base64.b64encode(att["content_bytes"]).decode("ascii"),
                })

        try:
            client = self._get_client()
            poller = client.begin_send(message)
            result = poller.result()

            operation_id = result.get("id", "")
            send_status = result.get("status", "Unknown")
            error = result.get("error", None)

            logger.info(
                "Email sent to=%s operation_id=%s status=%s",
                to_email, operation_id, send_status,
            )

            return {
                "operation_id": operation_id,
                "status": send_status,
                "error": str(error) if error else None,
            }

        except Exception as e:
            logger.error("Failed to send email to %s: %s", to_email, str(e))
            return {
                "operation_id": None,
                "status": "Failed",
                "error": str(e),
            }


def render_template(body_html: str, merge_fields: dict) -> str:
    """Replace {{field_name}} placeholders in the HTML template with merge field values.

    Example:
        body_html = "<p>Hello {{first_name}} from {{company}}!</p>"
        merge_fields = {"first_name": "John", "company": "Acme Corp"}
        result = "<p>Hello John from Acme Corp!</p>"
    """
    result = body_html
    if merge_fields:
        for key, value in merge_fields.items():
            placeholder = "{{" + key + "}}"
            result = result.replace(placeholder, str(value) if value else "")
    return result


def get_email_sender() -> EmailSenderService:
    return EmailSenderService()
