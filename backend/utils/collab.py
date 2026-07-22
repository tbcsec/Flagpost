"""Collaborative-note scope resolution + persistence (ARCHITECTURE.md §4.2).

A collaborative note is addressed by a ``doc_key`` that encodes *which* resource
it belongs to; this module is the single place that parses a ``doc_key``, decides
whether a user may read/write it (per-request, server-side, exactly like a REST
route — §7.6), and resolves the owning ``competition_id``. The CRDT transport
(``plugins/collab``) stays agnostic to which side of the platform it's serving —
it only asks this module "is this user allowed, and under which competition?"
(§4.2).

Two scopes today:

- ``team_challenge:<team_id>:<challenge_id>`` — a team's private scratchpad for
  a challenge. Authorized to **members of that team only** (no permission grant,
  no cross-team visibility, §4.2). The team and challenge must belong to the
  same competition.
- ``ticket:<ticket_id>`` — staff internal notes on a support ticket. Authorized
  to holders of ``ticket_view_internal_notes`` (staff) — deliberately **not**
  the ticket opener, so a competitor never sees the staff note channel.

Persistence is a single opaque blob per doc (ADR-0014); ``load_state`` /
``save_state`` are the only DB touchpoints and both are keyed by ``doc_key``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import user_has_permission
from models.challenge import Challenge
from models.collab import CollabDocument
from models.team import Team, TeamMembership
from models.ticket import Ticket
from models.user import User


@dataclass(frozen=True)
class ResolvedNote:
    """A note the requesting user is allowed to read/write."""

    doc_key: str
    competition_id: str


async def resolve_note(
    db: AsyncSession, user: User, doc_key: str
) -> ResolvedNote | None:
    """Authorize ``user`` for ``doc_key`` and resolve its competition.

    Returns ``None`` for an unknown scope, a missing/mismatched resource, or a
    user who isn't allowed — the caller (WS authorizer) treats every ``None`` as
    "not allowed in this room", never distinguishing 403 from 404 over the socket.
    """
    parts = doc_key.split(":")
    scope = parts[0] if parts else ""

    if scope == "team_challenge" and len(parts) == 3:
        _, team_id, challenge_id = parts
        challenge = await db.get(Challenge, challenge_id)
        team = await db.get(Team, team_id)
        if challenge is None or team is None:
            return None
        if team.competition_id != challenge.competition_id:
            return None
        member = await db.scalar(
            select(TeamMembership.id).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user.id,
            )
        )
        if member is None:
            return None
        return ResolvedNote(doc_key=doc_key, competition_id=challenge.competition_id)

    if scope == "ticket" and len(parts) == 2:
        ticket = await db.get(Ticket, parts[1])
        if ticket is None:
            return None
        if not await user_has_permission(
            db, user.id, "ticket_view_internal_notes", ticket.competition_id
        ):
            return None
        return ResolvedNote(doc_key=doc_key, competition_id=ticket.competition_id)

    return None


async def load_state(db: AsyncSession, doc_key: str) -> bytes | None:
    """The last-persisted Y.js blob for a doc, or ``None`` if never saved."""
    doc = await db.get(CollabDocument, doc_key)
    return doc.state if doc is not None else None


async def save_state(
    db: AsyncSession, doc_key: str, competition_id: str, state: bytes
) -> None:
    """Upsert the full merged Y.js state for a doc (ADR-0014 client-snapshot)."""
    doc = await db.get(CollabDocument, doc_key)
    if doc is None:
        doc = CollabDocument(
            doc_key=doc_key, competition_id=competition_id, state=state
        )
        db.add(doc)
    else:
        doc.state = state
    await db.commit()
