from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: str = "development"
    database_url: str = "sqlite:///./data/diu_monitor.db"
    public_base_url: str = "http://localhost:8000"
    qr_base_url: str = ""
    session_secret: str = "development-only-change-me-please"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_allowed_domains: str = ""
    bootstrap_admin_email: str = ""
    # Backward-compatible local-development input. Never used in production.
    diu_teacher_email: str = ""
    dev_auth_enabled: bool = False
    source_access_token: str = ""
    source_project_id: str = "diu-campus-schedule-cc857"
    cookie_secure: bool = True

    @field_validator("dev_auth_enabled")
    @classmethod
    def no_dev_auth_in_production(cls, value, info):
        if value and info.data.get("environment") == "production":
            raise ValueError("DEV_AUTH_ENABLED is forbidden in production")
        return value

    @property
    def domains(self):
        return {x.strip().lower() for x in self.google_allowed_domains.split(",") if x.strip()}

    @property
    def effective_bootstrap_admin_email(self):
        if self.bootstrap_admin_email.strip():
            return self.bootstrap_admin_email.strip().lower()
        if self.environment == "development":
            return self.diu_teacher_email.strip().lower()
        return ""

    @property
    def effective_qr_base_url(self):
        return (self.qr_base_url or self.public_base_url).rstrip("/")

@lru_cache
def get_settings():
    return Settings()
