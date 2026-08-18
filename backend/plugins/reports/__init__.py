"""Post-event reports module (ROADMAP #134, ADR-0030) — the sixth optional module.

Turns a *finished* competition into a branded, downloadable PDF/HTML report
(executive summary, participation, results, challenge analysis, support). Not
required-core, so it carries the per-competition enable/disable toggle
(``competition_modules`` — default ON) and appears in the at-creation module
picker (#252). Generation is gated on the competition being ``ended`` (ADR-0028)
and renders off the request path with WeasyPrint (ADR-0030).

Staged build (#134): this is the foundation — the manifest, the
:class:`~models.report.CompetitionReport` data model, and the ``generate_report``
permission. The aggregation layer, the WeasyPrint renderer, and the routes mount
in later stages on this branch; ``setup`` grows an ``app.include_router`` call
then (and the manifest's ``provides.routes`` flips to true).
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    # No routes yet — see the module docstring. The loader still records the
    # manifest (so the module is toggleable and shows in the catalog), which is
    # all Stage 1 needs.
    return None
