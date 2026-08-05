"""Assistant conversations — admin and competitor (#98, ADR-0023 Phase 2/3).

A user opens a conversation of a given ``assistant_type`` for a competition, then
posts messages; each message runs one turn (tool calls execute as *that user* —
§5.4) and delivers the answer over the ``ai`` WebSocket room while the POST
persists the result. Read-only throughout: the only writes are the
conversation/message rows, which carry their own ``ai.query`` usage event (never
message content, §4).

Gating dispatches on the conversation type. Both require the module configured +
enabled (site master switch) and enabled for the competition. Then:

- **admin** — the caller can see the competition and holds a tool permission
  (:func:`can_use_admin_assistant`).
- **competitor** — the competition is *running* (owner decision: active-only),
  its competitor assistant is enabled, and the caller is a player
  (``challenge_view``).

Per-user message-rate (admin 60/h, competitor 20/h), single-in-flight, and
conversation-length caps apply either way (§9).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, user_has_permission
from db import get_db, utcnow
from models.ai import (
    AI_SETTINGS_ID,
    AiCompetitionSettings,
    AiConversation,
    AiDisclosureAcceptance,
    AiMessage,
    AiSettings,
)
from models.competition import Competition
from models.user import User
from plugins.loader import is_module_enabled
from ratelimit import get_rate_limiter
from ratelimit.base import RateLimiter
from realtime import manager
from schemas.ai import (
    AiAvailabilityOut,
    AiConversationCreate,
    AiConversationDetail,
    AiConversationOut,
    AiMessageCreate,
    AiMessageOut,
    AiUsageOut,
)
from utils.ai.assistant import run_admin_turn, run_competitor_turn
from utils.ai.client import AiProviderError
from utils.ai.tools import can_use_admin_assistant
from utils.competitions import get_visible_competition, is_competition_active
from utils.event_bus import event_bus

logger = logging.getLogger("ai")

router = APIRouter(prefix="/api/competitions/{competition_id}/ai", tags=["ai"])

# Conversation length cap: 20 exchanges, then the conversation closes and a new
# message must start a fresh one (spec §9).
MAX_EXCHANGES = 20
# History window handed to the model — the last 20 exchanges (user+assistant).
HISTORY_MESSAGES = 40
# Per-user message caps (spec §9): the competitor assistant is a tighter hint
# channel and a proxy to a paid endpoint, so it gets a lower ceiling.
ADMIN_MSG_LIMIT = 60
COMPETITOR_MSG_LIMIT = 20
MSG_WINDOW = 3600

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


async def _visible_competition_or_404(
    db: AsyncSession, user: User, competition_id: str
) -> Competition:
    competition = await get_visible_competition(db, competition_id, user)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


async def _require_staff_access(db: AsyncSession, user: User, competition_id: str):
    competition = await _visible_competition_or_404(db, user, competition_id)
    if not await can_use_admin_assistant(db, user, competition_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to the administrator assistant here.",
        )
    return competition


async def _competitor_enabled(db: AsyncSession, competition_id: str) -> bool:
    row = await db.get(AiCompetitionSettings, competition_id)
    return bool(row and row.competitor_enabled)


async def _require_competitor_access(db: AsyncSession, user: User, competition_id: str):
    """Gate the competitor assistant: the competition must be visible to the
    caller, currently *running* (owner decision: active-only), have its competitor
    assistant enabled, and the caller must be a player here (``challenge_view``)."""
    competition = await _visible_competition_or_404(db, user, competition_id)
    if not is_competition_active(competition):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The assistant is available only while the competition is running.",
        )
    if not await _competitor_enabled(db, competition_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The competitor assistant isn't enabled for this competition.",
        )
    if not await user_has_permission(db, user.id, "challenge_view", competition_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The competitor assistant is for participants of this competition.",
        )
    return competition


async def _require_access(
    db: AsyncSession, user: User, competition_id: str, assistant_type: str
):
    """Dispatch to the gate for the requested assistant type."""
    if assistant_type == "competitor":
        return await _require_competitor_access(db, user, competition_id)
    return await _require_staff_access(db, user, competition_id)


async def _conversation_or_404(
    db: AsyncSession, competition_id: str, conversation_id: str, user: User
) -> AiConversation:
    conv = await db.get(AiConversation, conversation_id)
    if conv is None or conv.competition_id != competition_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    if conv.user_id == user.id:
        return conv
    # A non-owner may read only via the right oversight grant: competitor
    # transcripts need ai_view_transcripts; admin ones need admin-assistant access.
    if conv.assistant_type == "competitor":
        allowed = await user_has_permission(
            db, user.id, "ai_view_transcripts", competition_id
        )
    else:
        allowed = await can_use_admin_assistant(db, user, competition_id)
    if not allowed:
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
    """Which assistant(s) the caller may open here — the audience-aware launcher
    gate. Never raises on "off": both false when the module is
    unconfigured/disabled, so a competitor probing it learns only that nothing is
    available to them."""
    settings = await db.get(AiSettings, AI_SETTINGS_ID)
    configured = bool(
        settings and settings.enabled and settings.base_url and settings.model
    )
    if not configured or not await is_module_enabled(db, "ai", competition_id):
        return AiAvailabilityOut(admin=False, competitor=False)
    competition = await get_visible_competition(db, competition_id, current_user)
    if competition is None:
        return AiAvailabilityOut(admin=False, competitor=False)
    admin = await can_use_admin_assistant(db, current_user, competition_id)
    competitor = (
        is_competition_active(competition)
        and await _competitor_enabled(db, competition_id)
        and await user_has_permission(
            db, current_user.id, "challenge_view", competition_id
        )
    )
    accepted = competitor and (
        await db.get(AiDisclosureAcceptance, current_user.id) is not None
    )
    return AiAvailabilityOut(
        admin=admin, competitor=competitor, competitor_disclosure_accepted=accepted
    )


@router.post("/disclosure/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_disclosure(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Record the caller's one-time acceptance of the competitor-assistant
    disclosure (their messages go to the configured model endpoint; transcripts
    are staff-reviewable). Idempotent, and gated exactly like the assistant it
    unlocks, so only a real competitor in a running, enabled competition can
    record one. Site-wide per user — the disclosed facts are install-level."""
    await _require_ai(db, competition_id)
    await _require_competitor_access(db, current_user, competition_id)
    if await db.get(AiDisclosureAcceptance, current_user.id) is not None:
        return
    db.add(AiDisclosureAcceptance(user_id=current_user.id))
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race with a concurrent accept (two tabs): the row exists, which
        # is exactly the promised end-state — swallow it so the route stays
        # idempotent, and skip the emit (the winning request emitted).
        await db.rollback()
        return
    # Commit before emit (audit consumer opens its own session).
    await event_bus.emit(
        "ai.disclosure_accepted",
        {"competition_id": competition_id, "user_id": current_user.id},
    )


@router.post(
    "/conversations",
    response_model=AiConversationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    competition_id: str,
    body: AiConversationCreate | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AiConversationOut:
    assistant_type = (body or AiConversationCreate()).assistant_type
    await _require_ai(db, competition_id)
    await _require_access(db, current_user, competition_id, assistant_type)
    if assistant_type == "competitor" and (
        await db.get(AiDisclosureAcceptance, current_user.id) is None
    ):
        # The first-run disclosure gates the channel server-side too, so the
        # recorded acceptance is meaningful rather than a UI courtesy.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Accept the assistant disclosure first.",
        )
    conv = AiConversation(
        competition_id=competition_id,
        user_id=current_user.id,
        assistant_type=assistant_type,
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


async def _run_turn_for(
    conv: AiConversation,
    db: AsyncSession,
    user: User,
    competition: Competition,
    settings: AiSettings,
    history: list[dict],
    content: str,
    on_text,
):
    """Dispatch to the assistant appropriate to the conversation type. The
    competitor turn additionally loads the per-competition controls (guidance
    level + challenge-metadata toggle)."""
    if conv.assistant_type == "competitor":
        comp_settings = await db.get(AiCompetitionSettings, competition.id)
        return await run_competitor_turn(
            db, user, competition, settings, comp_settings, history, content,
            now=utcnow(), on_text=on_text,
        )
    return await run_admin_turn(
        db, user, competition, settings, history, content,
        now=utcnow(), on_text=on_text,
    )


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
    conv = await _conversation_or_404(db, competition_id, conversation_id, current_user)
    if conv.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only post to your own conversation.",
        )
    # Re-gate at message time by the conversation's type — a competitor turn is
    # refused once the competition stops running or the toggle is turned off.
    competition = await _require_access(
        db, current_user, competition_id, conv.assistant_type
    )
    if conv.closed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This conversation is closed — start a new one.",
        )

    is_competitor = conv.assistant_type == "competitor"
    rl_key = ("ai_competitor_msg:" if is_competitor else "ai_admin_msg:") + current_user.id
    rl_limit = COMPETITOR_MSG_LIMIT if is_competitor else ADMIN_MSG_LIMIT
    if not await rate_limiter.hit(rl_key, limit=rl_limit, window_seconds=MSG_WINDOW):
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

        # Delivery is best-effort and runs ahead of persistence: the admin turn
        # streams chunks live; the competitor turn delivers one flag-scanned block
        # (see run_competitor_turn). Either way the answer reaches the WS room,
        # then the turn is committed below. If that commit fails the client saw
        # the answer but the POST 500s and nothing is stored — self-correcting
        # (re-ask), not a silent divergence.
        async def on_text(text: str) -> None:
            await manager.broadcast(
                "ai", conversation_id, {"type": "chunk", "text": text}
            )

        try:
            outcome = await _run_turn_for(
                conv, db, current_user, competition, settings, history,
                body.content, on_text,
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
                    "assistant_type": conv.assistant_type,
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
                "assistant_type": conv.assistant_type,
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
