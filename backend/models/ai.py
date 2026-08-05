"""AI assistants module settings (#98, ADR-0023) — the provider config singleton.

One row holds the site-wide, bring-your-own-endpoint configuration an
administrator sets for the ``ai`` optional module: the OpenAI-compatible
``base_url`` + ``model``, the write-only ``api_key``, per-response output caps
and a request timeout, the two optional system-prompt overrides, and the
site-level default guidance level that new competitions inherit (owner decision).

Like :class:`~models.site_settings.SiteSettings` this is **not** tenant-scoped —
authentication and AI provider config are properties of the install (§7.7.1), not
of a competition — and there is only ever one row: the settings router lazily
creates it with defaults on first read, and ``id`` is a fixed sentinel so a
second row can't be created by accident.

``enabled`` is the site master switch and defaults **off**: the module ships
inert (spec §2), and no assistant does anything until an administrator configures
an endpoint and turns this on. The conversation tables (``ai_conversations`` /
``ai_messages``) and the per-competition controls arrive with the assistants
themselves in later phases; this row is the provider plumbing on its own.
"""

from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime, utcnow
from utils.crypto import EncryptedString

# The single row's fixed primary key — the singleton sentinel.
AI_SETTINGS_ID = "ai"

DEFAULT_REQUEST_TIMEOUT_S = 60
DEFAULT_MAX_OUTPUT_TOKENS = 1024
# Deliberately lower than the admin cap (spec §9): the competitor assistant is a
# hint channel and a proxy to a paid endpoint, so it gets a tighter ceiling.
DEFAULT_COMPETITOR_MAX_OUTPUT_TOKENS = 512
DEFAULT_GUIDANCE_LEVEL = "platform_only"


class AiSettings(Base, TimestampMixin):
    __tablename__ = "ai_settings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=AI_SETTINGS_ID)
    # Master switch. Off until an admin configures + enables the module (spec §2);
    # no assistant runs while this is false. Enabling is refused at the API unless
    # base_url + model are set (schemas.ai), so "enabled but unconfigured" isn't
    # reachable — the same posture the identity-provider admin takes.
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Bring-your-own OpenAI-compatible endpoint (ADR-0023 §1): base + model are
    # passed verbatim. base_url is a *trusted operator setting* — the same class
    # as the SMTP host and OIDC issuer — so it is deliberately NOT run through the
    # ADR-0013 webhook SSRF blocklist and may point at a private local inference
    # server (Ollama/vLLM); that is the intended self-hosted deployment.
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    # The API key must be *presented* to the endpoint, so it is encrypted at rest,
    # not hashed (ADR-0020) — the same treatment as the SMTP password and the
    # OIDC/SAML/LDAP provider secrets. Write-only over the API (GET exposes only
    # ``api_key_set``), and dropped from the backup export. May be blank for a
    # keyless local endpoint.
    #
    # **Deferred** like ``SiteSettings.smtp_password`` and for the same reason:
    # ``EncryptedString`` decrypts on column load and *raises* on a key mismatch.
    # The admin settings page is exactly where an operator re-enters the key after
    # a lost/rotated one, so eager-decrypting would 500 the recovery path. The
    # provider client undefers it explicitly at call time, so a key failure
    # surfaces at the request that needs it (ADR-0020).
    api_key: Mapped[str | None] = mapped_column(
        EncryptedString, nullable=True, deferred=True
    )
    # Hard per-response output ceilings (spec §9), enforced server-side regardless
    # of what the model requests; the competitor cap is separate and lower.
    max_output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_MAX_OUTPUT_TOKENS,
        server_default=str(DEFAULT_MAX_OUTPUT_TOKENS),
    )
    competitor_max_output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_COMPETITOR_MAX_OUTPUT_TOKENS,
        server_default=str(DEFAULT_COMPETITOR_MAX_OUTPUT_TOKENS),
    )
    request_timeout_s: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_REQUEST_TIMEOUT_S,
        server_default=str(DEFAULT_REQUEST_TIMEOUT_S),
    )
    # Optional per-assistant system-prompt overrides (spec §6). Null = the
    # code-shipped default. The prompt governs tone / refusal style / topicality
    # only; per the ADR-0023 axiom, no data-scoping or safety property depends on
    # it, which is what makes an override low-risk.
    admin_prompt_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    competitor_prompt_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Site-level default guidance level that a new competition inherits and may
    # override (owner decision). ``platform_only`` is the safe default; the
    # per-competition override machinery lands with the competitor assistant.
    default_guidance_level: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=DEFAULT_GUIDANCE_LEVEL,
        server_default=DEFAULT_GUIDANCE_LEVEL,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, onupdate=utcnow, nullable=True
    )
