"""External identity providers — all kinds (ADR-0022, generalizing ADR-0021).

Three site-wide tables — deliberately **not** ``CompetitionScopedMixin``, since
authentication is a property of the install, not of a competition (§7.7.1):

- :class:`IdentityProvider` — one row per configured provider of any ``kind``
  (``"oidc"`` today; ``"saml"``/``"ldap"`` arrive with their transports, #100/
  #101). Shared, typed columns cover what the admin list and the login page
  need; the kind-specific non-secret settings live in ``config`` (JSON,
  validated against the per-kind model in ``schemas/auth_providers`` at write
  *and* re-parsed at login, ADR-0022 §6); the kind's one retrievable secret —
  OIDC client secret, SAML SP key, LDAP bind password — lives in ``secret``.
- :class:`UserExternalIdentity` — the link between a local user and a
  provider's subject (OIDC ``sub``; later SAML ``NameID`` / LDAP stable id).
  Unique on ``(provider_id, subject)``: the subject is the stable key, so an
  email changing upstream follows the user instead of minting or hijacking an
  account.
- :class:`AuthLoginState` — one in-flight browser-redirect login. PKCE and the
  ``state``/``nonce`` values (and, later, SAML's ``RelayState``/``InResponseTo``)
  have to survive the round trip to the IdP and can't live in a cookie the
  IdP's redirect wouldn't reliably carry, so they're persisted server-side with
  a short TTL and deleted on use. LDAP never touches this table — a credential
  bind has no redirect leg.

``posture`` is the ADR-0022 §2 trust split: an ``open`` provider (a public IdP)
is governed by the #118 public-signup gate; a ``closed`` provider (an
admin-configured directory) is admitted by being enabled, and its email claims
are display-only unless ``email_is_authoritative`` is set.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime
from utils.crypto import EncryptedString


class IdentityProvider(Base, TimestampMixin):
    __tablename__ = "identity_providers"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # Which protocol this row configures. Discriminates the `config` payload;
    # the valid set is the schemas/auth_providers registry, not a DB enum, so a
    # new protocol is a code change without a migration.
    kind: Mapped[str] = mapped_column(String, nullable=False)
    # ADR-0022 §2: "open" = the #118 public-signup gate applies; "closed" = the
    # provider being enabled *is* the admission decision.
    posture: Mapped[str] = mapped_column(String, nullable=False, default="open")
    # Shown on the login button ("Sign in with {name}").
    name: Mapped[str] = mapped_column(String, nullable=False)
    # URL-safe identifier used in /api/auth/{kind}/{slug}/… — stable, so
    # changing the display name never breaks a redirect URI registered at an IdP.
    slug: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    # Closed providers only (enforced at the API): treat the provider's email
    # attribute as proof of address ownership, enabling first-contact linking
    # to an existing local account. Off by default — a directory `mail` field
    # is not, in general, a verified address (ADR-0022 §2).
    email_is_authoritative: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # The kind's one retrievable secret (ADR-0020: encrypted, not hashed,
    # because it must be replayed to the far side). Write-only over the API:
    # reads expose only a `secret_set` boolean.
    secret: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    # Kind-specific non-secret settings (issuer/client_id/scopes for OIDC).
    # Generic JSON for SQLite/Postgres portability (ADR-0006); shape is owned
    # by the per-kind Pydantic model, enforced at write and re-parsed at login.
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class UserExternalIdentity(Base, TimestampMixin):
    __tablename__ = "user_external_identities"
    __table_args__ = (
        UniqueConstraint("provider_id", "subject", name="uq_external_identity"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("identity_providers.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # The provider's stable subject for this user (OIDC `sub`).
    subject: Mapped[str] = mapped_column(String, nullable=False)
    # Whatever the provider last told us, kept for display/audit only. Never
    # used to resolve identity after the initial link.
    email: Mapped[str | None] = mapped_column(String, nullable=True)


class AuthLoginState(Base):
    """One in-flight redirect login. Deleted on use; expired rows are swept
    opportunistically by the login route."""

    __tablename__ = "auth_login_states"

    # The `state` parameter itself — random, single-use, and the primary key so
    # a replayed callback can't find a second row to consume.
    state: Mapped[str] = mapped_column(String, primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False
    )
    # OIDC-specific legs, nullable so a SAML request (which has neither) can
    # share the table rather than duplicating the TTL/single-use machinery.
    code_verifier: Mapped[str | None] = mapped_column(String, nullable=True)
    nonce: Mapped[str | None] = mapped_column(String, nullable=True)
    # Where to send the browser after a successful login; validated as a
    # site-relative path before it's stored, so it can't become an open redirect.
    return_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
