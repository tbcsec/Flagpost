"""Archived-competition retention (#26): the archive-time purge clock, the
site-setting toggle, the purge job (DB tree + attachment objects + event), and
the manual-delete storage cleanup that shipped with it."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db import SessionLocal, utcnow
from models.competition import Competition
from tests.conftest import admin_token
from utils.event_bus import event_bus
from utils.retention import purge_expired_competitions


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_competition(client, admin: str, name: str = "Retiring CTF") -> str:
    resp = await client.post(
        "/api/competitions",
        json={"name": name, "participation_mode": "individual"},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _challenge_with_attachment(client, admin: str, comp: str) -> str:
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Chal", "points": 100, "flag": "flag{x}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/attachments",
        files={"file": ("handout.zip", b"PK\x03\x04data", "application/zip")},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return chal


async def _object_keys(comp: str) -> list[str]:
    from models.attachment import Attachment

    async with SessionLocal() as session:
        return list(
            (
                await session.execute(
                    select(Attachment.object_key).where(
                        Attachment.competition_id == comp
                    )
                )
            ).scalars()
        )


async def _set_retention(client, admin: str, *, enabled: bool, days: int = 30) -> None:
    resp = await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "archive_auto_delete": enabled,
            "archive_retention_days": days,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text


async def _force_purge_after(comp: str, when: datetime) -> None:
    async with SessionLocal() as session:
        competition = await session.get(Competition, comp)
        competition.purge_after = when
        await session.commit()


async def test_archive_stamps_clock_and_unarchive_clears_it(client):
    admin = await admin_token(client)
    comp = await _create_competition(client, admin)

    body = (
        await client.post(f"/api/competitions/{comp}/archive", headers=_auth(admin))
    ).json()
    # Default policy: on at 30 days.
    assert body["purge_after"] is not None
    archived_at = datetime.fromisoformat(body["archived_at"])
    purge_after = datetime.fromisoformat(body["purge_after"])
    assert purge_after - archived_at == timedelta(days=30)

    body = (
        await client.post(f"/api/competitions/{comp}/unarchive", headers=_auth(admin))
    ).json()
    assert body["archived_at"] is None
    assert body["purge_after"] is None


async def test_disabled_retention_archives_without_a_clock(client):
    admin = await admin_token(client)
    await _set_retention(client, admin, enabled=False)
    comp = await _create_competition(client, admin)

    body = (
        await client.post(f"/api/competitions/{comp}/archive", headers=_auth(admin))
    ).json()
    assert body["archived_at"] is not None
    assert body["purge_after"] is None


async def test_retention_days_setting_is_honored(client):
    admin = await admin_token(client)
    await _set_retention(client, admin, enabled=True, days=7)
    comp = await _create_competition(client, admin)

    body = (
        await client.post(f"/api/competitions/{comp}/archive", headers=_auth(admin))
    ).json()
    delta = datetime.fromisoformat(body["purge_after"]) - datetime.fromisoformat(
        body["archived_at"]
    )
    assert delta == timedelta(days=7)


async def test_public_site_settings_expose_the_policy(client):
    # The archive confirm dialog needs the policy without manage_site_settings.
    body = (await client.get("/api/site-settings")).json()
    assert body["archive_auto_delete"] is True
    assert body["archive_retention_days"] == 30


async def test_purge_deletes_expired_tree_objects_and_emits(client, object_storage):
    admin = await admin_token(client)
    comp = await _create_competition(client, admin)
    await _challenge_with_attachment(client, admin, comp)
    keys = await _object_keys(comp)
    assert keys and all(object_storage.exists(k) for k in keys)

    resp = await client.post(f"/api/competitions/{comp}/archive", headers=_auth(admin))
    assert resp.status_code == 200
    await _force_purge_after(comp, utcnow() - timedelta(minutes=1))

    captured: list[dict] = []

    async def capture(event_name: str, payload: dict) -> None:
        captured.append(payload)

    event_bus.subscribe("competition.deleted", capture, owner="test-retention")
    try:
        purged = await purge_expired_competitions(
            SessionLocal, storage=object_storage
        )
    finally:
        event_bus.unsubscribe_owner("test-retention")

    assert purged == 1
    # DB tree gone (API 404s), storage objects gone, purge audited as auto.
    resp = await client.get(f"/api/competitions/{comp}", headers=_auth(admin))
    assert resp.status_code == 404
    assert all(not object_storage.exists(k) for k in keys)
    assert captured == [
        {"competition_id": comp, "user_id": None, "auto": True}
    ]


async def test_purge_leaves_unexpired_and_unclocked_archives(client, object_storage):
    admin = await admin_token(client)
    future = await _create_competition(client, admin, name="Still Cooling")
    legacy = await _create_competition(client, admin, name="Pre-Feature Archive")

    await client.post(f"/api/competitions/{future}/archive", headers=_auth(admin))
    await client.post(f"/api/competitions/{legacy}/archive", headers=_auth(admin))
    # `future` keeps its (30-day) clock; `legacy` mimics a pre-feature archive —
    # no clock at all, the upgrade-grandfathering invariant.
    await _force_purge_after(legacy, None)

    purged = await purge_expired_competitions(SessionLocal, storage=object_storage)
    assert purged == 0
    for comp in (future, legacy):
        resp = await client.get(f"/api/competitions/{comp}", headers=_auth(admin))
        assert resp.status_code == 200, resp.text


async def test_purge_never_touches_an_active_competition(client, object_storage):
    """Belt-and-braces: even a (theoretically impossible) purge_after on an
    active competition must not delete it — archived_at guards the query."""
    admin = await admin_token(client)
    comp = await _create_competition(client, admin, name="Active But Clocked")
    await _force_purge_after(comp, datetime(2000, 1, 1, tzinfo=timezone.utc))

    purged = await purge_expired_competitions(SessionLocal, storage=object_storage)
    assert purged == 0
    resp = await client.get(f"/api/competitions/{comp}", headers=_auth(admin))
    assert resp.status_code == 200


async def test_manual_delete_also_removes_stored_objects(client, object_storage):
    admin = await admin_token(client)
    comp = await _create_competition(client, admin, name="Doomed")
    await _challenge_with_attachment(client, admin, comp)
    keys = await _object_keys(comp)
    assert keys and all(object_storage.exists(k) for k in keys)

    resp = await client.delete(f"/api/competitions/{comp}", headers=_auth(admin))
    assert resp.status_code == 204
    assert all(not object_storage.exists(k) for k in keys)
