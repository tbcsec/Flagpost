"""Competition routes (ARCHITECTURE.md §6, §13.1).

Tier 0 scope is the *entity + scoping foundation* (ROADMAP #2): create a
competition (to exercise RBAC + the event bus) and read them back. Full
competition management — editing name/schedule, registration windows,
public/private visibility — is Tier 1 #6 and is deliberately not built here.

The competition is the tenancy *root*, so it isn't itself competition-scoped;
the §6.2 discipline (every tenant-scoped query filtered by ``competition_id``)
applies to the child entities that hang off it, which arrive in Tier 1. That
discipline is carried by ``CompetitionScopedMixin`` (db.py) so it's structural
rather than per-endpoint memory.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, require_permission
from auth.membership import (
    ensure_participant_role,
    has_global_role,
    member_competition_ids,
)
from db import get_db, utcnow
from models.competition import Competition
from models.rules_acceptance import RulesAcceptance
from models.user import User
from schemas.competition import (
    CompetitionCloneRequest,
    CompetitionCreate,
    CompetitionJoinRequest,
    CompetitionOut,
    CompetitionUpdate,
)
from routers.site_settings import get_or_create_settings
from storage import get_storage
from storage.base import ObjectStorage
from utils.competition_clone import clone_competition
from utils.competition_status import start_transition, stop_transition
from utils.competitions import get_visible_competition
from utils.event_bus import event_bus
from utils.retention import delete_competition_tree
from utils.rules import (
    accept_rules,
    effective_rules,
    require_rules_accepted,
)

router = APIRouter(prefix="/api/competitions", tags=["competitions"])


@router.get("", response_model=list[CompetitionOut])
async def list_competitions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Competition]:
    result = await db.execute(select(Competition).order_by(Competition.created_at))
    competitions = list(result.scalars().all())
    # Enforce visibility on the listing: private competitions are hidden from
    # anyone who isn't a member/organiser (a global admin sees all).
    if await has_global_role(db, current_user.id):
        return competitions
    member_ids = await member_competition_ids(db, current_user.id)
    return [
        c
        for c in competitions
        if c.visibility == "public" or c.id in member_ids
    ]


@router.get("/{competition_id}", response_model=CompetitionOut)
async def get_competition(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    # A private competition the caller can't see 404s (indistinguishable from
    # missing), never 403 — its existence isn't disclosed.
    competition = await get_visible_competition(db, competition_id, current_user)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


async def _join(
    db: AsyncSession, competition: Competition, user: User
) -> Competition:
    """Grant the Participant role (idempotently) and emit the join event once."""
    # Email verification gate (#74): join-only — an existing member is never
    # re-gated by an idempotent re-join (e.g. the setting flipping on
    # mid-event), and admin-created accounts are exempt (stamped verified at
    # creation).
    already_member = competition.id in await member_competition_ids(db, user.id)
    site = await get_or_create_settings(db)
    if (
        not already_member
        and site.email_verification_enabled
        and (user.email is None or user.email_verified_at is None)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email address before joining a competition",
        )
    # Rules gate (#57): mandatory effective rules must be accepted first.
    await require_rules_accepted(db, competition, user)
    newly_joined = await ensure_participant_role(db, competition.id, user.id)
    await db.commit()
    if newly_joined:
        await event_bus.emit(
            "competition.member_joined",
            {"competition_id": competition.id, "user_id": user.id},
        )
    return competition


@router.post("/join", response_model=CompetitionOut)
async def join_by_code(
    body: CompetitionJoinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    """Join any competition by its invite code — the only self-serve path into a
    private competition, and the individual-mode entry point (no team to join)."""
    competition = await db.scalar(
        select(Competition).where(Competition.invite_code == body.invite_code)
    )
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invite code"
        )
    # Accept-with-join (#57): the code path can't pre-fetch a private
    # competition's rules (the id is unknown and existence undisclosed), so the
    # first attempt 403s with the document and the retry carries acceptance.
    # A valid invite code is the authorization to accept.
    if body.accept_rules:
        doc, _display_only = await effective_rules(db, competition)
        if doc is not None:
            await accept_rules(db, competition.id, current_user.id)
    return await _join(db, competition, current_user)


@router.post("/{competition_id}/join", response_model=CompetitionOut)
async def join_competition(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    """Self-serve join for a **public** competition (from the lobby list).
    Private competitions require the invite-code route above."""
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    if competition.visibility != "public":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This competition is invite-only — join with an invite code",
        )
    return await _join(db, competition, current_user)


@router.post("", response_model=CompetitionOut, status_code=status.HTTP_201_CREATED)
async def create_competition(
    body: CompetitionCreate,
    # create_competition is a global-scope permission (§7.1) — held by
    # Administrator, not a per-competition role.
    current_user: User = Depends(require_permission("create_competition")),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    competition = Competition(
        name=body.name,
        description=body.description,
        start_at=body.start_at,
        end_at=body.end_at,
        registration_opens_at=body.registration_opens_at,
        registration_closes_at=body.registration_closes_at,
        participation_mode=body.participation_mode,
        visibility=body.visibility,
        mc_guess_limit=body.mc_guess_limit,
        mc_penalty_pct=body.mc_penalty_pct,
        challenge_ratings_enabled=body.challenge_ratings_enabled,
        challenge_tags=body.challenge_tags or None,
        difficulty_tiers=body.difficulty_tiers or None,
        public_scoreboard=body.public_scoreboard,
        ctftime_enabled=body.ctftime_enabled,
        brackets=body.brackets or None,
        max_team_size=body.max_team_size,
        paused=body.paused,
        rules_override=body.rules_override,
        rules_display_only=body.rules_display_only,
    )
    db.add(competition)
    await db.commit()
    await db.refresh(competition)

    await event_bus.emit(
        "competition.created",
        {
            "competition_id": competition.id,
            "user_id": current_user.id,
            "name": competition.name,
        },
    )
    return competition


@router.post(
    "/{competition_id}/clone",
    response_model=CompetitionOut,
    status_code=status.HTTP_201_CREATED,
)
async def clone_competition_route(
    competition_id: str,
    body: CompetitionCloneRequest,
    current_user: User = Depends(require_permission("create_competition")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Competition:
    """Clone a competition's config into a fresh one (§`utils.competition_clone`).
    Copies settings/categories/challenges/hints/attachments/surveys/module state;
    never the run's live data. Same permission as creating one from scratch."""
    source = await db.get(Competition, competition_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    clone = await clone_competition(db, source, body.name, storage)
    await db.commit()
    await db.refresh(clone)
    await event_bus.emit(
        "competition.created",
        {
            "competition_id": clone.id,
            "user_id": current_user.id,
            "name": clone.name,
            "cloned_from": source.id,
        },
    )
    return clone


@router.patch("/{competition_id}", response_model=CompetitionOut)
async def update_competition(
    competition_id: str,
    body: CompetitionUpdate,
    # edit_competition is competition-scoped (§7.1). require_permission resolves
    # the competition from the {competition_id} path param; a global Administrator
    # satisfies it for any competition, a Judge only for their own (§7.5).
    current_user: User = Depends(require_permission("edit_competition")),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )

    # PATCH semantics: apply only the fields the caller actually sent.
    changes = body.model_dump(exclude_unset=True)
    # Rules re-acceptance (#57, owner decision): adding or changing a non-null
    # override supersedes what members agreed to, so their acceptance rows are
    # deleted wholesale — every participant re-accepts the new text (the admin
    # UI warns before saving). Clearing the override (back to the global rules
    # they may have already accepted) doesn't reset.
    reset_acceptances = (
        "rules_override" in changes
        and changes["rules_override"] is not None
        and changes["rules_override"] != competition.rules_override
    )
    for field, value in changes.items():
        setattr(competition, field, value)
    if reset_acceptances:
        await db.execute(
            delete(RulesAcceptance).where(
                RulesAcceptance.competition_id == competition.id
            )
        )
    await db.commit()
    await db.refresh(competition)

    await event_bus.emit(
        "competition.updated",
        {
            "competition_id": competition.id,
            "user_id": current_user.id,
            "changed_fields": sorted(changes.keys()),
        },
    )
    return competition


async def _competition_or_404(db: AsyncSession, competition_id: str) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


@router.post("/{competition_id}/start", response_model=CompetitionOut)
async def start_competition(
    competition_id: str,
    # manage_schedule (Judge/Administrator) governs when a competition runs (#221).
    current_user: User = Depends(require_permission("manage_schedule")),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    """Open gameplay now: status → running (from not_started, or re-starting an
    ended competition). Idempotent if already running. Emits competition.started,
    so automations + the audit log see a manual start like a scheduled one."""
    competition = await _competition_or_404(db, competition_id)
    event = start_transition(competition)
    await db.commit()
    await db.refresh(competition)
    if event is not None:
        await event_bus.emit(*event)
    return competition


@router.post("/{competition_id}/stop", response_model=CompetitionOut)
async def stop_competition(
    competition_id: str,
    current_user: User = Depends(require_permission("manage_schedule")),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    """Close gameplay now: status → ended. Idempotent if already ended. Reversible
    — a later start reopens it. Emits competition.ended."""
    competition = await _competition_or_404(db, competition_id)
    event = stop_transition(competition)
    await db.commit()
    await db.refresh(competition)
    if event is not None:
        await event_bus.emit(*event)
    return competition


@router.post("/{competition_id}/archive", response_model=CompetitionOut)
async def archive_competition(
    competition_id: str,
    current_user: User = Depends(require_permission("edit_competition")),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    """Close a competition out: retained but hidden from the switcher/lobby and
    flagged in the admin list. Reversible (§`archived_at`). When the site's
    archive_auto_delete retention is on (#26), also stamps the purge clock —
    the confirm dialog has already shown the operator the exact deletion date."""
    competition = await _competition_or_404(db, competition_id)
    if competition.archived_at is None:
        competition.archived_at = utcnow()
        site = await get_or_create_settings(db)
        if site.archive_auto_delete:
            competition.purge_after = competition.archived_at + timedelta(
                days=site.archive_retention_days
            )
        await db.commit()
        await db.refresh(competition)
        await event_bus.emit(
            "competition.archived",
            {
                "competition_id": competition.id,
                "user_id": current_user.id,
                "purge_after": (
                    competition.purge_after.isoformat()
                    if competition.purge_after
                    else None
                ),
            },
        )
    return competition


@router.post("/{competition_id}/unarchive", response_model=CompetitionOut)
async def unarchive_competition(
    competition_id: str,
    current_user: User = Depends(require_permission("edit_competition")),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    competition = await _competition_or_404(db, competition_id)
    if competition.archived_at is not None:
        competition.archived_at = None
        # Unarchiving cancels the retention clock; re-archiving restarts it.
        competition.purge_after = None
        await db.commit()
        await db.refresh(competition)
        await event_bus.emit(
            "competition.unarchived",
            {"competition_id": competition.id, "user_id": current_user.id},
        )
    return competition


@router.delete("/{competition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_competition(
    competition_id: str,
    current_user: User = Depends(require_permission("delete_competition")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> None:
    """Permanently delete a competition and everything under it (§6.2 tenant
    tree cascades on the FK), including its stored attachment objects (#26 —
    previously orphaned in MinIO). Irreversible — the destructive counterpart
    to archive. Shares the tree-delete with the retention purge."""
    competition = await _competition_or_404(db, competition_id)
    await delete_competition_tree(
        db, storage, competition, actor_user_id=current_user.id
    )
