"""Code judge module (#446, ADR-0042).

The eighth optional module. Ships **inert**: routes mount site-wide but nothing
judges until an operator configures an executor endpoint and at least one
language and enables it (``JudgeSettings``), on top of the per-competition
module toggle — the instancing / AI posture (ADR-0036, ADR-0023).

#447 wired the site configuration surface and problem authoring (programming
challenges and their test data); #448 adds the executor
(``utils/judge_executor*``, the Go harness in ``judge_harness/``) and then the
submission queue and its worker loop. The worker deliberately does *not* run on
the event bus, whose per-handler timeout would cut real judgings off (ADR-0042
§2).
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.judge_admin import router as judge_admin_router
    from routers.judge_problems import router as judge_problems_router
    from routers.judge_jury import router as judge_jury_router
    from routers.judge_submissions import router as judge_submissions_router

    app.include_router(judge_admin_router)
    app.include_router(judge_problems_router)
    app.include_router(judge_submissions_router)
    app.include_router(judge_jury_router)
