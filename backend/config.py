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
    database_url: str = "postgresql+asyncpg://flagpost:flagpost@localhost:5432/flagpost"

    redis_url: str | None = None

    # --- Flag submission rate limit (§13.2) ---
    # Per-subject (user or team) sliding window on the submit endpoint — tight
    # enough to blunt a guessing script, loose enough not to slow a human typing
    # a real answer.
    submission_rate_limit: int = 10
    submission_rate_window_seconds: int = 30

    # --- Real-time layer (§4.1) ---
    # How long a fresh WebSocket connection has to send its first-frame auth
    # message before the server closes it (the token is never in the URL,
    # ADR-0003).
    ws_auth_timeout_seconds: float = 5.0
    # Grace period before a departed presence member is cleared from a room's
    # "who's here" set (§4.1 "debounced presence clearing"): a brief reconnect
    # inside this window doesn't flicker the presence list.
    ws_presence_grace_seconds: float = 5.0

    # --- Outbound email (§5.3 send_email action) ---
    # Unset host = email delivery disabled (the action logs and no-ops). Email
    # is only an automation action target for now, not a notification channel
    # of its own (§4.4).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "flagpost@localhost"
    smtp_starttls: bool = True

    # --- Automation engine (§5.2) ---
    # Cascade-depth cap: a rule's actions emit events that may trigger further
    # rules; evaluation stops past this depth (basic runaway-loop guard — the
    # fuller detection scheme stays open in §15).
    automation_max_depth: int = 3
    # How often the time-trigger scheduler ticks (competition.time_remaining,
    # §5.2). A minute is plenty for "N minutes before end" rules.
    automation_scheduler_interval_seconds: float = 60.0

    # --- Object storage (MinIO / S3, §13.3) ---
    # Endpoint the backend talks to. Defaults to the compose MinIO as exposed on
    # the host, so a native `uvicorn` run works against `docker compose up minio`.
    minio_endpoint: str = "localhost:9000"
    # Endpoint used when *signing* download URLs, i.e. the host the browser can
    # reach. Falls back to minio_endpoint. In full-docker the backend talks to
    # `minio:9000` but must sign against `localhost:9000` — compose sets this.
    minio_public_endpoint: str | None = None
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "challenge-files"
    minio_secure: bool = False  # http in dev; true behind TLS in prod
    # Lifetime of a signed download URL, in seconds (§13.3 — short-lived).
    signed_url_ttl_seconds: int = 300

    # --- Auth (ARCHITECTURE.md §7.7, ADR-0003) ---
    # Dev default only; MUST be overridden in any real deployment. Kept ≥32
    # bytes so HS256 doesn't emit an insecure-key-length warning in local runs.
    jwt_secret: str = "dev-insecure-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    # httpOnly refresh cookie is sent over http in local dev; set true in prod.
    refresh_cookie_secure: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
