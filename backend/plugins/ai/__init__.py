"""AI Assistants module (#98, ADR-0023).

Mounts the admin provider-config surface (Phase 1) and the administrator
assistant's conversation API + WebSocket room (Phase 2). The module ships inert —
the site master switch defaults off — so nothing calls the configured endpoint
until an administrator sets one up and enables it. The competitor assistant and
its per-competition controls arrive in a later phase.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from realtime import register_room_type
    from routers.ai_admin import router as ai_admin_router
    from routers.ai_conversations import router as ai_conversations_router

    app.include_router(ai_admin_router)
    app.include_router(ai_conversations_router)

    async def authorize_ai_room(db, user, conversation_id: str) -> bool:
        # A conversation's live stream is joinable by its owner, or by staff who
        # can use the assistant in that competition (the transcript-review lens).
        from models.ai import AiConversation
        from utils.ai.tools import can_use_admin_assistant

        conv = await db.get(AiConversation, conversation_id)
        if conv is None:
            return False
        if conv.user_id == user.id:
            return True
        return await can_use_admin_assistant(db, user, conv.competition_id)

    register_room_type("ai", authorize=authorize_ai_room)
