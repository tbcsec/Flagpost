"""Rules / code-of-conduct routes (issue #57).

Competition-scoped (§6.2), mounted by the ``competitions`` plugin. Both routes
are plain-authenticated rather than permission-gated: a prospective joiner has
no competition role yet, so ``challenge_view`` would lock out exactly the
users the rules exist for. Visibility is still enforced — a private
competition the caller can't see 404s (existence undisclosed), matching the
competition read routes. The invite-code join path never needs these routes
pre-join: its 403 carries the document, and acceptance travels with the
retried join (``accept_rules``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user
from auth.membership import member_competition_ids
from db import get_db
from models.competition import Competition
from models.user import User
from schemas.rules import RulesOut
from utils.rules import accept_rules, rules_state

router = APIRouter(
    prefix="/api/competitions/{competition_id}/rules", tags=["rules"]
)


async def _visible_competition_or_404(
    db: AsyncSession, competition_id: str, user: User
) -> Competition:
    # Imported here (not at module top) to avoid a circular import with the
    # competitions router, which itself imports the gate helpers.
    from routers.competitions import _can_see

    competition = await db.get(Competition, competition_id)
    if competition is None or not await _can_see(db, competition, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


def _out(state, *, member: bool) -> RulesOut:
    return RulesOut(
        rules=state.rules,
        display_only=state.display_only,
        accepted=state.accepted,
        exempt=state.exempt,
        # The in-app gate's verdict: membership included so a non-member
        # browsing a public competition is never blocked app-wide — the join
        # flows do their own gating from the raw facts.
        required=(
            state.rules is not None
            and not state.display_only
            and not state.accepted
            and not state.exempt
            and member
        ),
    )


@router.get("", response_model=RulesOut)
async def read_rules(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RulesOut:
    competition = await _visible_competition_or_404(
        db, competition_id, current_user
    )
    state = await rules_state(db, competition, current_user)
    member = competition.id in await member_competition_ids(db, current_user.id)
    return _out(state, member=member)


@router.post("/accept", response_model=RulesOut)
async def accept_competition_rules(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RulesOut:
    """Record the caller's acceptance of the effective rules. Idempotent —
    re-accepting neither duplicates the row nor re-emits the event."""
    competition = await _visible_competition_or_404(
        db, competition_id, current_user
    )
    state = await rules_state(db, competition, current_user)
    if state.rules is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This competition has no rules to accept",
        )
    await accept_rules(db, competition.id, current_user.id)
    fresh = await rules_state(db, competition, current_user)
    member = competition.id in await member_competition_ids(db, current_user.id)
    return _out(fresh, member=member)
