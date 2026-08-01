"""Application settings, loaded from the environment.

Populated by docker-compose (see docker-compose.yml) in the container, and
falls back to local-dev defaults so `uvicorn main:app --reload` works against
a locally-running Postgres without extra setup.
"""

import ipaddress
import logging
import os
import secrets as _secrets
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Secrets that must never authenticate a real deployment: the repo ships these
# as dev conveniences, so they're *public knowledge*. Running on one would let
# anyone forge a JWT for any account (including Administrator). Treated as
# "unset" — a per-install secret is derived instead (see _resolve_jwt_secret).
_INSECURE_JWT_DEFAULTS = frozenset(
    {
        "",
        "dev-insecure-secret-change-me-in-production",
        "dev-insecure-secret-change-me-0000000000",
    }
)
# MinIO's vendor defaults. Same reasoning as the JWT secret above — these are
# public knowledge — but the remedy has to differ: a JWT secret can be derived
# per install, while these must match whatever the object-storage server was
# started with, so the app cannot invent them. It refuses to run on them
# instead, and only where it can tell that doing so would be exposed (see
# _assert_object_storage_credentials).
_INSECURE_MINIO_DEFAULTS = frozenset({"", "minioadmin"})


def _endpoint_host(value: str) -> str:
    """The bare hostname from ``host:port``, ``https://host/path`` or ``host``."""
    remainder = value.split("://", 1)[-1].split("/", 1)[0]
    if remainder.startswith("["):  # bracketed IPv6
        return remainder[1 : remainder.find("]")] if "]" in remainder else remainder
    return remainder.rsplit(":", 1)[0] if ":" in remainder else remainder


def _is_loopback(host: str) -> bool:
    host = host.strip().lower()
    if host in {"", "localhost"} or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# Persist a generated secret so tokens survive restarts without the operator
# having to set JWT_SECRET. Defaults next to the code (deterministic regardless
# of CWD); JWT_SECRET_FILE can point it at a mounted volume so the secret also
# survives a container being recreated (see docker-compose.yml).
_JWT_SECRET_FILE = Path(
    os.environ.get("JWT_SECRET_FILE") or (Path(__file__).resolve().parent / ".jwt_secret")
)


def _resolve_jwt_secret(configured: str) -> str:
    """Return a usable JWT secret, never a public default.

    An explicit, non-default ``JWT_SECRET`` wins. Otherwise derive a strong
    per-install secret and persist it — so a fresh dev/compose run works with
    zero config yet never signs tokens with a value that's public in the repo.
    Set ``JWT_SECRET`` explicitly for multi-host deployments (each replica would
    otherwise generate its own and reject each other's tokens).
    """
    if configured and configured not in _INSECURE_JWT_DEFAULTS:
        return configured
    log = logging.getLogger("startup")
    try:
        if _JWT_SECRET_FILE.exists():
            existing = _JWT_SECRET_FILE.read_text().strip()
            if existing:
                return existing
        generated = _secrets.token_urlsafe(64)
        _JWT_SECRET_FILE.write_text(generated)
        try:
            _JWT_SECRET_FILE.chmod(0o600)
        except OSError:
            pass
        log.warning(
            "JWT_SECRET not set — generated a persistent per-install secret at "
            "%s. Set JWT_SECRET explicitly for multi-host deployments.",
            _JWT_SECRET_FILE,
        )
        return generated
    except OSError:
        # Read-only filesystem: fall back to an ephemeral per-process secret.
        # Tokens won't survive a restart, but we still never use a public default.
        log.warning(
            "JWT_SECRET not set and %s is unwritable — using an ephemeral "
            "per-process secret; sessions won't survive a restart. Set "
            "JWT_SECRET to fix.",
            _JWT_SECRET_FILE,
        )
        return _secrets.token_urlsafe(64)


# The version a **source build** reports (#111). Release images override it via
# the APP_VERSION env var, baked from the git tag by release-images.yml.
#
# It means "the release this source tree is based on", not "this is that
# release" — `main` starts accumulating the next version's work the moment a tag
# is cut. Hence the `-src` marker, which is honest about that *and* keeps source
# builds distinguishable from release images in the adoption data. The suffix is
# ignored for version ordering, so update notices still fire correctly.
#
# **Bump this when tagging a release.** A tag-push check in release-images.yml
# fails the release if it disagrees with the tag, so a forgotten bump is a red
# build rather than months of quietly wrong data.
SOURCE_BUILD_VERSION = "1.2.0-src"


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

    # --- Public spectator page (#24) ---
    # TTL for the memoised public insights/timeline payload. The endpoint is
    # unauthenticated and can fan out to many spectators while the page polls
    # every 30s, so a short memo collapses them onto one computation. Set to 0
    # to disable (the tests do, so they can observe a mutation immediately).
    public_insights_cache_seconds: float = 15.0

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
    # An unset (or known public-default) secret is resolved to a strong
    # per-install secret at startup — the app never signs tokens with a value
    # that's public in the repo (see _resolve_jwt_secret). Set JWT_SECRET
    # explicitly in production, and always for multi-host deployments.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    # httpOnly refresh cookie is sent over http in local dev; set true in prod.
    refresh_cookie_secure: bool = False

    # --- Demo mode (for a public demo instance, e.g. demo.flagpost.io) ---
    # When true: a "resets hourly" banner shows app-wide, the login page lists
    # the shared demo credentials, outbound/abusable automation actions (webhooks,
    # email) are disabled, and demo accounts + sample data are seeded on startup.
    # The actual hourly reset is done externally (the operator recreates the
    # stack); this flag just makes the instance present + behave as a demo.
    # MUST stay false for any real deployment — it seeds well-known credentials.
    demo_mode: bool = False

    # The browser-facing origin this install is served on, e.g.
    # "https://ctf.example.com". Only needed for OIDC (#58): the redirect_uri
    # sent to an IdP must match the one registered there *exactly*, and it can't
    # be inferred reliably — behind a TLS-terminating proxy the backend sees a
    # plain-HTTP hop, so a request-derived URL would say "http://" and the IdP
    # would reject it. Deriving it from config sidesteps that without requiring
    # uvicorn --proxy-headers. Empty = fall back to the request (correct for a
    # direct HTTP dev run).
    public_base_url: str = ""

    # This deployment's version (#111) — see SOURCE_BUILD_VERSION above for what
    # the default means and when to bump it.
    #
    # An **empty** APP_VERSION falls back to the source default rather than being
    # taken literally. That's load-bearing: the Dockerfile always sets the env
    # var (there's no conditional ENV in a Dockerfile), so a source build would
    # otherwise report "" — or, as it did before this was fixed, whatever
    # literal the ARG defaulted to, silently shadowing the value below.
    app_version: str = SOURCE_BUILD_VERSION

    @field_validator("app_version", mode="before")
    @classmethod
    def _blank_app_version_means_source_build(cls, value: str | None) -> str:
        # Stripped first: a stray newline or space from a shell heredoc or a
        # quoted compose value is still "blank", and would otherwise be sent to
        # the update endpoint and bucketed as an unparseable version.
        return (str(value).strip() if value is not None else "") or SOURCE_BUILD_VERSION

    # Update check + anonymous adoption count (#111). One daily GET carrying
    # only `app_version`. Setting this to "" disables the feature outright, for
    # air-gapped installs that must never make an outbound call — a stronger
    # guarantee than the in-app toggle, which needs a running app to flip.
    update_check_url: str = "https://updates.flagpost.io/v1/check"

    # OIDC (#58, ADR-0021). Issuers must normally be public https endpoints —
    # the SSRF guard that enforces that also, correctly, blocks `localhost`,
    # which makes a local mock IdP unusable. This opt-out exists so the feature
    # can be exercised on a dev box; it disables BOTH the https requirement and
    # the non-routable-address blocklist for issuer/token/JWKS fetches, so
    # enabling it in production reopens exactly the SSRF hole ADR-0013 closed.
    # Off by default and logged loudly whenever it takes effect.
    oidc_allow_insecure_issuers: bool = False

    @model_validator(mode="after")
    def _harden_jwt_secret(self) -> "Settings":
        # Replace an unset / public-default secret with a real per-install one,
        # so no deployment ever runs on a forgeable auth root of trust.
        self.jwt_secret = _resolve_jwt_secret(self.jwt_secret)
        return self

    @model_validator(mode="after")
    def _assert_object_storage_credentials(self) -> "Settings":
        """Refuse to serve a real deployment on MinIO's published defaults.

        The compose stack publishes the S3 API on the host — it has to, because
        the browser fetches attachments straight from it via signed URLs — so
        ``minioadmin``/``minioadmin`` there means anyone who can reach the box
        has read/write on every challenge attachment and ticket screenshot, for
        every competition, entirely outside RBAC. On a CTF platform that is the
        competition itself: unreleased challenge binaries leak, or get replaced.

        Two independent signals, because either alone has a blind spot:

        - ``public_base_url`` — the variable an operator sets to deploy (README
          → "Deploying to production"). Empty for a native run, ``localhost``
          for the default compose, so local workflows are untouched. Misses the
          operator who sets only ``SITE_ADDRESS``.
        - ``minio_public_endpoint`` — set precisely when browsers must reach the
          object store over the network, which is a direct statement that it is
          exposed. Catches the case above, since remote attachment downloads do
          not work without it.

        Deliberately *not* inferred from the compose port mapping, which the app
        cannot see. An install serving from ``minio:9000`` on the compose network
        with no published port is safe and unaffected — that is how the demo
        stack runs.

        A hard failure rather than a warning: a warning scrolls past, and the
        window between "operator deploys" and "someone finds an open MinIO" is
        not one a log line closes.
        """
        if not (
            self.minio_access_key in _INSECURE_MINIO_DEFAULTS
            or self.minio_secret_key in _INSECURE_MINIO_DEFAULTS
        ):
            return self

        exposed_by = None
        if not _is_loopback(_endpoint_host(self.public_base_url)):
            exposed_by = f"PUBLIC_BASE_URL={self.public_base_url!r}"
        elif self.minio_public_endpoint and not _is_loopback(
            _endpoint_host(self.minio_public_endpoint)
        ):
            exposed_by = f"MINIO_PUBLIC_ENDPOINT={self.minio_public_endpoint!r}"

        if exposed_by is not None:
            raise ValueError(
                "Refusing to start: object storage is using MinIO's default "
                f"credentials on a deployment that is reachable ({exposed_by}). "
                "These are published defaults, not secrets — anyone who can "
                "reach the S3 API would have full read/write on every challenge "
                "attachment, including unreleased ones, outside RBAC entirely. "
                "Set MINIO_ROOT_USER and MINIO_ROOT_PASSWORD (compose passes "
                "them to both MinIO and the backend) to values from e.g. "
                "`openssl rand -hex 24`, then recreate the minio service."
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
