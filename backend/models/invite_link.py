"""Competition invite links (#427).

A shareable, revocable link an organiser hands out to get people *into* or
*looking at* a competition. The existing ``Competition.invite_code`` is a single
permanent, non-rotating secret; an ``InviteLink`` is the richer, managed
primitive — multiple per competition, each with an optional expiry / use-cap and
an explicit revoke — layered *alongside* that code (the code stays the stable
fallback join path).

Competition-scoped (``CompetitionScopedMixin``): a link always belongs to one
competition and is purged with it (``ondelete=CASCADE``). It is **not** exported
or carried by clone — links are ephemeral secrets, so a cloned/restored
competition mints fresh ones (#427).

Two capabilities (``capability``):

- ``join`` — the landing page invites the recipient to join (login/register →
  the normal join gates). Works for public **and** private competitions: the
  token *is* the authorization to know the competition exists.
- ``view`` — a read-only "this is happening" link. **Public competitions only**
  and resolves to no more than the public spectator surface, so it adds no new
  anonymous read-path into private data (#427). Validity is re-checked against
  *current* competition state on every use, so flipping a competition to private
  (or disabling its public scoreboard) kills outstanding view links — fail closed.

Whether a link is *usable* (not revoked, not expired, uses remaining, and — for
``view`` — the competition still publicly visible) is computed at resolve time in
``utils.invite_links``; the row only stores the facts.
"""

from datetime import datetime
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin, UtcDateTime

# A link is one of these. Kept as a small closed set (validated in the schema and
# re-asserted here is unnecessary — SQLite/Postgres store the string) so a new
# capability is a deliberate code change, not stray data.
CAPABILITIES: tuple[str, ...] = ("join", "view")


def generate_link_token() -> str:
    """The shareable secret embedded in the URL. Longer than the competition
    invite code (16 bytes vs 8): it travels further and lives in link history, so
    it carries more entropy and never collides with the join-code namespace."""
    return token_urlsafe(16)


class InviteLink(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "invite_links"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # The URL secret. Unique + indexed — the public resolve path looks a link up
    # by token on every landing hit.
    token: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=generate_link_token
    )
    capability: Mapped[str] = mapped_column(String, nullable=False)
    # Organiser's own note ("Discord #announcements", "sponsor email") — never
    # shown to recipients.
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    # Optional lifecycle controls the bare invite_code lacks. NULL = no limit.
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Successful *new* joins through this link (re-clicks by existing members
    # don't count), so max_uses means "admit this many people".
    use_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # When the link last admitted someone (same new-join semantics as
    # use_count) — "is this link still circulating?" at a glance (#427 Phase 4).
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Soft revoke: set once, never reused. A revoked link fails closed like an
    # expired one; the row is kept for the audit trail rather than deleted.
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Who minted it. SET NULL rather than CASCADE: deleting the author must not
    # silently drop a live link that others may still be holding.
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
