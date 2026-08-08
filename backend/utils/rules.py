"""Rules / code-of-conduct gate (issue #57).

One shared enforcement point for the four places a user gains competition
membership — ``_join()`` (both competition-join routes), ``join_team`` and
``create_team`` — so the gate can't drift per-endpoint. The *effective*
document is the competition's ``rules_override`` when set, else the site-wide
``rules_text``; the display-only flag travels with whichever document applies.

Staff exemption is permission-driven, never a role check (§7.6): anyone
holding ``edit_competition`` for the competition (a Judge there, or a global
Administrator) skips the gate and the prompt entirely (owner decision).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import user_has_permission
from models.competition import Competition
from models.rules_acceptance import RulesAcceptance
from models.user import User
from utils.event_bus import event_bus


def has_rules_text(doc: dict | None) -> bool:
    """Whether a rich-text document actually says anything.

    A TipTap doc that's visually empty still serializes to nested nodes
    (``{"type": "doc", "content": [{"type": "paragraph"}]}``), so "rules are
    configured" must mean *non-whitespace text exists*, not "the JSON is
    non-null" — otherwise a cleared-but-saved editor would silently gate joins
    on an empty pop-up.
    """
    if not doc or not isinstance(doc, dict):
        return False

    def walk(node: object) -> bool:
        if not isinstance(node, dict):
            return False
        text = node.get("text")
        if isinstance(text, str) and text.strip():
            return True
        content = node.get("content")
        if isinstance(content, list):
            return any(walk(child) for child in content)
        return False

    return walk(doc)


async def effective_rules(
    db: AsyncSession, competition: Competition
) -> tuple[dict | None, bool]:
    """The document that applies to ``competition`` and its display-only flag:
    the override (with the competition's flag) when set, else the site-wide
    text (with the site's flag). Returns ``(None, False)`` when nothing
    meaningful is configured at either level."""
    if has_rules_text(competition.rules_override):
        return competition.rules_override, competition.rules_display_only
    # Imported here (not at module top) to avoid a routers→utils→routers cycle.
    from routers.site_settings import get_or_create_settings

    site = await get_or_create_settings(db)
    if has_rules_text(site.rules_text):
        return site.rules_text, site.rules_display_only
    return None, False


async def has_accepted(
    db: AsyncSession, competition_id: str, user_id: str
) -> bool:
    row = await db.scalar(
        select(RulesAcceptance.id).where(
            RulesAcceptance.competition_id == competition_id,
            RulesAcceptance.user_id == user_id,
        )
    )
    return row is not None


async def is_rules_exempt(
    db: AsyncSession, competition_id: str, user_id: str
) -> bool:
    """Staff (edit_competition holders) never see or accept the rules."""
    return await user_has_permission(
        db, user_id, "edit_competition", competition_id
    )


@dataclass(frozen=True)
class RulesState:
    rules: dict | None
    display_only: bool
    accepted: bool
    exempt: bool


async def rules_state(
    db: AsyncSession, competition: Competition, user: User
) -> RulesState:
    doc, display_only = await effective_rules(db, competition)
    return RulesState(
        rules=doc,
        display_only=display_only,
        accepted=await has_accepted(db, competition.id, user.id),
        exempt=await is_rules_exempt(db, competition.id, user.id),
    )


async def require_rules_accepted(
    db: AsyncSession, competition: Competition, user: User
) -> None:
    """The join gate: 403 unless the effective rules (if any, and mandatory)
    have been accepted by ``user``, or the user is staff-exempt.

    The error detail is structured — ``code`` lets clients distinguish it from
    a plain permission failure, and it carries the document itself so the
    invite-code join flow (which cannot pre-fetch a private competition's
    rules without disclosing its existence) can render the prompt straight
    from the rejection.
    """
    doc, display_only = await effective_rules(db, competition)
    if doc is None or display_only:
        return
    if await is_rules_exempt(db, competition.id, user.id):
        return
    if await has_accepted(db, competition.id, user.id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "rules_not_accepted",
            "competition_id": competition.id,
            "rules": doc,
            "message": "You must accept the competition rules before joining",
        },
    )


async def accept_rules(
    db: AsyncSession, competition_id: str, user_id: str
) -> bool:
    """Record acceptance (idempotently) and emit the audit event once.

    Returns True when a new row was recorded, False when one already existed
    (re-accepting neither duplicates the row nor re-emits). Commits.
    """
    if await has_accepted(db, competition_id, user_id):
        return False
    db.add(RulesAcceptance(competition_id=competition_id, user_id=user_id))
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race with a concurrent accept (e.g. two tabs): both requests
        # passed the exists-check and the other one committed first. The row
        # existing is exactly the outcome the caller wanted, so resolve to the
        # already-accepted path — the winning request alone emits the event.
        await db.rollback()
        return False
    await event_bus.emit(
        "competition.rules_accepted",
        {"competition_id": competition_id, "user_id": user_id},
    )
    return True
