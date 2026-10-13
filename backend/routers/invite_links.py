"""Competition invite-link routes (#427).

Two surfaces:

- ``org_router`` (``/api/competitions/{competition_id}/invite-links``) — organiser
  create / list / revoke, all gated by ``manage_invite_links`` (competition
  scope, so the per-competition grant resolves from the path). Each row op
  re-checks ``competition_id`` to block cross-tenant id access (§6.2).
- ``public_router`` (``/api/invite-links/{token}``) — the token-addressed landing
  surface: an unauthenticated *resolve* (what is this link?) and an authenticated
  *join*. Resolution fails closed to 404 (never discloses why) via
  ``utils.invite_links``.

The join path reuses ``routers.competitions._join`` so every existing gate
(email-verify, mandatory rules, registration fields, idempotent role grant) and
the ``competition.member_joined`` emit stay in one place.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, require_permission
from auth.membership import member_competition_ids
from db import ensure_aware_utc, get_db, utcnow
from models.competition import Competition
from models.invite_link import InviteLink
from models.user import User
from schemas.competition import CompetitionOut
from schemas.invite_link import (
    InviteLinkCreate,
    InviteLinkJoinRequest,
    InviteLinkOut,
    InviteLinkResolved,
)
from utils.event_bus import event_bus
from utils.invite_links import (
    is_active,
    is_resolvable,
    join_blocked_reason,
    view_available,
)
from utils.rules import accept_rules, effective_rules

org_router = APIRouter(
    prefix="/api/competitions/{competition_id}/invite-links", tags=["invite-links"]
)
public_router = APIRouter(prefix="/api/invite-links", tags=["invite-links"])


def _to_out(link: InviteLink) -> InviteLinkOut:
    return InviteLinkOut(
        id=link.id,
        competition_id=link.competition_id,
        token=link.token,
        capability=link.capability,
        label=link.label,
        expires_at=link.expires_at,
        max_uses=link.max_uses,
        use_count=link.use_count,
        last_used_at=link.last_used_at,
        revoked_at=link.revoked_at,
        created_at=link.created_at,
        active=is_active(link),
    )


async def _require_competition(db: AsyncSession, competition_id: str) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


# ---- organiser surface --------------------------------------------------------


@org_router.post("", response_model=InviteLinkOut, status_code=status.HTTP_201_CREATED)
async def create_invite_link(
    competition_id: str,
    body: InviteLinkCreate,
    current_user: User = Depends(require_permission("manage_invite_links")),
    db: AsyncSession = Depends(get_db),
) -> InviteLinkOut:
    competition = await _require_competition(db, competition_id)
    # View links are public-competition-only (#427) — reject at creation so the
    # organiser gets an immediate, explicit error rather than a link that only
    # ever 404s on resolve.
    if body.capability == "view" and competition.visibility != "public":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A view link can only be created for a public competition",
        )
    if body.expires_at is not None and ensure_aware_utc(body.expires_at) <= utcnow():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="expires_at must be in the future",
        )
    link = InviteLink(
        competition_id=competition_id,
        capability=body.capability,
        label=body.label,
        expires_at=body.expires_at,
        max_uses=body.max_uses,
        created_by=current_user.id,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    await event_bus.emit(
        "invite_link.created",
        {
            "competition_id": competition_id,
            "invite_link_id": link.id,
            "capability": link.capability,
        },
    )
    return _to_out(link)


@org_router.get("", response_model=list[InviteLinkOut])
async def list_invite_links(
    competition_id: str,
    current_user: User = Depends(require_permission("manage_invite_links")),
    db: AsyncSession = Depends(get_db),
) -> list[InviteLinkOut]:
    await _require_competition(db, competition_id)
    rows = (
        await db.scalars(
            select(InviteLink)
            .where(InviteLink.competition_id == competition_id)
            .order_by(InviteLink.created_at.desc())
        )
    ).all()
    return [_to_out(link) for link in rows]


@org_router.post("/{link_id}/revoke", response_model=InviteLinkOut)
async def revoke_invite_link(
    competition_id: str,
    link_id: str,
    current_user: User = Depends(require_permission("manage_invite_links")),
    db: AsyncSession = Depends(get_db),
) -> InviteLinkOut:
    link = await db.get(InviteLink, link_id)
    # Cross-tenant guard (§6.2): a link id from another competition 404s rather
    # than revealing it exists.
    if link is None or link.competition_id != competition_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invite link not found"
        )
    if link.revoked_at is None:
        link.revoked_at = utcnow()
        await db.commit()
        await db.refresh(link)
        await event_bus.emit(
            "invite_link.revoked",
            {
                "competition_id": competition_id,
                "invite_link_id": link.id,
                "capability": link.capability,
            },
        )
    return _to_out(link)


# ---- public token surface -----------------------------------------------------


async def _link_by_token(db: AsyncSession, token: str) -> InviteLink | None:
    return await db.scalar(select(InviteLink).where(InviteLink.token == token))


@public_router.get("/{token}", response_model=InviteLinkResolved)
async def resolve_invite_link(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> InviteLinkResolved:
    """Unauthenticated: what does this link point at? Fails closed to 404 for a
    revoked/expired/used-up link, and for a view link whose competition is no
    longer publicly visible."""
    link = await _link_by_token(db, token)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invite link not found"
        )
    competition = await db.get(Competition, link.competition_id)
    if competition is None or not is_resolvable(link, competition):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invite link not found"
        )
    if link.capability == "join":
        # ended, or the competition's registration window (#427 Phase 4).
        reason = join_blocked_reason(competition)
        actionable = reason is None
    else:
        reason = None
        actionable = view_available(competition)
    return InviteLinkResolved(
        capability=link.capability,
        competition_id=competition.id,
        competition_name=competition.name,
        competition_status=competition.status,
        participation_mode=competition.participation_mode,
        actionable=actionable,
        reason=reason,
        requires_login=link.capability == "join",
    )


@public_router.post("/{token}/join", response_model=CompetitionOut)
async def join_via_invite_link(
    token: str,
    body: InviteLinkJoinRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    """Authenticated: complete a join through a ``join`` link. Reuses the shared
    ``_join`` helper so all join gates apply; a successful *new* join consumes one
    use."""
    # Deferred import: _join lives with the competitions router, which the
    # competitions plugin also mounts; importing at module top would be fine
    # (no cycle) but this keeps the join logic's owner explicit.
    from routers.competitions import _join

    link = await _link_by_token(db, token)
    if link is None or link.capability != "join":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invite link not found"
        )
    competition = await db.get(Competition, link.competition_id)
    # Revoked / expired / used-up / archived → fail closed, same 404 as a bad
    # token. (The permanent invite_code path is deliberately untouched; the
    # *link* surface is fail-closed by design, #427.)
    if (
        competition is None
        or competition.archived_at is not None
        or not is_active(link)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invite link not found"
        )
    # Ended competitions don't admit new members via a link (#427, decision 4),
    # and the competition's registration window — enforced on the link path
    # only (#427 Phase 4) — gates it the same way. Same vocabulary as the
    # landing's resolve, so the two surfaces can't disagree.
    blocked = join_blocked_reason(competition)
    if blocked is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "ended": "This competition has ended",
                "registration_not_open": (
                    "Registration hasn't opened yet for this competition"
                ),
                "registration_closed": (
                    "Registration has closed for this competition"
                ),
            }[blocked],
        )
    # Accept-with-join (#57): a private competition's rules can't be pre-fetched
    # from the landing page, so acceptance rides the join request.
    if body is not None and body.accept_rules:
        doc, _display_only = await effective_rules(db, competition)
        if doc is not None:
            await accept_rules(db, competition.id, current_user.id)
    already_member = competition.id in await member_competition_ids(
        db, current_user.id
    )
    # Atomic use reservation for a capped link (#427 security-review M4). The old
    # check-then-increment raced: N concurrent joins on a `max_uses=1` link all
    # passed `is_active()` and all admitted. Reserve a slot with a conditional
    # UPDATE *before* granting access — the row lock serialises concurrent joins,
    # and winning 0 rows means the cap filled under us → fail closed with the
    # same undisclosing 404. It rides the same transaction as `_join` (which
    # commits), so a join gate that raises rolls the reservation back (the
    # session closes without commit). A re-clicking member burns nothing.
    if not already_member and link.max_uses is not None:
        reserved = await db.execute(
            update(InviteLink)
            .where(
                InviteLink.id == link.id,
                InviteLink.use_count < InviteLink.max_uses,
            )
            .values(use_count=InviteLink.use_count + 1, last_used_at=utcnow())
        )
        if reserved.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invite link not found"
            )
    await _join(
        db,
        competition,
        current_user,
        field_values=body.field_values if body else None,
        require_fields=False,
    )
    if not already_member:
        # Uncapped links can't race a cap, so a plain post-join increment is
        # fine; capped links already incremented in the reservation above
        # (committed by `_join`). Commit before emitting (SQLite writer lock).
        if link.max_uses is None:
            link.use_count += 1
            link.last_used_at = utcnow()
            await db.commit()
        await event_bus.emit(
            "invite_link.used",
            {
                "competition_id": competition.id,
                "invite_link_id": link.id,
                "user_id": current_user.id,
            },
        )
    return competition
