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
SOURCE_BUILD_VERSION = "1.6.0-src"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Comma-separated list of allowed browser origins for CORS.
    cors_origins: str = "http://localhost:3000"

    # Async SQLAlchemy URL. Overridden by docker-compose; this default targets
    # a Postgres reachable on localhost for native `uvicorn` runs.
    database_url: str = "postgresql+asyncpg://flagpost:flagpost@localhost:5432/flagpost"

    # Connection-pool sizing for the Postgres engine (#174). SQLAlchemy's stock
    # defaults (pool_size 5 + max_overflow 10 = 15 checkouts) are the concurrency
    # ceiling under a live event: a 200-user load test pinned the pool at 15
    # while the backend sat well under half its CPU — concurrency-bound, not
    # CPU-bound. These raise the ceiling. Keep pool_size + max_overflow comfortably
    # under Postgres' server-side max_connections (default 100) so the pool can't
    # oversubscribe the database — the single backend process (ADR-0005) is the
    # only pool. 30 + 30 = 60 total leaves headroom while giving the read-fan-out
    # more room: the post-fix re-run touched the previous 40 cap (peaked at 41),
    # so this is cheap insurance ahead of #87 stage 2 reducing that load at source.
    db_pool_size: int = 30
    db_max_overflow: int = 30
    # Seconds a request waits for a free connection before erroring, rather than
    # blocking forever, so pool exhaustion surfaces as a fast 500 not a hang.
    db_pool_timeout: int = 30
    # Total steady pool connections to share across workers when multi-worker
    # (#189 Phase 3). The per-process engine pool is per-worker, so N workers ×
    # a fixed 30 would blow past Postgres max_connections; instead each worker
    # gets budget // workers. Single-worker ignores this and uses db_pool_size
    # unchanged. Keep it ≤ Postgres max_connections minus overflow + headroom.
    db_connection_budget: int = 100

    redis_url: str | None = None
    # Bounded client-side Redis pool (#189 interim hardening). redis.asyncio's
    # default ConnectionPool is effectively uncapped and, under the 500-user
    # load test's concurrent churn, raced into "IndexError: pop from empty
    # list" (150 × HTTP 500). A BlockingConnectionPool with an explicit cap
    # queues instead — the same "size the pool on purpose" move #187 made for
    # Postgres. The acquire timeout bounds how long a request waits for a free
    # connection so exhaustion degrades to added latency, not a hang.
    redis_max_connections: int = 50
    redis_acquire_timeout_seconds: float = 10.0
    # Number of uvicorn worker processes (reads the conventional WEB_CONCURRENCY
    # env var). 1 = single process: in-process broadcast, no Redis required —
    # today's behaviour and the dev/test/single-box default. >1 activates the
    # cross-worker broadcast relay (#189, ADR-0025) and REQUIRES redis_url; the
    # startup guard refuses to boot otherwise, so a misconfigured multi-worker
    # deployment fails loudly instead of silently dropping broadcasts to
    # (N-1)/N of clients. Phase 3 computes a core-aware default in the
    # production image; it stays 1 here so nothing changes until then.
    web_concurrency: int = 1
    # This backend runs as more than one app *instance* — containers/hosts
    # behind a load balancer (ADR-0031, e.g. ECS/Fargate + ALB) — as opposed to
    # multiple workers inside one container, which web_concurrency covers.
    # Forces the cross-process realtime layer (Redis broadcast relay + shared
    # presence, ADR-0025/0026) on regardless of the local worker count: without
    # it, N single-worker tasks would each think they're the whole deployment
    # and silently stop relaying broadcasts to each other's clients. Requires
    # redis_url (enforced at startup); redundant-but-harmless when
    # web_concurrency > 1 already.
    multi_instance: bool = False
    # Password hashing (#207). argon2 parallelism=1 (one lane per hash) is the
    # OWASP-recommended server config — throughput comes from hashing many
    # logins *concurrently*, not from splitting one hash across cores. The
    # pwdlib default (p=4) can't avoid oversubscribing a box where cores≈workers
    # during a login storm (N workers × p lanes). Memory (64 MiB) and time (3)
    # are kept at pwdlib's recommended values, well above OWASP's minimums, so
    # this is not a weakening; existing p=4 hashes still verify (params are read
    # from the stored hash). Concurrent hashes are bounded by a shared executor
    # sized cores//web_concurrency, so N workers total ≈ cores worth of hashing.
    argon2_parallelism: int = 1
    argon2_memory_cost: int = 65536  # KiB (64 MiB) — pwdlib recommended
    argon2_time_cost: int = 3        # iterations — pwdlib recommended

    # --- Flag submission rate limit (§13.2) ---
    # Per-subject (user or team) sliding window on the submit endpoint — tight
    # enough to blunt a guessing script, loose enough not to slow a human typing
    # a real answer.
    submission_rate_limit: int = 10
    submission_rate_window_seconds: int = 30

    # Server-side coalescing window for the per-competition activity room (#175).
    # A burst of same-event pings (mass solves) within this window collapses to
    # one leading + one trailing broadcast; a lone event still fires instantly.
    # Each broadcast is an N-client refetch, so this caps burst width without
    # adding latency to steady, well-spaced events.
    activity_coalesce_window_seconds: float = 0.5

    # TTL backstop for the cached scoreboard read model (#87 stage 1). The cache
    # is cleared on every scoreboard-moving event, so a hit only serves an
    # unchanged board; this bounds staleness for the rare change that emits no
    # such event (a new participant joining) to a few seconds.
    scoreboard_cache_ttl_seconds: float = 5.0

    # Hard cap on request body size, enforced by an ASGI middleware before route
    # auth runs — otherwise an oversized body (e.g. to /site-settings/import) is
    # buffered + JSON-decoded before the 401/403, amplifying into transient heap
    # (an unauthenticated memory-DoS, #3). Generous by default so it clears the
    # 50 MB file/import routes and typical backups; raise it for very large
    # backup restores. Bytes.
    max_request_body_bytes: int = 100 * 1024 * 1024

    # --- Unauthenticated credential endpoints ---
    # Login, registration, password reset and email verification. Without this
    # there is no throttle and no lockout anywhere in the auth path: a breach
    # corpus can be replayed at full concurrency, and forgot-password is an
    # unmetered mail cannon aimed at any address the caller names.
    #
    # Keyed on the *identifier* (or email), not the client IP, because nothing
    # in the stack derives a trustworthy client address — uvicorn runs without
    # --proxy-headers, so the peer is Caddy for every request. That means this
    # blunts a targeted attack on one account but not spraying one password
    # across many; closing that needs trusted proxy headers first, and keying on
    # a forgeable header would be worse than not keying at all.
    #
    # Windows are generous enough that a human who mistypes a password twice
    # never notices.
    auth_rate_limit: int = 10
    auth_rate_window_seconds: int = 300
    # Tighter, because each one sends mail to an address the caller chose.
    auth_email_rate_limit: int = 3
    auth_email_rate_window_seconds: int = 900

    # --- Public spectator page (#24) ---
    # TTL for the memoised public insights/timeline payload. The endpoint is
    # unauthenticated and can fan out to many spectators while the page polls
    # every 30s, so a short memo collapses them onto one computation. Set to 0
    # to disable (the tests do, so they can observe a mutation immediately).
    public_insights_cache_seconds: float = 15.0
    # TTL for the memoised recent-solves feed that drives venue mode's
    # first-blood splash (#77). Shorter than the insights memo because venue
    # mode polls it faster (a splash should land within a few seconds of the
    # solve); still enough to collapse concurrent spectators onto one query.
    # 0 disables it (the tests do).
    public_activity_cache_seconds: float = 5.0
    # TTL for the cross-competition skills web (#364, ADR-0039). It scans every
    # competition, so it can't key the cache by competition_id (unlike the
    # boards) and drops wholesale on any solve — this TTL bounds the recompute for
    # read-heavy pages. 0 disables it (the tests do, to observe a solve at once).
    skills_cache_seconds: float = 30.0

    # --- Real-time layer (§4.1) ---
    # How long a fresh WebSocket connection has to send its first-frame auth
    # message before the server closes it (the token is never in the URL,
    # ADR-0003).
    ws_auth_timeout_seconds: float = 5.0
    # Per-user rate limit on the WS handshake (#178). The /ws endpoint was the
    # one authenticated surface with no throttle: an abusive client could loop
    # reconnects, each forcing a token decode + DB lookup + room authorize (+ a
    # scoreboard snapshot recompute). Keyed on the token subject, not the IP —
    # behind the single-origin Caddy proxy (uvicorn runs without --proxy-headers)
    # every client shares the proxy's IP, so a per-IP bucket would throttle the
    # whole event as one. Generous enough for a real client opening its handful
    # of shell + challenge-presence sockets on load (and re-opening them after a
    # reconnect); tight enough to stop a hammering loop.
    ws_handshake_rate_limit: int = 60
    ws_handshake_rate_window_seconds: int = 30
    # Per-socket send timeout for a room broadcast (#177). A slow/stalled client
    # (full TCP send buffer) must not hold up delivery to the rest of the room:
    # the send is bounded by this timeout, and a socket that exceeds it is
    # treated as gone and reaped, exactly like a send that errors.
    ws_send_timeout_seconds: float = 5.0
    # Grace period before a departed presence member is cleared from a room's
    # "who's here" set (§4.1 "debounced presence clearing"): a brief reconnect
    # inside this window doesn't flicker the presence list.
    ws_presence_grace_seconds: float = 5.0
    # Multi-worker presence (#189 Phase 2, ADR-0026). A worker refreshes the
    # shared-store liveness of its members every heartbeat; an entry lives for
    # ttl. ttl must exceed heartbeat + grace so a live-but-idle member never
    # expires between refreshes (30 > 10 + 5). Only used when multi-worker
    # (web_concurrency > 1); single-worker presence is purely in-process.
    ws_presence_ttl_seconds: float = 30.0
    ws_presence_heartbeat_seconds: float = 10.0

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
    # Whether THIS process/container may run the singleton background scheduler
    # (time triggers, report + certificate-export jobs, retention purge, update
    # check). True preserves every existing topology: in-process when
    # single-worker, entrypoint sidecar when multi-worker. Set false on the web
    # tasks of a multi-instance deployment (ADR-0031), where one dedicated
    # `python -m scheduler` service is THE scheduler — job pickup has no
    # cross-process claim locking, so N schedulers double-fire webhooks and
    # render jobs twice. `python -m scheduler` itself deliberately ignores this
    # flag: running it is the explicit opt-in.
    scheduler_enabled: bool = True

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
    # Authenticate to object storage with AWS IAM role credentials (ECS task
    # role / EC2 instance profile) instead of the static keys above (ADR-0031).
    # The client resolves and auto-refreshes them from the container/instance
    # metadata endpoint, so there is no long-lived storage secret to distribute;
    # the two key settings are ignored. Only meaningful against real S3 —
    # MinIO has no metadata endpoint to serve role credentials.
    minio_iam_auth: bool = False
    minio_bucket: str = "challenge-files"
    minio_secure: bool = False  # http in dev; true behind TLS in prod
    # SigV4 region. Setting it lets the client sign presigned URLs *offline*; with
    # it unset the client makes a GetBucketLocation call to the (browser-facing)
    # public endpoint at sign time, which the backend can't reach when the public
    # and internal endpoints differ (e.g. localhost:9000 vs minio:9000 in compose).
    minio_region: str = "us-east-1"
    # Lifetime of a signed download URL, in seconds (§13.3 — short-lived).
    signed_url_ttl_seconds: int = 300

    # --- Certificates (optional module, ADR-0027) ---
    # The "Made with Flagpost" footer is composited onto every certificate by the
    # server and is un-removable by design (the marketing lever). This is the
    # gated-off hook for a future paid "remove branding" tier: shipped False so
    # the footer always renders; a licensed install would flip it. Deliberately a
    # config/env flag, not an admin-editable setting, so it can't be turned off
    # through the normal UI today.
    certificate_branding_removable: bool = False

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

    # Boot-time baseline import (#357, ADR-0038). Path to a mounted platform
    # export (ADR-0016): on startup, an *unconfigured* instance (no active
    # administrator) imports it instead of coming up empty — provisioning the
    # owner, branding, competitions and users declaratively. A normal install
    # imports exactly once; a reset-on-a-schedule internal demo re-imports on
    # every clean boot (see docs/INTERNAL_DEMO.md). Empty = off. A set-but-
    # unreadable/invalid file aborts startup rather than booting empty. When
    # set, the demo seed is suppressed — the baseline replaces the canned data.
    bootstrap_backup_file: str = ""

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

    # Prometheus /metrics (#351). Off by default — inert until an operator turns
    # it on, matching the AI / instancing posture. When enabled the endpoint
    # exposes operational cardinality only (counts, latencies, pool depth), never
    # competitor PII, and is gated: a scrape must present a matching bearer token
    # OR come from an allowlisted IP. Enabling with neither set is refused at
    # startup (below) — /metrics must never be public.
    metrics_enabled: bool = False
    metrics_token: str = ""
    # Comma-separated IPs / CIDRs allowed to scrape (e.g. "10.0.0.0/8,127.0.0.1").
    metrics_allowed_ips: str = ""

    @model_validator(mode="after")
    def _guard_metrics_gate(self) -> "Settings":
        if self.metrics_enabled and not (
            self.metrics_token or self.metrics_allowed_ips.strip()
        ):
            raise ValueError(
                "Refusing to start: METRICS_ENABLED is set but the /metrics "
                "endpoint has no gate. It exposes internal operational metrics "
                "and must never be public — set METRICS_TOKEN (a static scrape "
                "secret) and/or METRICS_ALLOWED_IPS (an IP/CIDR allowlist)."
            )
        return self

    @property
    def metrics_allowed_ip_list(self) -> list:
        """Parsed IP/CIDR allowlist for /metrics scraping (bare IPs → /32/128)."""
        nets = []
        for part in self.metrics_allowed_ips.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                nets.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                # A malformed entry is dropped, not fatal — the other gate
                # (token) and the remaining entries still apply.
                continue
        return nets

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
        if self.minio_iam_auth:
            # IAM-role auth (ADR-0031): no static credentials are in play at
            # all — the storage client ignores the key settings this check
            # would otherwise be inspecting.
            return self
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
