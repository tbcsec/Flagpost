"""Skills module (#364, ADR-0039, §11.3).

Required-core so its routes are always mounted, but the FEATURE is site-wide-
toggled by ``site_settings.skills_enabled`` (not a per-competition module switch)
because the skills web spans every competition. Mounts the self + admin skills
reads; the cross-competition aggregation reuses data the required-core modules
already record, so there's no per-solve instrumentation here — only cache
invalidation, wired below.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.skills import admin_router, me_router

    app.include_router(me_router)
    app.include_router(admin_router)

    # A new solve or category change moves the web, so drop the cross-competition
    # cache on those events (foreground, like the scoring plugin's board
    # invalidation) — else a read could serve a stale web until the TTL lapses.
    from utils.skills import invalidate_skills

    async def _invalidate(_event_name: str, _payload: dict) -> None:
        invalidate_skills()

    for event_type in (
        "challenge.solved",
        "challenge.deleted",
        "challenge.updated",
        "category.created",
        "category.deleted",
        # The enriched matrix (#435) also derives *opportunity*: `available`
        # counts published challenges across a user's member competitions, so a
        # publish or a new membership moves cells too.
        "challenge.published",
        "competition.member_joined",
        # v2 (#440): wrong guesses and hint reveals are cell signals now, so a
        # graded attempt or a reveal must drop the cache like a solve does.
        "challenge.attempted",
        "hint.released",
        # A rejudge or override taking a solve away (#450) moves it back.
        "challenge.solve_revoked",
    ):
        event_bus.subscribe(event_type, _invalidate, owner="skills")
