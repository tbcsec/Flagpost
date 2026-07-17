"""Application settings, loaded from the environment.

Populated by docker-compose (see docker-compose.yml) in the container, and
falls back to local-dev defaults so `uvicorn main:app --reload` works against
a locally-running Postgres without extra setup.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Comma-separated list of allowed browser origins for CORS.
    cors_origins: str = "http://localhost:3000"

    # Async SQLAlchemy URL. Overridden by docker-compose; this default targets
    # a Postgres reachable on localhost for native `uvicorn` runs.
    database_url: str = "postgresql+asyncpg://ctf:ctf@localhost:5432/ctf"

    # Provisioned by docker-compose ahead of the code that uses them (Tier 1+).
    redis_url: str | None = None
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None

    # --- Auth (ARCHITECTURE.md §7.7, ADR-0003) ---
    # Dev default only; MUST be overridden in any real deployment.
    jwt_secret: str = "dev-insecure-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    # httpOnly refresh cookie is sent over http in local dev; set true in prod.
    refresh_cookie_secure: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
