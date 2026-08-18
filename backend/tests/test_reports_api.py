"""Post-event report API + generation pipeline (#134, ADR-0030, Stage 4).

Covers the routes (catalog, create gated on `ended`, versioning, history,
download URLs, delete), the RBAC/module gates, and the scheduler processor that
renders a pending report and stores it. The main pipeline test renders HTML-only
so it runs without WeasyPrint; a separate PDF test skips when WeasyPrint's system
libraries aren't installed.
"""

import pytest

from db import SessionLocal
from models.competition import Competition
from models.report import CompetitionReport
from utils import automation_scheduler
from tests.conftest import admin_token
from tests.test_report_data import (
    _auth,
    _challenge,
    _competition,
    _me_id,  # noqa: F401  (kept for parity with the data-test helpers)
    _participant,
    _register,
    _submit,
)

try:
    import weasyprint  # noqa: F401

    _WEASYPRINT = True
except Exception:  # pragma: no cover
    _WEASYPRINT = False


async def _end(comp: str) -> None:
    async with SessionLocal() as db:
        competition = await db.get(Competition, comp)
        competition.status = "ended"
        await db.commit()


async def _ended_comp_with_data(client) -> str:
    comp = await _competition(client)
    easy = await _challenge(client, comp, "Easy", 100, "flag{a}")
    ada = await _participant(client, comp, "ada@example.com")
    await _submit(client, comp, easy, ada, "flag{a}")
    await _end(comp)
    return comp


async def test_report_catalog(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    cat = (
        await client.get(f"/api/competitions/{comp}/reports/catalog", headers=_auth(admin))
    ).json()
    assert {s["id"] for s in cat["sections"]} == {
        "overview", "participation", "results", "challenges", "support", "feedback",
    }
    assert all(s["label"] for s in cat["sections"])
    assert set(cat["presets"]) == {"executive", "technical", "full"}
    assert cat["formats"] == ["pdf", "html"]
    # A user without generate_report can't read it.
    token = await _register(client, "nope@example.com")
    r = await client.get(f"/api/competitions/{comp}/reports/catalog", headers=_auth(token))
    assert r.status_code == 403


async def test_create_requires_ended_competition(client):
    admin = await admin_token(client)
    comp = await _competition(client)  # autostarted → running
    body = {"sections": ["overview"], "formats": ["html"]}
    assert (
        await client.post(f"/api/competitions/{comp}/reports", json=body, headers=_auth(admin))
    ).status_code == 422
    await _end(comp)
    created = await client.post(
        f"/api/competitions/{comp}/reports", json=body, headers=_auth(admin)
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["version"] == 1
    assert payload["status"] == "pending"
    assert payload["config"]["sections"] == ["overview"]
    assert payload["pdf_url"] is None


async def test_versions_increment_and_history_newest_first(client):
    admin = await admin_token(client)
    comp = await _ended_comp_with_data(client)
    for _ in range(2):
        assert (
            await client.post(
                f"/api/competitions/{comp}/reports",
                json={"sections": ["overview"], "formats": ["html"]},
                headers=_auth(admin),
            )
        ).status_code == 201
    history = (
        await client.get(f"/api/competitions/{comp}/reports", headers=_auth(admin))
    ).json()
    assert [r["version"] for r in history] == [2, 1]


async def test_create_requires_generate_report(client):
    comp = await _ended_comp_with_data(client)
    token = await _participant(client, comp, "plain@example.com")  # Participant, no grant
    r = await client.post(
        f"/api/competitions/{comp}/reports",
        json={"sections": ["overview"], "formats": ["html"]},
        headers=_auth(token),
    )
    assert r.status_code == 403


async def test_routes_404_when_module_disabled(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    await client.put(
        f"/api/competitions/{comp}/modules/reports",
        json={"enabled": False},
        headers=_auth(admin),
    )
    assert (
        await client.get(f"/api/competitions/{comp}/reports/catalog", headers=_auth(admin))
    ).status_code == 404
    assert (
        await client.get(f"/api/competitions/{comp}/reports", headers=_auth(admin))
    ).status_code == 404


async def test_generate_html_stores_and_serves_download(client, object_storage, monkeypatch):
    # The scheduler calls get_storage() directly (not via FastAPI DI), so point it
    # at the in-memory double, same as the certificate export test.
    monkeypatch.setattr("storage.get_storage", lambda: object_storage)
    admin = await admin_token(client)
    comp = await _ended_comp_with_data(client)
    created = (
        await client.post(
            f"/api/competitions/{comp}/reports",
            json={
                "sections": ["overview", "participation", "results", "challenges", "support", "feedback"],
                "formats": ["html"],
            },
            headers=_auth(admin),
        )
    ).json()

    await automation_scheduler.process_report_jobs(SessionLocal)

    got = (
        await client.get(
            f"/api/competitions/{comp}/reports/{created['id']}", headers=_auth(admin)
        )
    ).json()
    assert got["status"] == "ready"
    # A same-origin API path, not a presigned object-store URL — so it resolves
    # even where MinIO isn't browser-reachable (the tunnelled demo, #134).
    assert got["html_url"] == (
        f"/api/competitions/{comp}/reports/{created['id']}/download/html"
    )
    assert got["pdf_url"] is None  # html-only request

    # That path streams the stored HTML straight back through the API.
    dl = await client.get(got["html_url"], headers=_auth(admin))
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("text/html")
    assert "attachment" in dl.headers["content-disposition"]
    assert "Executive summary" in dl.text

    # The format that wasn't produced 404s (no pdf_object_key), not 500s.
    assert (
        await client.get(
            f"/api/competitions/{comp}/reports/{created['id']}/download/pdf",
            headers=_auth(admin),
        )
    ).status_code == 404

    async with SessionLocal() as db:
        report = await db.get(CompetitionReport, created["id"])
    assert report.html_object_key and object_storage.exists(report.html_object_key)


async def test_download_gated_by_permission_and_target(client, object_storage, monkeypatch):
    monkeypatch.setattr("storage.get_storage", lambda: object_storage)
    admin = await admin_token(client)
    comp = await _ended_comp_with_data(client)
    created = (
        await client.post(
            f"/api/competitions/{comp}/reports",
            json={"sections": ["overview"], "formats": ["html"]},
            headers=_auth(admin),
        )
    ).json()
    base = f"/api/competitions/{comp}/reports/{created['id']}/download"

    # Pending (not yet rendered) → 404: there is no file to serve yet.
    assert (await client.get(f"{base}/html", headers=_auth(admin))).status_code == 404

    await automation_scheduler.process_report_jobs(SessionLocal)

    # Unknown format is rejected before ever touching storage.
    assert (await client.get(f"{base}/docx", headers=_auth(admin))).status_code == 404
    # Unknown report id → 404.
    assert (
        await client.get(
            f"/api/competitions/{comp}/reports/nope/download/html", headers=_auth(admin)
        )
    ).status_code == 404
    # Ready and downloadable for a manager.
    assert (await client.get(f"{base}/html", headers=_auth(admin))).status_code == 200

    # A participant without generate_report can't pull the bytes — the proxy
    # re-checks the permission on every fetch, unlike a bearer presigned URL.
    participant = await _register(client, "peer@example.com")
    assert (await client.get(f"{base}/html", headers=_auth(participant))).status_code == 403


@pytest.mark.skipif(not _WEASYPRINT, reason="weasyprint/system libs unavailable")
async def test_generate_pdf(client, object_storage, monkeypatch):
    monkeypatch.setattr("storage.get_storage", lambda: object_storage)
    admin = await admin_token(client)
    comp = await _ended_comp_with_data(client)
    created = (
        await client.post(
            f"/api/competitions/{comp}/reports",
            json={"sections": ["overview"], "formats": ["pdf"]},
            headers=_auth(admin),
        )
    ).json()

    await automation_scheduler.process_report_jobs(SessionLocal)

    async with SessionLocal() as db:
        report = await db.get(CompetitionReport, created["id"])
    assert report.status == "ready" and report.pdf_object_key
    assert object_storage.get(report.pdf_object_key)[:5] == b"%PDF-"


async def test_delete_removes_report_and_artifacts(client, object_storage, monkeypatch):
    monkeypatch.setattr("storage.get_storage", lambda: object_storage)
    admin = await admin_token(client)
    comp = await _ended_comp_with_data(client)
    report_id = (
        await client.post(
            f"/api/competitions/{comp}/reports",
            json={"sections": ["overview"], "formats": ["html"]},
            headers=_auth(admin),
        )
    ).json()["id"]
    await automation_scheduler.process_report_jobs(SessionLocal)

    async with SessionLocal() as db:
        key = (await db.get(CompetitionReport, report_id)).html_object_key
    assert object_storage.exists(key)

    r = await client.delete(
        f"/api/competitions/{comp}/reports/{report_id}", headers=_auth(admin)
    )
    assert r.status_code == 204
    assert not object_storage.exists(key)
    assert (
        await client.get(
            f"/api/competitions/{comp}/reports/{report_id}", headers=_auth(admin)
        )
    ).status_code == 404


async def test_render_failure_is_recorded_not_raised(client, object_storage, monkeypatch):
    """A render error is recorded as a failed report and must NOT propagate out of
    the processor (a bad job can't kill the scheduler tick)."""
    monkeypatch.setattr("storage.get_storage", lambda: object_storage)
    admin = await admin_token(client)
    comp = await _ended_comp_with_data(client)
    report_id = (
        await client.post(
            f"/api/competitions/{comp}/reports",
            json={"sections": ["overview"], "formats": ["html"]},
            headers=_auth(admin),
        )
    ).json()["id"]

    def boom(*args, **kwargs):
        raise RuntimeError("render exploded")

    monkeypatch.setattr("plugins.reports.render.render_report", boom)
    await automation_scheduler.process_report_jobs(SessionLocal)  # must not raise

    async with SessionLocal() as db:
        report = await db.get(CompetitionReport, report_id)
    assert report.status == "failed"
    assert "render exploded" in (report.error or "")


async def test_version_unique_per_competition(client):
    """The (competition_id, version) constraint holds the monotonic invariant."""
    from sqlalchemy.exc import IntegrityError

    comp = await _ended_comp_with_data(client)
    async with SessionLocal() as db:
        db.add(CompetitionReport(competition_id=comp, version=1, status="pending", config={}))
        db.add(CompetitionReport(competition_id=comp, version=1, status="pending", config={}))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_deleting_competition_cleans_report_artifacts(client, object_storage, monkeypatch):
    """Hard-deleting a competition removes its report artefacts from storage — not
    just the DB rows (which cascade)."""
    monkeypatch.setattr("storage.get_storage", lambda: object_storage)
    admin = await admin_token(client)
    comp = await _ended_comp_with_data(client)
    report_id = (
        await client.post(
            f"/api/competitions/{comp}/reports",
            json={"sections": ["overview"], "formats": ["html"]},
            headers=_auth(admin),
        )
    ).json()["id"]
    await automation_scheduler.process_report_jobs(SessionLocal)
    async with SessionLocal() as db:
        key = (await db.get(CompetitionReport, report_id)).html_object_key
    assert object_storage.exists(key)

    deleted = await client.delete(f"/api/competitions/{comp}", headers=_auth(admin))
    assert deleted.status_code in (200, 204)
    assert not object_storage.exists(key)
