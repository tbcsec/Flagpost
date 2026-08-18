"""Post-event reports module (ROADMAP #134, ADR-0030) — the sixth optional module.

Turns a *finished* competition into a branded, downloadable PDF/HTML report
(executive summary, participation, results, challenge analysis, support). Not
required-core, so it carries the per-competition enable/disable toggle
(``competition_modules`` — default ON) and appears in the at-creation module
picker (#252). Generation is gated on the competition being ``ended`` (ADR-0028)
and renders off the request path with WeasyPrint (ADR-0030).

Rendering (Jinja2 → WeasyPrint) lives in ``render.py`` and the aggregation in
``utils.report_data``; the routes below are organiser-facing and gated on
``generate_report`` + the module toggle (§11.3). Generation runs off the request
path on the kernel scheduler tick (``utils.automation_scheduler``), not here, so
it works in both single-worker and the multi-worker sidecar (ADR-0025/0026).
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.reports import router

    app.include_router(router)
