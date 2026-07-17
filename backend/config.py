"""Application settings, loaded from the environment.

Skeleton scope: only what the hello-world app needs (CORS). The infra
connection strings (DATABASE_URL, REDIS_URL, MinIO creds) are already passed
in by docker-compose so the Tier 0 features can read them here without
touching the wiring — they're declared optional and simply unused for now.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Comma-separated list of allowed browser origins for CORS.
    cors_origins: str = "http://localhost:3000"

    # Provisioned by docker-compose ahead of the code that uses them.
    database_url: str | None = None
    redis_url: str | None = None
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
