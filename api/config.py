"""Runtime settings. Fails loudly rather than starting with an unsafe default."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EXAMPLE_SECRET = "dev-only-not-a-real-secret-32-bytes-minimum-xx"
MIN_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://orbit:orbitpw@127.0.0.1:55432/orbit"
    session_secret: str = ""
    artifact_root: str = "./experiments/results"
    log_level: str = "INFO"
    env: str = "development"
    cors_origins: str = ""
    max_concurrent_runs: int = 2

    session_idle_seconds: int = 2 * 60 * 60
    session_absolute_seconds: int = 12 * 60 * 60

    @field_validator("session_secret")
    @classmethod
    def _secret_must_be_real(cls, value: str, info: object) -> str:
        return value

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    def require_usable_secret(self) -> None:
        if len(self.session_secret) < MIN_SECRET_BYTES:
            raise RuntimeError(
                f"SESSION_SECRET must be at least {MIN_SECRET_BYTES} bytes; refusing to start"
            )
        if self.is_production and self.session_secret == EXAMPLE_SECRET:
            raise RuntimeError("SESSION_SECRET is the example value; refusing to start")


@lru_cache
def get_settings() -> Settings:
    return Settings()
