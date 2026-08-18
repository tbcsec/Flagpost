"""Post-event reports module foundation (#134, ADR-0030).

Stage 1 only: the optional ``reports`` module is registered (so it is
per-competition toggleable and appears in the at-creation module picker, #252),
the :class:`CompetitionReport` model persists with sane defaults, and the
competition-scoped ``generate_report`` permission exists and is seeded into the
built-in operational roles. The aggregation/render/API layers land in later
stages.
"""

from sqlalchemy import select

from db import SessionLocal
from models.report import CompetitionReport
from models.role import Role
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _competition(client) -> str:
    admin = await admin_token(client)
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def test_reports_module_in_optional_catalog(client):
    """The `reports` module is optional and shows in the at-creation picker
    (#252) with a display name and a one-line description."""
    admin = await admin_token(client)
    entries = (await client.get("/api/modules", headers=_auth(admin))).json()
    reports = next((m for m in entries if m["id"] == "reports"), None)
    assert reports is not None, "reports module missing from the optional catalog"
    assert reports["name"]
    assert reports["description"]


async def test_generate_report_permission_in_catalog(client):
    """The new grant is in the catalog, competition-scoped, under Competition
    Management — so the role editor can delegate it."""
    admin = await admin_token(client)
    cat = (await client.get("/api/roles/catalog", headers=_auth(admin))).json()
    entry = next((c for c in cat if c["key"] == "generate_report"), None)
    assert entry is not None
    assert entry["scope"] == "competition"
    assert entry["category"] == "Competition Management"


async def test_judge_has_generate_report(client):
    """Seeded into Judge (full operational control) — and thus reaches existing
    installs via the startup role re-sync, not a data migration."""
    async with SessionLocal() as db:
        judge = await db.scalar(select(Role).where(Role.name == "Judge"))
        assert judge is not None
        assert "generate_report" in judge.permissions


async def test_competition_report_persists_with_defaults(client):
    """The row round-trips and carries its defaults (version 1, pending, no
    artefacts yet) — proving the table is in Base.metadata and the mixins wire up."""
    comp = await _competition(client)
    async with SessionLocal() as db:
        report = CompetitionReport(
            competition_id=comp,
            config={"preset": "executive", "sections": ["summary"], "options": {}},
        )
        db.add(report)
        await db.commit()
        report_id = report.id

    async with SessionLocal() as db:
        stored = await db.get(CompetitionReport, report_id)
        assert stored is not None
        assert stored.competition_id == comp
        assert stored.version == 1
        assert stored.status == "pending"
        assert stored.config["preset"] == "executive"
        assert stored.created_at is not None
        assert stored.pdf_object_key is None
        assert stored.html_object_key is None
