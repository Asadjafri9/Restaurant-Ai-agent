import logging
import secrets
from functools import lru_cache
from typing import Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # WhatsApp
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_api_version: str = "v25.0"

    # AI
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    ai_fallback_message: str = (
        "Sorry, I am unable to respond right now.\nPlease try again later."
    )

    # Infrastructure
    database_url_central: str = ""
    database_url_tenant: str = ""
    redis_url: str = ""

    # Service topology: agent | admin | kfc | kababjees | all
    service_mode: str = "all"
    tenant_slug: str = ""
    tenant_id: str = ""

    # Auth
    jwt_secret: str = ""
    jwt_alg: str = "HS256"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7

    # Encryption
    fernet_key: str = ""
    phone_hash_pepper: str = ""

    # CORS
    allowed_origins: str = "http://localhost:5173,http://localhost:3000"

    # Tenant provisioning
    tenant_db_host: str = ""
    tenant_db_port: int = 5432
    tenant_db_admin_url: str = ""

    environment: str = "development"
    webhook_signature_required: bool = True

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def resolve_gemini_api_key(cls, v: str) -> str:
        import os

        return v or os.getenv("GOOGLE_API_KEY", "")

    @field_validator("database_url_central", mode="before")
    @classmethod
    def resolve_database_url(cls, v: str) -> str:
        import os

        return v or os.getenv("DATABASE_URL", "")

    @field_validator("database_url_tenant", mode="before")
    @classmethod
    def resolve_tenant_database_url(cls, v: str) -> str:
        import os

        return v or os.getenv("TENANT_DATABASE_URL", "") or os.getenv("DATABASE_URL", "")

    @field_validator("tenant_db_port", mode="before")
    @classmethod
    def coerce_tenant_db_port(cls, v: object) -> object:
        if v is None or v == "":
            return 5432
        return v

    @model_validator(mode="after")
    def defaults(self) -> Self:
        if not self.jwt_secret:
            self.jwt_secret = secrets.token_hex(32)
        if not self.phone_hash_pepper:
            self.phone_hash_pepper = secrets.token_hex(16)
        if not self.fernet_key and self.environment == "development":
            from cryptography.fernet import Fernet

            self.fernet_key = Fernet.generate_key().decode()
        if self.database_url_central and not self.tenant_db_host:
            from urllib.parse import urlparse

            parsed = urlparse(self.database_url_central.replace("postgresql+asyncpg://", "postgresql://"))
            self.tenant_db_host = parsed.hostname or ""
            self.tenant_db_port = parsed.port or 5432
        if self.database_url_central and not self.tenant_db_admin_url:
            self.tenant_db_admin_url = self.database_url_central.replace(
                "postgresql+asyncpg://", "postgresql://"
            )
        if self.service_mode in ("kfc", "kababjees") and not self.tenant_slug:
            self.tenant_slug = self.service_mode
        if self.service_mode in ("kfc", "kababjees") and not self.tenant_id:
            from app.core.tenant_ids import TENANT_IDS

            self.tenant_id = str(TENANT_IDS[self.service_mode])
        return self

    @property
    def is_agent_service(self) -> bool:
        return self.service_mode in ("agent", "all")

    @property
    def is_admin_service(self) -> bool:
        return self.service_mode in ("admin", "all")

    @property
    def is_tenant_service(self) -> bool:
        return self.service_mode in ("kfc", "kababjees", "all")

    @property
    def is_standalone_tenant(self) -> bool:
        return self.service_mode in ("kfc", "kababjees")

    @property
    def async_database_url_tenant(self) -> str:
        url = self.database_url_tenant
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def async_database_url_central(self) -> str:
        url = self.database_url_central
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
