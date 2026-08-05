"""Per-competition AI surfaces (#98, ADR-0023 Phase 3).

Two organiser-facing surfaces under a competition, distinct from the chat:

- **Competitor-assistant controls** (``/settings``, gated on ``edit_competition``)
  — the on/off toggle, the guidance-level override (null inherits the site
  default), and the hard challenge-metadata data toggle. Lazily creates the row
  on first write, like the site-settings singleton.
- **Transcript review** (``/transcripts``, gated on ``ai_view_transcripts``) —
  read-only oversight of the competitor assistant, the accountability that makes
  the behavioural guidance level *reviewable* rather than merely trusted (spec
  §5). Competitor conversations only; the organiser's own admin chats aren't
  listed here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.ai import AI_SETTINGS_ID, AiCompetitionSettings, AiConversation, AiMessage, AiSettings
from models.user import User
from schemas.ai import (
    AiCompetitionSettingsOut,
    AiCompetitionSettingsUpdate,
    AiMessageOut,
    AiTranscriptDetail,
    AiTranscriptSummary,
)
from utils.ai.guidance import resolve_guidance_level

router = APIRouter(prefix="/api/competitions/{competition_id}/ai", tags=["ai"])


async def _site_default_guidance(db: AsyncSession) -> str | None:
    settings = await db.get(AiSettings, AI_SETTINGS_ID)
    return settings.default_guidance_level if settings else None


async def _to_out(
    db: AsyncSession, row: AiCompetitionSettings | None
) -> AiCompetitionSettingsOut:
    site_default = await _site_default_guidance(db)
    override = row.guidance_level if row else None
    return AiCompetitionSettingsOut(
        competitor_enabled=bool(row and row.competitor_enabled),
        guidance_level=override,
        effective_guidance_level=resolve_guidance_level(override, site_default),
        challenge_metadata_access=bool(row and row.challenge_metadata_access),
        updated_at=row.updated_at if row else None,
    )


@router.get("/settings", response_model=AiCompetitionSettingsOut)
async def get_competition_ai_settings(
    competition_id: str,
    current_user: User = Depends(require_permission("edit_competition")),
    db: AsyncSession = Depends(get_db),
) -> AiCompetitionSettingsOut:
    row = await db.get(AiCompetitionSettings, competition_id)
    return await _to_out(db, row)


@router.put("/settings", response_model=AiCompetitionSettingsOut)
async def update_competition_ai_settings(
    competition_id: str,
    body: AiCompetitionSettingsUpdate,
    current_user: User = Depends(require_permission("edit_competition")),
    db: AsyncSession = Depends(get_db),
) -> AiCompetitionSettingsOut:
    row = await db.get(AiCompetitionSettings, competition_id)
    if row is None:
        row = AiCompetitionSettings(competition_id=competition_id)
        db.add(row)

    fields = body.model_fields_set
    if "competitor_enabled" in fields and body.competitor_enabled is not None:
        row.competitor_enabled = body.competitor_enabled
    if "challenge_metadata_access" in fields and body.challenge_metadata_access is not None:
        row.challenge_metadata_access = body.challenge_metadata_access
    # guidance_level is present-with-null-means-inherit: only touch it when the
    # field was sent, and an explicit null clears the override.
    if "guidance_level" in fields:
        row.guidance_level = body.guidance_level

    await db.commit()
    await db.refresh(row)
    return await _to_out(db, row)


@router.get("/transcripts", response_model=list[AiTranscriptSummary])
async def list_transcripts(
    competition_id: str,
    current_user: User = Depends(require_permission("ai_view_transcripts")),
    db: AsyncSession = Depends(get_db),
) -> list[AiTranscriptSummary]:
    """Competitor conversations in this competition, newest first, with the
    author's display name and message count — the review list."""
    rows = (
        await db.execute(
            select(
                AiConversation,
                User.display_name,
                func.count(AiMessage.id),
            )
            .join(User, User.id == AiConversation.user_id)
            .outerjoin(AiMessage, AiMessage.conversation_id == AiConversation.id)
            .where(
                AiConversation.competition_id == competition_id,
                AiConversation.assistant_type == "competitor",
            )
            .group_by(AiConversation.id, User.display_name)
            .order_by(AiConversation.created_at.desc())
        )
    ).all()
    return [
        AiTranscriptSummary(
            id=conv.id,
            user_id=conv.user_id,
            user_display_name=display_name,
            assistant_type=conv.assistant_type,
            message_count=count,
            created_at=conv.created_at,
            closed_at=conv.closed_at,
        )
        for conv, display_name, count in rows
    ]


@router.get("/transcripts/{conversation_id}", response_model=AiTranscriptDetail)
async def get_transcript(
    competition_id: str,
    conversation_id: str,
    current_user: User = Depends(require_permission("ai_view_transcripts")),
    db: AsyncSession = Depends(get_db),
) -> AiTranscriptDetail:
    conv = await db.get(AiConversation, conversation_id)
    if (
        conv is None
        or conv.competition_id != competition_id
        or conv.assistant_type != "competitor"
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found"
        )
    author = await db.get(User, conv.user_id)
    messages = (
        (
            await db.execute(
                select(AiMessage)
                .where(AiMessage.conversation_id == conversation_id)
                .order_by(AiMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    return AiTranscriptDetail(
        id=conv.id,
        user_id=conv.user_id,
        user_display_name=author.display_name if author else "(unknown)",
        assistant_type=conv.assistant_type,
        message_count=len(messages),
        created_at=conv.created_at,
        closed_at=conv.closed_at,
        messages=[AiMessageOut.model_validate(m) for m in messages],
    )
