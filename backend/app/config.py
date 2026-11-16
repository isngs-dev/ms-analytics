from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor to this project's own .env, never the current working directory: running from another
# repo's folder must not pick up that repo's .env. (Missing file is fine, e.g. inside Docker.)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

_DEFAULT_DB = "postgresql+psycopg://ms:change-me@localhost:5434/ms_analytics"
_DEV_SECRET = "dev-only-change-me-dev-only-change-me"  # 37 bytes; production must override


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    environment: str = "development"  # development | production
    database_url: str = _DEFAULT_DB
    jwt_secret: str = _DEV_SECRET
    jwt_expire_minutes: int = 480
    cookie_secure: bool = False  # set true behind HTTPS
    cors_origins: str = "http://localhost:3000"  # comma separated
    demo_user_password: str = ""  # used only by `python -m app.seed.users`

    google_service_account_file: str = "/secrets/service-account.json"
    google_oauth_token_file: str = "/secrets/oauth-token.json"  # created by scripts/drive_login.py
    google_api_key: str = ""  # fallback: only reads items shared "Anyone with the link"
    drive_root_folder_id: str = ""
    drive_root_resource_key: str = ""  # the ?resourcekey=... part of old-style shared links
    data_source: str = "mock"  # "mock" | "drive"

    sync_interval_minutes: int = 10  # polling Drive is cheap: only files whose modifiedTime changed are re-read
    scheduler_enabled: bool = False

    @field_validator("database_url")
    @classmethod
    def _driver(cls, v: str) -> str:
        """Hosting platforms (Render, Heroku ...) hand out `postgres://` / `postgresql://` URLs: use the psycopg 3 driver."""
        for plain in ("postgres://", "postgresql://"):
            if v.startswith(plain):
                return "postgresql+psycopg://" + v[len(plain):]
        return v

    def assert_safe(self) -> None:
        if self.environment == "production" and self.jwt_secret == _DEV_SECRET:
            raise RuntimeError("JWT_SECRET must be set in production")
        if self.environment == "production" and self.database_url == _DEFAULT_DB:
            raise RuntimeError("DATABASE_URL is not set on this service: add it under Environment "
                               "(on Render: the Internal Database URL of the database)")


settings = Settings()
