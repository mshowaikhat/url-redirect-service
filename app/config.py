"""Application configuration, loaded from environment variables (Factor 3)."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All config for the redirect service. Read once at startup."""

    gcp_project_id: str = Field(..., alias="GCP_PROJECT_ID")
    firestore_collection: str = Field("urls", alias="FIRESTORE_COLLECTION")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    port: int = Field(8080, alias="PORT")
    otel_service_name: str = Field("redirect", alias="OTEL_SERVICE_NAME")

    # Firestore emulator: auto-detected by the client when this var is set
    firestore_emulator_host: str | None = Field(
        None, alias="FIRESTORE_EMULATOR_HOST"
    )

    # Redis cache (Memorystore in prod, redis:7-alpine in docker-compose).
    # When redis_host is unset the cache is disabled and every lookup goes
    # straight to Firestore -- useful for local dev without docker.
    redis_host: str | None = Field(None, alias="REDIS_HOST")
    redis_port: int = Field(6379, alias="REDIS_PORT")
    redis_auth: str | None = Field(None, alias="REDIS_AUTH")
    cache_ttl_seconds: int = Field(3600, alias="CACHE_TTL_SECONDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
