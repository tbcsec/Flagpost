"""Certificates module (#219, ADR-0027): module gating, RBAC, template CRUD +
input hardening, the real-renderer preview, manual + scheduled release (with
idempotency + module gating), notifications, self-scoped download, the
cross-competition list, recipient rules, bulk ZIP export, upload hardening, and
the unauthenticated asset endpoints."""

import io
import zipfile
from datetime import timedelta

from sqlalchemy import select

from db import SessionLocal, utcnow
from models.certificate import CertificateExportJob, CertificateTemplate
from models.competition import Competition
from models.notification import Notification
from tests.conftest import admin_token

import main  # noqa: F401 — importing loads modules so is_module_enabled sees "certificates"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> str:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return r.json()["access_token"]


async def _competition(client, mode: str = "individual") -> str:
    admin = await admin_token(client)
    r = await client.post(
        "/api/competitions",
        json={"name": "CTF", "participation_mode": mode, "visibility": "public"},
        headers=_auth(admin),
    )
    return r.json()["id"]


async def _participant(client, comp: str, email: str) -> str:
    token = await _register(client, email)
    r = await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    assert r.status_code == 200, r.text
    return token


async def _published_challenge(client, comp, admin, flag="flag{win}", points=100) -> str:
    r = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "Chal", "points": points, "flag": flag},
        headers=_auth(admin),
    )
    chal = r.json()["id"]
    await client.post(f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin))
    return chal


def _body(**over) -> dict:
    body = {
        "background_kind": "preset",
        "background_preset": "classic",
        "background_color": "#ffffff",
        "elements": [{"type": "token", "x": 10, "y": 40, "width": 80, "token": "recipient_name"}],
        "recipient_rule": "all",
        "release_mode": "manual",
        "release_delay_minutes": 0,
    }
    body.update(over)
    return body


def _png(w=1400, h=990, color=(200, 180, 140)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


async def _cert_base(client, comp: str) -> str:
    return f"/api/competitions/{comp}/certificates"


# --- gating + RBAC ---------------------------------------------------------


async def test_routes_404_when_module_disabled(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    r = await client.put(
        f"/api/competitions/{comp}/modules/certificates",
        json={"enabled": False},
        headers=_auth(admin),
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/competitions/{comp}/certificates/template", headers=_auth(admin))
    assert r.status_code == 404


async def test_participant_cannot_manage(client):
    comp = await _competition(client)
    p = await _participant(client, comp, "p1@x.com")
    r = await client.put(
        f"/api/competitions/{comp}/certificates/template", json=_body(), headers=_auth(p)
    )
    assert r.status_code == 403


# --- template CRUD + hardening ---------------------------------------------


async def test_template_default_then_upsert(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    r = await client.get(f"/api/competitions/{comp}/certificates/template", headers=_auth(admin))
    assert r.status_code == 200 and r.json()["id"] == ""  # unsaved default
    r = await client.put(
        f"/api/competitions/{comp}/certificates/template", json=_body(), headers=_auth(admin)
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] and r.json()["background_preset"] == "classic"
    r = await client.get(f"/api/competitions/{comp}/certificates/template", headers=_auth(admin))
    assert r.json()["recipient_rule"] == "all" and len(r.json()["elements"]) == 1


async def test_rejects_unknown_token_and_bad_color(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    for bad in (
        _body(elements=[{"type": "token", "x": 1, "y": 1, "token": "BOGUS"}]),
        _body(elements=[{"type": "text", "x": 1, "y": 1, "text": "hi", "color": "red"}]),
        _body(elements=[{"type": "token", "x": 200, "y": 1, "token": "points"}]),
        _body(background_color="nothex"),
    ):
        r = await client.put(
            f"/api/competitions/{comp}/certificates/template", json=bad, headers=_auth(admin)
        )
        assert r.status_code == 422, bad


async def test_select_upload_without_image_400(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    r = await client.put(
        f"/api/competitions/{comp}/certificates/template",
        json=_body(background_kind="upload"),
        headers=_auth(admin),
    )
    assert r.status_code == 400


async def test_preview_returns_png(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    r = await client.post(
        f"/api/competitions/{comp}/certificates/preview", json=_body(), headers=_auth(admin)
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


# --- release + self download -----------------------------------------------


async def test_manual_release_notifies_and_self_download(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    p = await _participant(client, comp, "ada@x.com")
    base = f"/api/competitions/{comp}/certificates"
    await client.put(f"{base}/template", json=_body(), headers=_auth(admin))

    # Before release: nothing for the participant.
    assert (await client.get(f"{base}/me", headers=_auth(p))).json()["available"] is False
    assert (await client.get(f"{base}/me/download", headers=_auth(p))).status_code == 404

    r = await client.post(f"{base}/release", headers=_auth(admin))
    assert r.status_code == 200 and r.json()["released"] is True

    assert (await client.get(f"{base}/me", headers=_auth(p))).json()["available"] is True
    dl = await client.get(f"{base}/me/download", headers=_auth(p))
    assert dl.status_code == 200 and dl.content[:8] == b"\x89PNG\r\n\x1a\n"

    async with SessionLocal() as db:
        notes = (
            await db.execute(
                select(Notification).where(Notification.type == "certificate.released")
            )
        ).scalars().all()
    assert len(notes) == 1  # exactly the one participant

    mine = await client.get("/api/me/certificates", headers=_auth(p))
    assert any(c["competition_id"] == comp for c in mine.json())


async def test_release_is_idempotent(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    await _participant(client, comp, "b@x.com")
    base = f"/api/competitions/{comp}/certificates"
    await client.put(f"{base}/template", json=_body(), headers=_auth(admin))
    await client.post(f"{base}/release", headers=_auth(admin))
    await client.post(f"{base}/release", headers=_auth(admin))  # second time
    async with SessionLocal() as db:
        notes = (
            await db.execute(
                select(Notification).where(Notification.type == "certificate.released")
            )
        ).scalars().all()
    assert len(notes) == 1  # not re-notified


async def test_non_participant_gets_no_certificate(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    await _participant(client, comp, "in@x.com")
    outsider = await _register(client, "out@x.com")  # never joined
    base = f"/api/competitions/{comp}/certificates"
    await client.put(f"{base}/template", json=_body(), headers=_auth(admin))
    await client.post(f"{base}/release", headers=_auth(admin))
    assert (await client.get(f"{base}/me", headers=_auth(outsider))).json()["available"] is False
    assert (await client.get(f"{base}/me/download", headers=_auth(outsider))).status_code == 404


async def test_recipient_rule_solvers(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    chal = await _published_challenge(client, comp, admin, flag="flag{win}")
    solver = await _participant(client, comp, "solver@x.com")
    idle = await _participant(client, comp, "idle@x.com")
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{win}"},
        headers=_auth(solver),
    )
    base = f"/api/competitions/{comp}/certificates"
    await client.put(f"{base}/template", json=_body(recipient_rule="solvers"), headers=_auth(admin))
    await client.post(f"{base}/release", headers=_auth(admin))
    assert (await client.get(f"{base}/me", headers=_auth(solver))).json()["available"] is True
    assert (await client.get(f"{base}/me", headers=_auth(idle))).json()["available"] is False


async def test_team_mode_release_and_download(client):
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "T", "participation_mode": "team", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]
    member = await _register(client, "cap@x.com")
    await client.post(
        f"/api/competitions/{comp}/teams", json={"name": "Hackers"}, headers=_auth(member)
    )
    base = f"/api/competitions/{comp}/certificates"
    await client.put(f"{base}/template", json=_body(), headers=_auth(admin))
    await client.post(f"{base}/release", headers=_auth(admin))
    assert (await client.get(f"{base}/me", headers=_auth(member))).json()["available"] is True
    dl = await client.get(f"{base}/me/download", headers=_auth(member))
    assert dl.status_code == 200 and dl.content[:8] == b"\x89PNG\r\n\x1a\n"


# --- scheduled release tick ------------------------------------------------


async def _set_end(comp: str, delta: timedelta) -> None:
    async with SessionLocal() as db:
        c = await db.get(Competition, comp)
        c.end_at = utcnow() + delta
        await db.commit()


async def test_scheduled_release_on_end(client):
    from utils.automation_scheduler import release_scheduled_certificates

    admin = await admin_token(client)
    comp = await _competition(client)
    p = await _participant(client, comp, "s@x.com")
    base = f"/api/competitions/{comp}/certificates"
    await client.put(f"{base}/template", json=_body(release_mode="on_end"), headers=_auth(admin))
    await _set_end(comp, timedelta(minutes=-5))  # already ended

    await release_scheduled_certificates(SessionLocal)
    assert (await client.get(f"{base}/me", headers=_auth(p))).json()["available"] is True

    # Idempotent: a second tick doesn't re-notify.
    await release_scheduled_certificates(SessionLocal)
    async with SessionLocal() as db:
        notes = (
            await db.execute(
                select(Notification).where(Notification.type == "certificate.released")
            )
        ).scalars().all()
    assert len(notes) == 1


async def test_scheduled_release_end_delay_waits(client):
    from utils.automation_scheduler import release_scheduled_certificates

    admin = await admin_token(client)
    comp = await _competition(client)
    await _participant(client, comp, "d@x.com")
    base = f"/api/competitions/{comp}/certificates"
    await client.put(
        f"{base}/template",
        json=_body(release_mode="end_delay", release_delay_minutes=60),
        headers=_auth(admin),
    )
    await _set_end(comp, timedelta(minutes=-30))  # ended 30m ago, delay 60m → not yet
    await release_scheduled_certificates(SessionLocal)
    async with SessionLocal() as db:
        t = await db.scalar(select(CertificateTemplate).where(CertificateTemplate.competition_id == comp))
        assert t.released_at is None
    await _set_end(comp, timedelta(minutes=-90))  # now past end+delay
    await release_scheduled_certificates(SessionLocal)
    async with SessionLocal() as db:
        t = await db.scalar(select(CertificateTemplate).where(CertificateTemplate.competition_id == comp))
        assert t.released_at is not None


async def test_scheduled_release_gated_on_module(client):
    from utils.automation_scheduler import release_scheduled_certificates

    admin = await admin_token(client)
    comp = await _competition(client)
    await _participant(client, comp, "g@x.com")
    base = f"/api/competitions/{comp}/certificates"
    await client.put(f"{base}/template", json=_body(release_mode="on_end"), headers=_auth(admin))
    await client.put(
        f"/api/competitions/{comp}/modules/certificates",
        json={"enabled": False},
        headers=_auth(admin),
    )
    await _set_end(comp, timedelta(minutes=-5))
    await release_scheduled_certificates(SessionLocal)
    async with SessionLocal() as db:
        t = await db.scalar(select(CertificateTemplate).where(CertificateTemplate.competition_id == comp))
        assert t.released_at is None  # disabled module ⇒ not released


# --- bulk export -----------------------------------------------------------


async def test_bulk_export_zip(client, object_storage, monkeypatch):
    from utils import automation_scheduler

    # The scheduler calls get_storage() directly (not via FastAPI DI), so point it
    # at the same in-memory double the routes use.
    monkeypatch.setattr("storage.get_storage", lambda: object_storage)

    admin = await admin_token(client)
    comp = await _competition(client)
    await _participant(client, comp, "e1@x.com")
    await _participant(client, comp, "e2@x.com")
    base = f"/api/competitions/{comp}/certificates"
    await client.put(f"{base}/template", json=_body(), headers=_auth(admin))
    r = await client.post(f"{base}/exports", headers=_auth(admin))
    assert r.status_code == 201 and r.json()["status"] == "pending"
    job_id = r.json()["id"]

    await automation_scheduler.process_certificate_exports(SessionLocal)

    r = await client.get(f"{base}/exports/{job_id}", headers=_auth(admin))
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert r.json()["download_url"]

    async with SessionLocal() as db:
        job = await db.get(CertificateExportJob, job_id)
    data = object_storage.get(job.object_key)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert len(names) == 2 and all(n.endswith(".png") for n in names)


async def test_export_scoped_to_competition(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    other = await _competition(client)
    base = f"/api/competitions/{comp}/certificates"
    await client.put(f"{base}/template", json=_body(), headers=_auth(admin))
    job_id = (await client.post(f"{base}/exports", headers=_auth(admin))).json()["id"]
    # The same job id under a different competition path must 404.
    r = await client.get(
        f"/api/competitions/{other}/certificates/exports/{job_id}", headers=_auth(admin)
    )
    assert r.status_code == 404


# --- upload hardening + media scope ----------------------------------------


async def test_background_upload_hardening(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    base = f"/api/competitions/{comp}/certificates"
    # Not an image → 415.
    r = await client.post(
        f"{base}/background",
        files={"file": ("x.txt", b"not an image", "text/plain")},
        headers=_auth(admin),
    )
    assert r.status_code == 415
    # Portrait → 422 (not landscape A4-ish).
    r = await client.post(
        f"{base}/background",
        files={"file": ("p.png", _png(800, 1200), "image/png")},
        headers=_auth(admin),
    )
    assert r.status_code == 422
    # Valid landscape → stored.
    r = await client.post(
        f"{base}/background",
        files={"file": ("bg.png", _png(1400, 990), "image/png")},
        headers=_auth(admin),
    )
    assert r.status_code == 200
    assert r.json()["has_background_image"] is True and r.json()["background_kind"] == "upload"


async def test_media_rejects_foreign_key(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    r = await client.get(
        f"/api/competitions/{comp}/certificates/media",
        params={"key": "SOME-OTHER-COMP/certificates/x.png"},
        headers=_auth(admin),
    )
    assert r.status_code == 403


# --- assets + pure helpers -------------------------------------------------


async def test_asset_endpoints(client):
    r = await client.get("/api/certificate-assets/manifest")
    assert r.status_code == 200 and "tokens" in r.json() and "fonts" in r.json()
    r = await client.get("/api/certificate-assets/fonts/serif/regular")
    assert r.status_code == 200 and r.content[:4] == b"\x00\x01\x00\x00"  # TTF magic
    assert (await client.get("/api/certificate-assets/fonts/serif/bogus")).status_code == 404
    r = await client.get("/api/certificate-assets/backgrounds/classic")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert (await client.get("/api/certificate-assets/backgrounds/bogus")).status_code == 404


def test_ordinal_and_placement():
    from plugins.certificates.assets import ordinal, placement_label

    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd",
    ]
    assert placement_label(3, is_scorer=True) == "3rd place"
    assert placement_label(9, is_scorer=False) == "Participant"


# --- fixes from the adversarial review -------------------------------------


async def test_uploaded_background_renders_on_self_download(client):
    """Regression: _spec_from_template must carry background_object_key, or the
    participant download silently loses the uploaded background."""
    from PIL import Image

    admin = await admin_token(client)
    comp = await _competition(client)
    p = await _participant(client, comp, "bg@x.com")
    base = f"/api/competitions/{comp}/certificates"
    r = await client.post(
        f"{base}/background",
        files={"file": ("bg.png", _png(1400, 990, (255, 0, 255)), "image/png")},
        headers=_auth(admin),
    )
    assert r.status_code == 200
    await client.put(
        f"{base}/template",
        json=_body(background_kind="upload", background_preset=None, elements=[]),
        headers=_auth(admin),
    )
    await client.post(f"{base}/release", headers=_auth(admin))
    dl = await client.get(f"{base}/me/download", headers=_auth(p))
    assert dl.status_code == 200
    im = Image.open(io.BytesIO(dl.content)).convert("RGB")
    px = im.getpixel((60, 60))  # design-area corner → the magenta background
    assert px[0] > 200 and px[1] < 60 and px[2] > 200, px


async def test_out_of_scope_image_key_rejected(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    body = _body(
        elements=[
            {"type": "image", "x": 10, "y": 10, "width": 20, "image_key": "OTHER/certificates/images/x.png"}
        ]
    )
    r = await client.put(
        f"/api/competitions/{comp}/certificates/template", json=body, headers=_auth(admin)
    )
    assert r.status_code == 422


async def test_too_many_image_elements_rejected(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    imgs = [
        {"type": "image", "x": i, "y": i, "width": 5, "image_key": f"{comp}/certificates/images/{i}.png"}
        for i in range(9)
    ]
    r = await client.put(
        f"/api/competitions/{comp}/certificates/template",
        json=_body(elements=imgs),
        headers=_auth(admin),
    )
    assert r.status_code == 422


async def test_preset_colors_persist_and_validate(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    base_url = f"/api/competitions/{comp}/certificates"
    r = await client.put(
        f"{base_url}/template",
        json=_body(background_preset="aurora", preset_accent="#ff0000", preset_base="#000000"),
        headers=_auth(admin),
    )
    assert r.status_code == 200, r.text
    assert r.json()["preset_accent"] == "#ff0000" and r.json()["preset_base"] == "#000000"
    g = await client.get(f"{base_url}/template", headers=_auth(admin))
    assert g.json()["preset_accent"] == "#ff0000"
    # Invalid hex rejected.
    bad = await client.put(
        f"{base_url}/template", json=_body(preset_accent="red"), headers=_auth(admin)
    )
    assert bad.status_code == 422


async def test_preset_asset_accepts_color_params(client):
    r = await client.get(
        "/api/certificate-assets/backgrounds/aurora",
        params={"accent": "#ff0000", "base": "#001122"},
    )
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    m = await client.get("/api/certificate-assets/manifest")
    assert all("accent" in p and "base" in p for p in m.json()["presets"])


# --- custom fonts ----------------------------------------------------------


def _ttf() -> bytes:
    from plugins.certificates.assets import font_path

    return font_path("sans").read_bytes()


async def test_custom_font_upload_list_use_delete(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    base = f"/api/competitions/{comp}/certificates"

    r = await client.post(
        f"{base}/fonts",
        files={"file": ("Brand.ttf", _ttf(), "font/ttf")},
        data={"name": "Brand Sans"},
        headers=_auth(admin),
    )
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert r.json()["name"] == "Brand Sans" and r.json()["format"] == "ttf"

    lst = await client.get(f"{base}/fonts", headers=_auth(admin))
    assert lst.status_code == 200 and [f["id"] for f in lst.json()] == [fid]

    # The font file streams back for the editor @font-face.
    f = await client.get(f"{base}/fonts/{fid}/file", headers=_auth(admin))
    assert f.status_code == 200 and f.content[:4] == b"\x00\x01\x00\x00"

    # A template can reference it, and it previews through the real renderer.
    body = _body(elements=[{"type": "text", "x": 10, "y": 40, "text": "Hi", "font": f"custom:{fid}"}])
    put = await client.put(f"{base}/template", json=body, headers=_auth(admin))
    assert put.status_code == 200, put.text
    prev = await client.post(f"{base}/preview", json=body, headers=_auth(admin))
    assert prev.status_code == 200 and prev.content[:8] == b"\x89PNG\r\n\x1a\n"

    d = await client.delete(f"{base}/fonts/{fid}", headers=_auth(admin))
    assert d.status_code == 204
    assert (await client.get(f"{base}/fonts", headers=_auth(admin))).json() == []
    # Now the saved reference is dangling → a re-save is rejected.
    again = await client.put(f"{base}/template", json=body, headers=_auth(admin))
    assert again.status_code == 422


async def test_custom_font_rejects_non_font(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    base = f"/api/competitions/{comp}/certificates"
    # A PNG isn't a font → 415.
    r = await client.post(
        f"{base}/fonts", files={"file": ("x.png", _png(), "image/png")}, headers=_auth(admin)
    )
    assert r.status_code == 415
    # TTF magic but not a real font → parse fails → 422.
    r = await client.post(
        f"{base}/fonts",
        files={"file": ("x.ttf", b"\x00\x01\x00\x00" + b"\x00" * 64, "font/ttf")},
        headers=_auth(admin),
    )
    assert r.status_code == 422


async def test_custom_font_scoped_to_competition(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    other = await _competition(client)
    fid = (
        await client.post(
            f"/api/competitions/{comp}/certificates/fonts",
            files={"file": ("f.ttf", _ttf(), "font/ttf")},
            headers=_auth(admin),
        )
    ).json()["id"]
    # The other competition can't fetch or delete it, nor reference it.
    assert (
        await client.get(f"/api/competitions/{other}/certificates/fonts/{fid}/file", headers=_auth(admin))
    ).status_code == 404
    assert (
        await client.delete(f"/api/competitions/{other}/certificates/fonts/{fid}", headers=_auth(admin))
    ).status_code == 404
    body = _body(elements=[{"type": "text", "x": 1, "y": 1, "text": "x", "font": f"custom:{fid}"}])
    r = await client.put(f"/api/competitions/{other}/certificates/template", json=body, headers=_auth(admin))
    assert r.status_code == 422


async def test_custom_font_count_cap(client, monkeypatch):
    from routers import certificates as cert_router

    monkeypatch.setattr(cert_router, "MAX_CUSTOM_FONTS", 1)
    admin = await admin_token(client)
    comp = await _competition(client)
    base = f"/api/competitions/{comp}/certificates"
    r1 = await client.post(f"{base}/fonts", files={"file": ("a.ttf", _ttf(), "font/ttf")}, headers=_auth(admin))
    assert r1.status_code == 201
    r2 = await client.post(f"{base}/fonts", files={"file": ("b.ttf", _ttf(), "font/ttf")}, headers=_auth(admin))
    assert r2.status_code == 400


async def test_malformed_custom_font_ref_rejected(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    body = _body(elements=[{"type": "text", "x": 1, "y": 1, "text": "x", "font": "custom:not-a-uuid"}])
    r = await client.put(f"/api/competitions/{comp}/certificates/template", json=body, headers=_auth(admin))
    assert r.status_code == 422  # schema shape-check


# --- template export / import ----------------------------------------------


async def test_template_export_import_roundtrip(client):
    admin = await admin_token(client)
    src = await _competition(client)
    dst = await _competition(client)
    sbase = f"/api/competitions/{src}/certificates"

    fid = (
        await client.post(f"{sbase}/fonts", files={"file": ("f.ttf", _ttf(), "font/ttf")}, headers=_auth(admin))
    ).json()["id"]
    img_key = (
        await client.post(f"{sbase}/images", files={"file": ("s.png", _png(200, 120), "image/png")}, headers=_auth(admin))
    ).json()["image_key"]
    body = _body(
        background_preset="aurora",
        preset_accent="#ff0000",
        preset_base="#001122",
        elements=[
            {"type": "text", "x": 10, "y": 20, "text": "Winner", "font": f"custom:{fid}"},
            {"type": "image", "x": 40, "y": 60, "width": 20, "image_key": img_key},
        ],
    )
    assert (await client.put(f"{sbase}/template", json=body, headers=_auth(admin))).status_code == 200

    doc = (await client.get(f"{sbase}/template/export", headers=_auth(admin))).json()
    assert doc["flagpost_certificate_template"] == 1
    assert len(doc["assets"]["fonts"]) == 1 and len(doc["assets"]["images"]) == 1

    # Import into a different competition.
    dbase = f"/api/competitions/{dst}/certificates"
    imp = await client.post(f"{dbase}/template/import", json=doc, headers=_auth(admin))
    assert imp.status_code == 200, imp.text
    got = (await client.get(f"{dbase}/template", headers=_auth(admin))).json()
    assert got["background_preset"] == "aurora" and got["preset_accent"] == "#ff0000"

    dst_fonts = (await client.get(f"{dbase}/fonts", headers=_auth(admin))).json()
    assert len(dst_fonts) == 1 and dst_fonts[0]["id"] != fid  # a fresh font row
    new_ref = f"custom:{dst_fonts[0]['id']}"
    text_el = next(e for e in got["elements"] if e["type"] == "text")
    image_el = next(e for e in got["elements"] if e["type"] == "image")
    assert text_el["font"] == new_ref
    # Image re-uploaded into the destination's own namespace (§6.2 tenancy).
    assert image_el["image_key"].startswith(f"{dst}/certificates/") and image_el["image_key"] != img_key

    # And it renders end-to-end with the re-uploaded assets.
    prev = await client.post(f"{dbase}/preview", json={
        **body,
        "elements": got["elements"],
    }, headers=_auth(admin))
    assert prev.status_code == 200 and prev.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_import_drops_unbundled_image_element(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    base = f"/api/competitions/{comp}/certificates"
    doc = {
        "flagpost_certificate_template": 1,
        "template": {
            "background_kind": "color",
            "background_color": "#ffffff",
            "elements": [
                {"type": "text", "x": 5, "y": 5, "text": "Kept"},
                {"type": "image", "x": 1, "y": 1, "width": 10, "image_key": "OLD/certificates/images/x.png"},
            ],
        },
        "assets": {},  # the image bytes weren't bundled
    }
    r = await client.post(f"{base}/template/import", json=doc, headers=_auth(admin))
    assert r.status_code == 200, r.text
    got = (await client.get(f"{base}/template", headers=_auth(admin))).json()
    types = [e["type"] for e in got["elements"]]
    assert types == ["text"]  # the un-portable image element was dropped


async def test_import_hardening(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    base = f"/api/competitions/{comp}/certificates"
    ref = "custom:1e2d3c4b-5a69-4788-9abc-def012345678"
    # Unsupported version.
    r = await client.post(
        f"{base}/template/import",
        json={"flagpost_certificate_template": 999, "template": {}, "assets": {}},
        headers=_auth(admin),
    )
    assert r.status_code == 422
    # Invalid base64 asset.
    r = await client.post(
        f"{base}/template/import",
        json={
            "flagpost_certificate_template": 1,
            "template": {"background_kind": "color", "elements": []},
            "assets": {"fonts": {ref: {"data": "!!!not-base64", "format": "ttf"}}},
        },
        headers=_auth(admin),
    )
    assert r.status_code == 422
    # Valid base64 but not a font.
    import base64 as _b64

    r = await client.post(
        f"{base}/template/import",
        json={
            "flagpost_certificate_template": 1,
            "template": {"background_kind": "color", "elements": []},
            "assets": {"fonts": {ref: {"data": _b64.b64encode(b"hello").decode(), "format": "ttf"}}},
        },
        headers=_auth(admin),
    )
    assert r.status_code == 415


async def test_reimport_replaces_custom_fonts(client):
    """Re-importing must replace the design's fonts, not accumulate them (else the
    per-competition cap is bypassed and rows orphan)."""
    admin = await admin_token(client)
    comp = await _competition(client)
    base = f"/api/competitions/{comp}/certificates"
    fid = (
        await client.post(f"{base}/fonts", files={"file": ("a.ttf", _ttf(), "font/ttf")}, headers=_auth(admin))
    ).json()["id"]
    body = _body(elements=[{"type": "text", "x": 5, "y": 5, "text": "Hi", "font": f"custom:{fid}"}])
    await client.put(f"{base}/template", json=body, headers=_auth(admin))
    doc = (await client.get(f"{base}/template/export", headers=_auth(admin))).json()
    for _ in range(2):
        assert (await client.post(f"{base}/template/import", json=doc, headers=_auth(admin))).status_code == 200
    fonts = (await client.get(f"{base}/fonts", headers=_auth(admin))).json()
    assert len(fonts) == 1  # replaced each time, not accumulated
    got = (await client.get(f"{base}/template", headers=_auth(admin))).json()
    assert got["elements"][0]["font"] == f"custom:{fonts[0]['id']}"


async def test_import_ignores_unreferenced_font(client):
    """A font embedded but referenced by no element is validated but not created
    (no orphan row / object)."""
    import base64 as _b64

    admin = await admin_token(client)
    comp = await _competition(client)
    base = f"/api/competitions/{comp}/certificates"
    doc = {
        "flagpost_certificate_template": 1,
        "template": {
            "background_kind": "color",
            "background_color": "#ffffff",
            "elements": [{"type": "text", "x": 1, "y": 1, "text": "hi"}],
        },
        "assets": {
            "fonts": {
                "custom:1e2d3c4b-5a69-4788-9abc-def012345678": {
                    "data": _b64.b64encode(_ttf()).decode(),
                    "format": "ttf",
                    "name": "Unused",
                }
            }
        },
    }
    assert (await client.post(f"{base}/template/import", json=doc, headers=_auth(admin))).status_code == 200
    assert (await client.get(f"{base}/fonts", headers=_auth(admin))).json() == []


async def test_import_color_over_upload_clears_background(client):
    admin = await admin_token(client)
    comp = await _competition(client)
    base = f"/api/competitions/{comp}/certificates"
    await client.post(
        f"{base}/background", files={"file": ("bg.png", _png(1400, 990), "image/png")}, headers=_auth(admin)
    )
    await client.put(
        f"{base}/template",
        json=_body(background_kind="upload", background_preset=None, elements=[]),
        headers=_auth(admin),
    )
    assert (await client.get(f"{base}/template", headers=_auth(admin))).json()["has_background_image"] is True
    doc = {
        "flagpost_certificate_template": 1,
        "template": {"background_kind": "color", "background_color": "#ffffff", "elements": []},
        "assets": {},
    }
    assert (await client.post(f"{base}/template/import", json=doc, headers=_auth(admin))).status_code == 200
    got = (await client.get(f"{base}/template", headers=_auth(admin))).json()
    assert got["background_kind"] == "color" and got["has_background_image"] is False


async def test_export_recipient_cap(client, object_storage, monkeypatch):
    from utils import automation_scheduler

    monkeypatch.setattr("storage.get_storage", lambda: object_storage)
    monkeypatch.setattr(automation_scheduler, "MAX_EXPORT_RECIPIENTS", 1)
    admin = await admin_token(client)
    comp = await _competition(client)
    await _participant(client, comp, "a@x.com")
    await _participant(client, comp, "b@x.com")
    base = f"/api/competitions/{comp}/certificates"
    await client.put(f"{base}/template", json=_body(), headers=_auth(admin))
    job_id = (await client.post(f"{base}/exports", headers=_auth(admin))).json()["id"]
    await automation_scheduler.process_certificate_exports(SessionLocal)
    r = await client.get(f"{base}/exports/{job_id}", headers=_auth(admin))
    assert r.json()["status"] == "failed"
    assert "Too many recipients" in (r.json()["error"] or "")
