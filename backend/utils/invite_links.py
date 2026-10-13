"""Invite-link resolution helpers (#427).

The row stores facts; these decide whether a link may be *used* right now. Two
independent axes:

- **Lifecycle** (``is_active``) — organiser-controlled: not revoked, not past its
  expiry, uses remaining. Applies to every link.
- **View exposure** (``view_available``) — for ``view`` links only: the
  competition must *currently* be publicly visible with its public scoreboard on.
  Re-checked on every resolve, never stamped at creation, so turning a
  competition private (or hiding its board) kills outstanding view links — fail
  closed (#427, no new anonymous read-path into private data).

Both are read-only predicates; callers 404 on failure rather than disclosing why.
"""

from __future__ import annotations

from db import ensure_aware_utc, utcnow
from models.competition import Competition
from models.invite_link import InviteLink


def is_active(link: InviteLink, now=None) -> bool:
    """Lifecycle-usable: not revoked, not expired, uses remaining."""
    now = now or utcnow()
    if link.revoked_at is not None:
        return False
    if link.expires_at is not None and ensure_aware_utc(link.expires_at) <= now:
        return False
    if link.max_uses is not None and link.use_count >= link.max_uses:
        return False
    return True


def view_available(competition: Competition) -> bool:
    """A ``view`` link may resolve only while the competition is publicly visible
    with its public scoreboard enabled and not archived — i.e. it exposes no more
    than the existing anonymous spectator surface."""
    return (
        competition.visibility == "public"
        and competition.public_scoreboard
        and competition.archived_at is None
    )


def is_resolvable(link: InviteLink, competition: Competition, now=None) -> bool:
    """Can the public landing resolve this link at all? Lifecycle for every link,
    an archived competition kills links of both kinds (it's retired from view —
    links are an *active* sharing surface), and ``view`` additionally requires
    current public exposure."""
    if not is_active(link, now):
        return False
    if competition.archived_at is not None:
        return False
    if link.capability == "view" and not view_available(competition):
        return False
    return True
