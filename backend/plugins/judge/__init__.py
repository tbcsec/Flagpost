"""Code judge module (#446, ADR-0042).

The eighth optional module. Ships **inert**: routes mount site-wide but nothing
judges until an operator configures an executor endpoint and at least one
language and enables it (``JudgeSettings``), on top of the per-competition
module toggle — the instancing / AI posture (ADR-0036, ADR-0023).

#447 wires the site configuration surface and problem authoring (programming
challenges and their test data). The executor and its worker loop (#448) arrive
in a later slice; the
worker deliberately does *not* run on the event bus, whose per-handler timeout
would cut real judgings off (ADR-0042 §2).
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.judge_admin import router as judge_admin_router
    from routers.judge_problems import router as judge_problems_router

    app.include_router(judge_admin_router)
    app.include_router(judge_problems_router)
