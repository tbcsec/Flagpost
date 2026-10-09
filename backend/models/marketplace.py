"""Marketplace settings (#389, ADR-0040) — the registry + trust config singleton.

One row holds the site-wide import-client configuration: which registry a code
resolves against, whether the surface is on at all, the trust policy that decides
which signatures are acceptable, the highest installable trust tier, and the
operator-added public keys that extend trust beyond the baked-in project root key.

Like :class:`~models.site_settings.SiteSettings` and
:class:`~models.ai.AiSettings` this is **not** tenant-scoped (the marketplace is
a property of the install, not a competition) and there is only ever one row: the
settings router lazily creates it with defaults on first read, and ``id`` is a
fixed sentinel so a second row can't be created by accident.

Unlike the ``ai`` module this defaults **enabled**: the surface makes no outbound
call until an operator explicitly resolves or installs (docs/MODULES.md §6), so an
available-but-idle marketplace leaks nothing. ``enabled = false`` fully disables it
for locked-down installs.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime, utcnow

# The single row's fixed primary key — the singleton sentinel.
MARKETPLACE_SETTINGS_ID = "marketplace"

DEFAULT_REGISTRY_URL = "https://marketplace.flagpost.io"
DEFAULT_TRUST_POLICY = "verified"
DEFAULT_MAX_TRUST_TIER = "declarative"


class MarketplaceSettings(Base, TimestampMixin):
    __tablename__ = "marketplace_settings"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=MARKETPLACE_SETTINGS_ID
    )
    # Master switch for the whole marketplace surface. No outbound call happens
    # until an operator acts, so on-by-default is safe; off = fully disabled.
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    # The registry a code resolves against. Configurable so a private mirror or an
    # air-gapped static host is first-class; the default is the hosted one.
    registry_url: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=DEFAULT_REGISTRY_URL,
        server_default=DEFAULT_REGISTRY_URL,
    )
    # Which signatures are acceptable — one of utils.marketplace_verify.TRUST_POLICIES
    # (official ⊂ verified ⊂ signed ⊂ any). Validated at the API.
    trust_policy: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=DEFAULT_TRUST_POLICY,
        server_default=DEFAULT_TRUST_POLICY,
    )
    # Highest tier installable (pack < declarative < code). Conservative by default:
    # third-party *code* needs an explicit opt-in. Content packs are always below
    # this, so it only bites once modules can install (#391).
    max_trust_tier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=DEFAULT_MAX_TRUST_TIER,
        server_default=DEFAULT_MAX_TRUST_TIER,
    )
    # Operator-added ed25519 public keys that extend trust beyond the baked-in
    # project root key: ``[{key_id, public_key (base64 raw), verified: bool, label}]``.
    # Public keys only — nothing secret — so GET exposes it and it rides the backup.
    # NULL is read as an empty list.
    trusted_keys: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    updated_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, onupdate=utcnow, nullable=True
    )
