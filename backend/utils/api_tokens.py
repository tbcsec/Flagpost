"""Shared personal-API-token lifecycle helpers (issue #75).

Lives outside ``routers/api_tokens.py`` because the credential-invalidating
paths that need it are elsewhere — banning an account, an administrator
resetting someone's password, a self-service password reset. Keeping the
revocation in one place is what stops those paths drifting apart from the
token router's own revoke.

Callers mutate, then commit, then emit — the house commit-before-broadcast
order — so these helpers only mark rows and hand back what changed.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import utcnow
from models.api_token import ApiToken
from utils.event_bus import event_bus


async def revoke_user_api_tokens(db: AsyncSession, user_id: str) -> list[str]:
    """Revoke every live token belonging to ``user_id``.

    Returns the ids revoked, so the caller can emit one ``api_token.revoked``
    per token after committing. Already-revoked tokens are left alone, so this
    is idempotent and safe to call on paths that may run twice.
    """
    tokens = (
        await db.scalars(
            select(ApiToken).where(
                ApiToken.user_id == user_id,
                ApiToken.revoked_at.is_(None),
            )
        )
    ).all()
    now = utcnow()
    for token in tokens:
        token.revoked_at = now
    return [token.id for token in tokens]


async def emit_revoked(token_ids: list[str], *, user_id: str, actor_id: str) -> None:
    """Emit one ``api_token.revoked`` per id, after the caller has committed."""
    for token_id in token_ids:
        await event_bus.emit(
            "api_token.revoked",
            {
                "api_token_id": token_id,
                "user_id": user_id,
                "actor_user_id": actor_id,
            },
        )
