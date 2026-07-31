"""External identity via OIDC (ADR-0021, issue #58).

Three site-wide tables — deliberately **not** ``CompetitionScopedMixin``, since
authentication is a property of the install, not of a competition (§7.7.1):

- :class:`OidcProvider` — an IdP an administrator configured. Each row carries
  its own ``enabled`` flag, which is the toggle; there is no module-level on/off
  because ``competition_modules`` is per-competition and has no site-scoped
  equivalent (ADR-0021).
- :class:`UserExternalIdentity` — the link between a local user and an IdP
  subject. Unique on ``(provider_id, subject)``: the IdP's ``sub`` is the stable
  key, so an email changing upstream follows the user instead of minting or
  hijacking an account.
- :class:`OidcLoginState` — one in-flight authorization request. PKCE and the
  ``state``/``nonce`` values have to survive the redirect to the IdP and back,
  and can't live in a cookie the IdP's redirect wouldn't reliably carry, so
  they're persisted server-side with a short TTL and deleted on use.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime
from utils.crypto import EncryptedString


class OidcProvider(Base, TimestampMixin):
    __tablename__ = "oidc_providers"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # Shown on the login button ("Sign in with {name}").
    name: Mapped[str] = mapped_column(String, nullable=False)
    # URL-safe identifier used in /api/auth/oidc/{slug}/… — stable, so changing
    # the display name never breaks a redirect URI registered at the IdP.
    slug: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    # OIDC issuer; discovery is issuer + /.well-known/openid-configuration.
    issuer: Mapped[str] = mapped_column(String, nullable=False)
    client_id: Mapped[str] = mapped_column(String, nullable=False)
    # Must be *retrieved* to authenticate to the token endpoint, so it's
    # encrypted rather than hashed (ADR-0020). Write-only over the API: reads
    # expose only a `client_secret_set` boolean.
    client_secret: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    scopes: Mapped[str] = mapped_column(
        String, nullable=False, default="openid email profile"
    )
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
        ForeignKey("oidc_providers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The IdP's `sub` claim — stable for the lifetime of the account there.
    subject: Mapped[str] = mapped_column(String, nullable=False)
    # Whatever the IdP last told us, kept for display/audit only. Never used to
    # resolve identity after the initial link.
    email: Mapped[str | None] = mapped_column(String, nullable=True)


class OidcLoginState(Base):
    """One in-flight authorization request. Deleted on use; expired rows are
    swept opportunistically (see ``utils.oidc.purge_expired_states``)."""

    __tablename__ = "oidc_login_states"

    # The `state` parameter itself — random, single-use, and the primary key so
    # a replayed callback can't find a second row to consume.
    state: Mapped[str] = mapped_column(String, primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("oidc_providers.id", ondelete="CASCADE"), nullable=False
    )
    code_verifier: Mapped[str] = mapped_column(String, nullable=False)
    nonce: Mapped[str] = mapped_column(String, nullable=False)
    # Where to send the browser after a successful login; validated as a
    # site-relative path before it's stored, so it can't become an open redirect.
    return_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
