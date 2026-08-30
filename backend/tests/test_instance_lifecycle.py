"""Phase 1c of challenge instancing (#266, ADR-0036): the ``instances`` module —
the lifecycle service, the competitor + staff + author routes, the site infra
settings + test-connection, the event catalogue wiring and the reaper.

The Docker *provisioner* itself is exercised against a mock transport in
``test_provisioner_docker`` (Phase 1b); here the lifecycle runs end-to-end on
the zero-infra ``shared-static`` kind, and the docker-specific pieces that don't
need a daemon (port allocation, settings, test-connection wiring) are tested
directly. Background provisioning is drained with ``event_bus.wait_for_background``.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from config import settings as app_settings
from db import SessionLocal, utcnow
from models.audit_log import AuditLogEntry
from models.challenge_instancing import (
    INSTANCE_SETTINGS_ID,
    ChallengeDeployment,
    ChallengeInstance,
    InstanceSettings,
)
from models.competition_module import CompetitionModule
from models.role import Role, RoleAssignment
from models.user import User
from tests.conftest import admin_token
from utils.event_bus import event_bus
from utils.provisioners import CheckResult

pytestmark = pytest.mark.asyncio


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": email.split("@")[0],
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _assign_participant(user_id: str, competition_id: str) -> None:
    async with SessionLocal() as session:
        role = await session.scalar(select(Role).where(Role.name == "Participant"))
        session.add(
            RoleAssignment(
                user_id=user_id, competition_id=competition_id, role_id=role.id
            )
        )
        await session.commit()


async def _make_competition(client, token, **over) -> str:
    body = {"name": "Instanced CTF", "participation_mode": "individual"}
    body.update(over)
    resp = await client.post("/api/competitions", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_challenge(client, comp, token) -> str:
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "pwn me", "points": 100, "flag": "flag{static}"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _shared_static_body(**over) -> dict:
    body = {
        "backend": "shared-static",
        "exposure": "tcp",
        "ports": [1337],
        "manifest": {
            "endpoints": [{"kind": "tcp", "host": "chal.example", "port": 31337}]
        },
        "per_subject_cap": 1,
    }
    body.update(over)
    return body


async def _put_deployment(client, comp, chal, token, **over):
    return await client.put(
        f"/api/competitions/{comp}/challenges/{chal}/deployment",
        json=_shared_static_body(**over),
        headers=_auth(token),
    )


async def _competitor(client, comp):
    token, uid = await _register(client, f"player{uid_counter()}@example.com")
    await _assign_participant(uid, comp)
    return token, uid


_counter = {"n": 0}


def uid_counter() -> int:
    _counter["n"] += 1
    return _counter["n"]


async def _events(name: str):
    async with SessionLocal() as session:
        return (
            await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.event_name == name)
            )
        ).scalars().all()


# --- deployment authoring ----------------------------------------------------


async def test_author_can_upsert_get_and_delete_a_deployment(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)

    put = await _put_deployment(client, comp, chal, admin)
    assert put.status_code == 200, put.text
    assert put.json()["backend"] == "shared-static"

    got = await client.get(
        f"/api/competitions/{comp}/challenges/{chal}/deployment", headers=_auth(admin)
    )
    assert got.status_code == 200
    assert got.json()["challenge_id"] == chal

    # Upsert edits in place (one spec per challenge).
    again = await _put_deployment(client, comp, chal, admin, per_subject_cap=3)
    assert again.json()["per_subject_cap"] == 3
    async with SessionLocal() as db:
        count = await db.scalar(
            select(func.count(ChallengeDeployment.id)).where(
                ChallengeDeployment.challenge_id == chal
            )
        )
    assert count == 1

    delete = await client.delete(
        f"/api/competitions/{comp}/challenges/{chal}/deployment", headers=_auth(admin)
    )
    assert delete.status_code == 204


async def test_deployment_validation_rejects_a_bad_shape(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    # docker backend with no image reference.
    resp = await client.put(
        f"/api/competitions/{comp}/challenges/{chal}/deployment",
        json={"backend": "docker", "exposure": "tcp", "ports": [1337]},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    assert "image reference" in resp.json()["detail"]


async def test_instanced_flag_exposed_on_challenge_reads(client):
    # The competitor-facing challenge list + detail carry `instanced` so the UI
    # knows which challenges offer a "Launch instance" panel — true only where a
    # deployment spec exists.
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal_a = await _make_challenge(client, comp, admin)
    chal_b = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal_a, admin)

    listing = await client.get(
        f"/api/competitions/{comp}/challenges", headers=_auth(admin)
    )
    by_id = {c["id"]: c for c in listing.json()}
    assert by_id[chal_a]["instanced"] is True
    assert by_id[chal_b]["instanced"] is False

    detail_a = await client.get(
        f"/api/competitions/{comp}/challenges/{chal_a}", headers=_auth(admin)
    )
    assert detail_a.json()["instanced"] is True
    detail_b = await client.get(
        f"/api/competitions/{comp}/challenges/{chal_b}", headers=_auth(admin)
    )
    assert detail_b.json()["instanced"] is False


async def test_deployment_authoring_needs_challenge_edit(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    token, _ = await _competitor(client, comp)
    resp = await _put_deployment(client, comp, chal, token)
    assert resp.status_code == 403


# --- launch / status / lifecycle (shared-static, end to end) -----------------


async def test_launch_provisions_to_running_and_reveals_endpoints(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal, admin)
    token, _ = await _competitor(client, comp)

    launched = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert launched.status_code == 201, launched.text
    body = launched.json()
    assert body["status"] == "requested"
    # Connection detail is hidden until the instance is running.
    assert body["endpoints"] == []

    await event_bus.wait_for_background()

    status = await client.get(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert status.status_code == 200
    got = status.json()
    assert got["status"] == "running"
    assert got["endpoints"] == [
        {"kind": "tcp", "host": "chal.example", "port": 31337}
    ]
    assert await _events("challenge.instance_requested")
    assert await _events("challenge.instance_started")


async def test_launch_without_a_deployment_is_404(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    token, _ = await _competitor(client, comp)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert resp.status_code == 404


async def test_per_subject_cap_blocks_a_second_instance(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal, admin, per_subject_cap=1)
    token, _ = await _competitor(client, comp)

    first = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert second.status_code == 409
    assert "maximum" in second.json()["detail"]


async def test_competition_alive_cap_is_enforced(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin, instance_max_alive=1)
    chal_a = await _make_challenge(client, comp, admin)
    chal_b = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal_a, admin, per_subject_cap=5)
    await _put_deployment(client, comp, chal_b, admin, per_subject_cap=5)
    token, _ = await _competitor(client, comp)

    a = await client.post(
        f"/api/competitions/{comp}/challenges/{chal_a}/instance", headers=_auth(token)
    )
    assert a.status_code == 201
    b = await client.post(
        f"/api/competitions/{comp}/challenges/{chal_b}/instance", headers=_auth(token)
    )
    assert b.status_code == 409
    assert "competition's limit" in b.json()["detail"]


async def _set_spawn_limit(client, admin, limit: int, window: int = 3600) -> None:
    resp = await client.put(
        "/api/admin/instances/settings",
        json={"spawn_rate_limit": limit, "spawn_rate_window_seconds": window},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text


async def test_spawn_rate_limit_throttles_a_burst_and_emits(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    # High per-subject cap so the throttle — not the cap — is the gate.
    await _put_deployment(client, comp, chal, admin, per_subject_cap=5)
    await _set_spawn_limit(client, admin, 1)
    token, _ = await _competitor(client, comp)

    first = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert second.status_code == 429, second.text
    await event_bus.wait_for_background()
    assert await _events("challenge.instance_launch_throttled")


async def test_spawn_rate_limit_off_by_default(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal, admin, per_subject_cap=5)
    # No spawn limit configured (0 = off): a burst all succeeds.
    token, _ = await _competitor(client, comp)
    for _ in range(3):
        r = await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
        )
        assert r.status_code == 201, r.text


async def test_spawn_rate_limit_only_counts_launches_inside_the_window(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal, admin, per_subject_cap=5)
    await _set_spawn_limit(client, admin, 1, window=60)
    token, uid = await _competitor(client, comp)

    first = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert first.status_code == 201
    # Age the first launch out of the 60s window — it must no longer count.
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(ChallengeInstance).where(ChallengeInstance.user_id == uid)
            )
        ).scalars().first()
        row.created_at = utcnow() - timedelta(hours=1)
        await db.commit()
    second = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert second.status_code == 201, second.text  # aged out → not throttled


async def test_extend_renews_lifetime_and_is_capped(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal, admin)
    token, _ = await _competitor(client, comp)
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    await event_bus.wait_for_background()

    from utils.instance_service import MAX_EXTENDS

    last = None
    for i in range(MAX_EXTENDS):
        resp = await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/instance/extend",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extend_count"] == i + 1
        last = resp.json()
    assert last["extend_count"] == MAX_EXTENDS
    # One more than the cap is refused.
    over = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance/extend",
        headers=_auth(token),
    )
    assert over.status_code == 409
    assert await _events("challenge.instance_extended")


async def test_subject_can_destroy_their_instance(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal, admin)
    token, _ = await _competitor(client, comp)
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    await event_bus.wait_for_background()

    killed = await client.delete(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert killed.status_code == 202
    gone = await client.get(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert gone.status_code == 404
    assert await _events("challenge.instance_destroyed")


# --- gating ------------------------------------------------------------------


async def test_launch_404s_when_module_disabled_for_competition(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal, admin)
    token, _ = await _competitor(client, comp)
    async with SessionLocal() as db:
        db.add(
            CompetitionModule(
                competition_id=comp, module_id="instances", enabled=False
            )
        )
        await db.commit()
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert resp.status_code == 404
    assert "disabled" in resp.json()["detail"]


async def test_launch_disabled_in_demo_mode(client, monkeypatch):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal, admin)
    token, _ = await _competitor(client, comp)
    monkeypatch.setattr(app_settings, "demo_mode", True)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert resp.status_code == 403
    assert "demo" in resp.json()["detail"].lower()


@pytest.mark.competition_lifecycle
async def test_not_started_blocks_competitor_but_staff_test_launch_works(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)  # stays not_started
    chal = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal, admin)
    token, _ = await _competitor(client, comp)

    competitor = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert competitor.status_code == 403

    # Staff (instance_manage) may test-launch before the competition starts.
    staff = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(admin)
    )
    assert staff.status_code == 201, staff.text


# --- staff ops ---------------------------------------------------------------


async def test_staff_can_list_and_kill_any_instance(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_challenge(client, comp, admin)
    await _put_deployment(client, comp, chal, admin)
    token, _ = await _competitor(client, comp)
    launched = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    instance_id = launched.json()["id"]
    await event_bus.wait_for_background()

    listing = await client.get(
        f"/api/competitions/{comp}/instances", headers=_auth(admin)
    )
    assert listing.status_code == 200
    ids = [row["id"] for row in listing.json()]
    assert instance_id in ids
    # The staff view carries the subject + handle the competitor view hides.
    assert "user_id" in listing.json()[0]
    # Labels are resolved server-side (challenge title + the subject's display
    # name), so the ops table never shows a bare id — and it works for any
    # subject, not just those in the competitor roster.
    row0 = next(r for r in listing.json() if r["id"] == instance_id)
    assert row0["challenge_title"] == "pwn me"
    assert row0["subject_label"] and row0["subject_label"] != row0["user_id"]

    kill = await client.delete(
        f"/api/competitions/{comp}/instances/{instance_id}", headers=_auth(admin)
    )
    assert kill.status_code == 202
    async with SessionLocal() as db:
        row = await db.get(ChallengeInstance, instance_id)
    assert row.status == "destroyed"


async def test_staff_list_needs_instance_view(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    token, _ = await _competitor(client, comp)
    resp = await client.get(
        f"/api/competitions/{comp}/instances", headers=_auth(token)
    )
    assert resp.status_code == 403


# --- site settings + test connection -----------------------------------------


async def test_settings_default_inert_and_credentials_are_write_only(client):
    admin = await admin_token(client)
    got = await client.get("/api/admin/instances/settings", headers=_auth(admin))
    assert got.status_code == 200
    assert got.json()["enabled"] is False
    assert got.json()["registry_credentials_set"] is False

    saved = await client.put(
        "/api/admin/instances/settings",
        json={"registry_credentials": "s3cret", "public_host": "chal.example"},
        headers=_auth(admin),
    )
    assert saved.status_code == 200
    # The secret is never echoed back; only its presence is reported.
    assert "registry_credentials" not in saved.json()
    assert saved.json()["registry_credentials_set"] is True
    assert await _events("instance.settings_updated")


async def test_enabling_requires_endpoint_and_public_host(client):
    admin = await admin_token(client)
    bad = await client.put(
        "/api/admin/instances/settings",
        json={"backend": "docker", "enabled": True},
        headers=_auth(admin),
    )
    assert bad.status_code == 400

    ok = await client.put(
        "/api/admin/instances/settings",
        json={
            "backend": "docker",
            "endpoint_url": "http://socket-proxy:2375",
            "public_host": "chal.example",
            "enabled": True,
        },
        headers=_auth(admin),
    )
    assert ok.status_code == 200
    assert ok.json()["enabled"] is True


async def test_enabling_rejects_a_non_orchestrating_backend(client):
    # A bogus/shared-static site backend must not slip past the enable invariant
    # (it isn't a SITE_BACKEND, so the endpoint/public-host requirement would be
    # skipped) — that reachable "enabled but unconfigured" state is refused.
    admin = await admin_token(client)
    resp = await client.put(
        "/api/admin/instances/settings",
        json={"backend": "shared-static", "enabled": True},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    assert "Backend must be one of" in resp.json()["detail"]


async def test_settings_require_manage_instance_infra(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    token, _ = await _competitor(client, comp)
    resp = await client.get("/api/admin/instances/settings", headers=_auth(token))
    assert resp.status_code == 403


async def test_test_connection_reports_staged_legs(client, monkeypatch):
    admin = await admin_token(client)
    # Unconfigured → 400.
    unconfigured = await client.post(
        "/api/admin/instances/test-connection", headers=_auth(admin)
    )
    assert unconfigured.status_code == 400

    await client.put(
        "/api/admin/instances/settings",
        json={
            "backend": "docker",
            "endpoint_url": "http://socket-proxy:2375",
            "public_host": "chal.example",
        },
        headers=_auth(admin),
    )

    async def fake_validation(settings):
        return [
            CheckResult("endpoint_reachable", True, "proxy reachable"),
            CheckResult("privilege_posture", False, "exec: NOT blocked"),
        ]

    monkeypatch.setattr(
        "routers.instances_settings._run_validation", fake_validation
    )
    resp = await client.post(
        "/api/admin/instances/test-connection", headers=_auth(admin)
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["ok"] is False  # a failing leg fails the whole check
    assert [leg["name"] for leg in result["legs"]] == [
        "endpoint_reachable",
        "privilege_posture",
    ]
