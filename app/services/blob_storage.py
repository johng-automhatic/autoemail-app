"""Azure Blob Storage service for CSV uploads and email attachments."""

import logging
import uuid
from datetime import datetime, timezone
from typing import BinaryIO

from azure.storage.blob.aio import BlobServiceClient

from app.config import get_settings

logger = logging.getLogger(__name__)


class BlobStorageService:
    """Handles upload/download of CSVs and attachments to Azure Blob Storage."""

    def __init__(self):
        settings = get_settings()
        self._conn_str = settings.azure_storage_connection_string
        self._csv_container = settings.blob_container_csv
        self._attachments_container = settings.blob_container_attachments

    async def _get_client(self) -> BlobServiceClient:
        return BlobServiceClient.from_connection_string(self._conn_str)

    async def upload_csv(self, file_content: bytes, original_filename: str, flow_id: int) -> str:
        """Upload a CSV file and return its blob path."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        blob_name = f"flow-{flow_id}/{timestamp}_{original_filename}"

        async with await self._get_client() as client:
            container = client.get_container_client(self._csv_container)
            # Ensure container exists
            try:
                await container.create_container()
            except Exception:
                pass  # Already exists

            blob = container.get_blob_client(blob_name)
            await blob.upload_blob(file_content, overwrite=True)

        logger.info("Uploaded CSV: %s", blob_name)
        return blob_name

    async def upload_attachment(
        self, file_content: bytes, filename: str, flow_id: int, mime_type: str
    ) -> str:
        """Upload an attachment file and return its blob path."""
        ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
        unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        blob_name = f"flow-{flow_id}/attachments/{unique_name}"

        async with await self._get_client() as client:
            container = client.get_container_client(self._attachments_container)
            try:
                await container.create_container()
            except Exception:
                pass

            blob = container.get_blob_client(blob_name)
            await blob.upload_blob(
                file_content,
                overwrite=True,
                content_settings={"content_type": mime_type},
            )

        logger.info("Uploaded attachment: %s", blob_name)
        return blob_name

    async def download_blob(self, container_name: str, blob_name: str) -> bytes:
        """Download a blob and return its bytes."""
        async with await self._get_client() as client:
            container = client.get_container_client(container_name)
            blob = container.get_blob_client(blob_name)
            stream = await blob.download_blob()
            return await stream.readall()

    async def delete_blob(self, container_name: str, blob_name: str) -> None:
        """Delete a blob."""
        async with await self._get_client() as client:
            container = client.get_container_client(container_name)
            blob = container.get_blob_client(blob_name)
            await blob.delete_blob()
            logger.info("Deleted blob: %s/%s", container_name, blob_name)


def get_blob_service() -> BlobStorageService:
    return BlobStorageService()
