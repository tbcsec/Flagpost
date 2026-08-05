"""Administrator-assistant conversations (#98, ADR-0023 Phase 2).

A staff user opens a conversation for a competition, then posts messages; each
message runs one assistant turn (tool calls execute as *that user* — §5.4) and
streams the answer over the ``ai`` WebSocket room while the POST persists the
result. Read-only throughout: the only writes are the conversation/message rows,
which carry their own ``ai.query`` usage event (never message content, §4).

Gating, in order: the module must be configured + enabled (site master switch),
the ``ai`` module enabled for the competition, the caller must be able to see the
competition and hold a tool permission (:func:`can_use_admin_assistant`), and
per-user message rate + single-in-flight + conversation-length caps apply (§9).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user
from db import get_db, utcnow
from models.ai import AI_SETTINGS_ID, AiConversation, AiMessage, AiSettings
from models.user import User
from plugins.loader import is_module_enabled
from ratelimit import get_rate_limiter
from ratelimit.base import RateLimiter
from realtime import manager
from schemas.ai import (
    AiAvailabilityOut,
    AiConversationDetail,
    AiConversationOut,
    AiMessageCreate,
    AiMessageOut,
    AiUsageOut,
)
from utils.ai.assistant import run_admin_turn
from utils.ai.client import AiProviderError
from utils.ai.tools import can_use_admin_assistant
from utils.competitions import get_visible_competition
from utils.event_bus import event_bus

logger = logging.getLogger("ai")

router = APIRouter(prefix="/api/competitions/{competition_id}/ai", tags=["ai"])

# Conversation length cap: 20 exchanges, then the conversation closes and a new
# message must start a fresh one (spec §9).
MAX_EXCHANGES = 20
# History window handed to the model — the last 20 exchanges (user+assistant).
HISTORY_MESSAGES = 40
# Per-user message cap for the admin assistant (spec §9).
ADMIN_MSG_LIMIT = 60
ADMIN_MSG_WINDOW = 3600

# One in-flight generation per user (spec §9: concurrent streams per user = 1).
# Process-local — a multi-worker deploy would need a shared lock (Redis); a
# second worker would let a second stream through, which is a soft cap, not a
# safety property, so this is acceptable for now.
_in_flight: set[str] = set()


async def _require_ai(db: AsyncSession, competition_id: str) -> AiSettings:
    """The AI settings row if the module is configured, enabled, and on for this
    competition — else a clear 4xx. Does not load the (deferred) api_key."""
    settings = await db.get(AiSettings, AI_SETTINGS_ID)
    if settings is None or not settings.enabled or not settings.base_url or not settings.model:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The AI assistant isn't configured on this instance.",
        )
    if not await is_module_enabled(db, "ai", competition_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The AI module is disabled for this competition.",
        )
    return settings


async def _require_staff_access(db: AsyncSession, user: User, competition_id: str):
    competition = await get_visible_competition(db, competition_id, user)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    if not await can_use_admin_assistant(db, user, competition_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to the administrator assistant here.",
        )
    return competition


async def _conversation_or_404(
    db: AsyncSession, competition_id: str, conversation_id: str, user: User
) -> AiConversation:
    conv = await db.get(AiConversation, conversation_id)
    if conv is None or conv.competition_id != competition_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    # Owner, or staff who can use the assistant here.
    if conv.user_id != user.id and not await can_use_admin_assistant(
        db, user, competition_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return conv


@router.get("/availability", response_model=AiAvailabilityOut)
async def availability(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AiAvailabilityOut:
    """Whether the caller may open the administrator assistant here — the client
    gate for showing the launcher. Never raises on "off"; returns ``available:
    false`` when the module is unconfigured/disabled or the caller isn't staff,
    so a competitor probing it learns only that the assistant isn't for them."""
    settings = await db.get(AiSettings, AI_SETTINGS_ID)
    configured = bool(
        settings and settings.enabled and settings.base_url and settings.model
    )
    if not configured or not await is_module_enabled(db, "ai", competition_id):
        return AiAvailabilityOut(available=False)
    competition = await get_visible_competition(db, competition_id, current_user)
    can_use = competition is not None and await can_use_admin_assistant(
        db, current_user, competition_id
    )
    return AiAvailabilityOut(available=can_use)


@router.post(
    "/conversations",
    response_model=AiConversationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AiConversationOut:
    await _require_ai(db, competition_id)
    await _require_staff_access(db, current_user, competition_id)
    conv = AiConversation(
        competition_id=competition_id,
        user_id=current_user.id,
        assistant_type="admin",
    )
    db.add(conv)
    await db.commit()
    return AiConversationOut.model_validate(conv)


@router.get("/conversations/{conversation_id}", response_model=AiConversationDetail)
async def get_conversation(
    competition_id: str,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AiConversationDetail:
    conv = await _conversation_or_404(db, competition_id, conversation_id, current_user)
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
    detail = AiConversationDetail.model_validate(conv)
    detail.messages = [AiMessageOut.model_validate(m) for m in messages]
    return detail


async def _history(db: AsyncSession, conversation_id: str) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(AiMessage.role, AiMessage.content)
                .where(AiMessage.conversation_id == conversation_id)
                .order_by(AiMessage.created_at.desc())
                .limit(HISTORY_MESSAGES)
            )
        )
        .all()
    )
    # Newest-first query, oldest-first for the model.
    return [{"role": role, "content": content} for role, content in reversed(rows)]


@router.post(
    "/conversations/{conversation_id}/messages", response_model=AiMessageOut
)
async def post_message(
    competition_id: str,
    conversation_id: str,
    body: AiMessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> AiMessageOut:
    settings = await _require_ai(db, competition_id)
    competition = await _require_staff_access(db, current_user, competition_id)
    conv = await _conversation_or_404(db, competition_id, conversation_id, current_user)
    if conv.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only post to your own conversation.",
        )
    if conv.closed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This conversation is closed — start a new one.",
        )

    if not await rate_limiter.hit(
        f"ai_admin_msg:{current_user.id}",
        limit=ADMIN_MSG_LIMIT,
        window_seconds=ADMIN_MSG_WINDOW,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You've sent a lot of messages — please wait a bit.",
        )

    used = await db.scalar(
        select(func.count(AiMessage.id)).where(
            AiMessage.conversation_id == conversation_id, AiMessage.role == "user"
        )
    )
    if (used or 0) >= MAX_EXCHANGES:
        conv.closed_at = utcnow()
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This conversation is full — start a new one.",
        )

    if current_user.id in _in_flight:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The assistant is still answering your previous message.",
        )
    _in_flight.add(current_user.id)
    try:
        history = await _history(db, conversation_id)
        user_message = AiMessage(
            competition_id=competition_id,
            conversation_id=conversation_id,
            role="user",
            content=body.content,
        )
        db.add(user_message)
        await db.commit()

        # Load the encrypted key only now, for the turn (deferred otherwise).
        await db.refresh(settings, ["api_key"])

        # Live streaming is best-effort and runs ahead of persistence: chunks go
        # to the WS room as tokens arrive, then the assistant turn is committed
        # below. If that commit fails the client saw the answer but the POST 500s
        # and nothing is stored — the client can re-ask, so it's self-correcting,
        # not a silent divergence. Buffering to make it atomic would defeat live
        # streaming, so the trade-off is deliberate.
        async def on_text(text: str) -> None:
            await manager.broadcast(
                "ai", conversation_id, {"type": "chunk", "text": text}
            )

        try:
            outcome = await run_admin_turn(
                db, current_user, competition, settings, history, body.content,
                now=utcnow(), on_text=on_text,
            )
        except AiProviderError:
            logger.warning("AI provider failed for conversation %s", conversation_id, exc_info=True)
            await manager.broadcast("ai", conversation_id, {"type": "error"})
            await event_bus.emit(
                "ai.error",
                {
                    "competition_id": competition_id,
                    "conversation_id": conversation_id,
                    "user_id": current_user.id,
                    "assistant_type": "admin",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The assistant is unavailable right now — please try again.",
            )

        assistant_message = AiMessage(
            competition_id=competition_id,
            conversation_id=conversation_id,
            role="assistant",
            content=outcome.content,
            tool_calls=[{"name": n} for n in outcome.tools_used] or None,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
        )
        db.add(assistant_message)
        await db.commit()

        await manager.broadcast(
            "ai", conversation_id, {"type": "done", "message_id": assistant_message.id}
        )
        # Commit before emit (audit consumer opens its own session).
        await event_bus.emit(
            "ai.query",
            {
                "competition_id": competition_id,
                "conversation_id": conversation_id,
                "user_id": current_user.id,
                "assistant_type": "admin",
                "input_tokens": outcome.input_tokens,
                "output_tokens": outcome.output_tokens,
                "tool_calls": outcome.tools_used,
            },
        )
        return AiMessageOut.model_validate(assistant_message)
    finally:
        _in_flight.discard(current_user.id)


@router.get("/usage", response_model=AiUsageOut)
async def usage(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AiUsageOut:
    """Per-competition token totals (spec §9) — the "surprise bill" guard. Gated
    like the assistant itself (staff with a tool permission)."""
    await _require_staff_access(db, current_user, competition_id)
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(AiMessage.input_tokens), 0),
                func.coalesce(func.sum(AiMessage.output_tokens), 0),
                func.count(AiMessage.id),
            ).where(AiMessage.competition_id == competition_id)
        )
    ).one()
    return AiUsageOut(input_tokens=row[0], output_tokens=row[1], message_count=row[2])
