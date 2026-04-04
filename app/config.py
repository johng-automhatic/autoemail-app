"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://localhost:5432/emailflowdb"

    # Entra ID / Auth
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    app_redirect_uri: str = "http://localhost:8000/auth/callback"

    # Azure Communication Services
    acs_connection_string: str = ""
    acs_endpoint: str = ""  # Alternative: use with managed identity

    # Azure Blob Storage
    azure_storage_connection_string: str = ""
    blob_container_csv: str = "csv-uploads"
    blob_container_attachments: str = "email-attachments"

    # App
    secret_key: str = "change-me-in-production"
    app_name: str = "Email Flow Manager"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.azure_tenant_id}"

    @property
    def scopes(self) -> list[str]:
        return [f"api://{self.azure_client_id}/.default"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
