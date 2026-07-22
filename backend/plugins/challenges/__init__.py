"""Challenges module (§11) — the feature the module loader was built for.

Provides the challenge and category routers (categories exist to organize
challenges, ROADMAP #9, so they ship in this module rather than their own).
Domain code lives in routers/schemas/models per §14.

Also owns the presence-only ``challenge/<challenge_id>`` WS room (§4.1): no data
broadcast, just the "N people viewing this challenge" live set. Authorized on
``challenge_view`` for the challenge's competition, exactly like the REST reads.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from auth.deps import user_has_permission
    from models.challenge import Challenge
    from realtime import register_room_type
    from routers.attachments import router as attachments_router
    from routers.categories import router as categories_router
    from routers.challenges import router as challenges_router
    from routers.submissions import router as submissions_router

    app.include_router(challenges_router)
    app.include_router(categories_router)
    app.include_router(attachments_router)
    # Flag submission + scoring (Phase 6) — competitor-facing, same module.
    app.include_router(submissions_router)

    async def authorize_challenge(db, user, challenge_id: str) -> bool:
        challenge = await db.get(Challenge, challenge_id)
        if challenge is None:
            return False
        return await user_has_permission(
            db, user.id, "challenge_view", challenge.competition_id
        )

    async def challenge_presence_member(db, user, challenge_id: str, mode: str) -> dict:
        challenge = await db.get(Challenge, challenge_id)
        # Staff (challenge_edit) vs competitor, so the indicator can distinguish
        # an organiser peeking from another competitor on the same challenge.
        is_staff = challenge is not None and await user_has_permission(
            db, user.id, "challenge_edit", challenge.competition_id
        )
        return {
            "id": user.id,
            "name": user.display_name,
            "role": "staff" if is_staff else "participant",
            "mode": mode,
        }

    register_room_type(
        "challenge",
        authorize=authorize_challenge,
        presence_member=challenge_presence_member,
    )
