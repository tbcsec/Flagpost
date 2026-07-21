"""Admin audit-log query endpoint (§3.3): RBAC, filtering (event/competition/
team/free-text), pagination, and the password-change event."""

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "U"},
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _seed(entries: list[dict]) -> None:
    async with SessionLocal() as session:
        for e in entries:
            session.add(
                AuditLogEntry(
                    event_name=e["event_name"],
                    payload=e.get("payload", {}),
                    competition_id=e.get("competition_id"),
                    user_id=e.get("user_id"),
                )
            )
        await session.commit()


async def test_requires_view_audit_log(client):
    token, _ = await _register(client, "nostaff@example.com")
    resp = await client.get("/api/admin/audit-log", headers=_auth(token))
    assert resp.status_code == 403


async def test_admin_can_query_all_events(client):
    admin = await admin_token(client)
    await _seed(
        [
            {"event_name": "challenge.solved", "competition_id": "c1", "payload": {"team_id": "t1"}},
            {"event_name": "team.created", "competition_id": "c1", "payload": {"team_id": "t2"}},
        ]
    )
    resp = await client.get("/api/admin/audit-log", headers=_auth(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2
    # Newest first.
    assert body["items"][0]["event_name"] == "team.created"


async def test_filter_by_exact_event(client):
    admin = await admin_token(client)
    await _seed(
        [
            {"event_name": "challenge.solved", "competition_id": "cx"},
            {"event_name": "challenge.updated", "competition_id": "cx"},
        ]
    )
    resp = await client.get(
        "/api/admin/audit-log",
        params={"event": "challenge.solved", "competition_id": "cx"},
        headers=_auth(admin),
    )
    names = {i["event_name"] for i in resp.json()["items"]}
    assert names == {"challenge.solved"}


async def test_filter_by_event_prefix_wildcard(client):
    admin = await admin_token(client)
    await _seed(
        [
            {"event_name": "challenge.solved", "competition_id": "cy"},
            {"event_name": "challenge.updated", "competition_id": "cy"},
            {"event_name": "team.created", "competition_id": "cy"},
        ]
    )
    resp = await client.get(
        "/api/admin/audit-log",
        params={"event": "challenge.*", "competition_id": "cy"},
        headers=_auth(admin),
    )
    names = {i["event_name"] for i in resp.json()["items"]}
    assert names == {"challenge.solved", "challenge.updated"}


async def test_filter_by_team_in_payload(client):
    admin = await admin_token(client)
    await _seed(
        [
            {"event_name": "challenge.solved", "competition_id": "cz", "payload": {"team_id": "alpha"}},
            {"event_name": "challenge.solved", "competition_id": "cz", "payload": {"team_id": "beta"}},
        ]
    )
    resp = await client.get(
        "/api/admin/audit-log",
        params={"team_id": "alpha", "competition_id": "cz"},
        headers=_auth(admin),
    )
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["payload"]["team_id"] == "alpha"


async def test_free_text_search_matches_payload(client):
    admin = await admin_token(client)
    await _seed(
        [
            {"event_name": "challenge.solved", "competition_id": "cq", "payload": {"flag_note": "needle-xyz"}},
            {"event_name": "challenge.solved", "competition_id": "cq", "payload": {"flag_note": "something-else"}},
        ]
    )
    resp = await client.get(
        "/api/admin/audit-log",
        params={"q": "needle-xyz", "competition_id": "cq"},
        headers=_auth(admin),
    )
    assert len(resp.json()["items"]) == 1


async def test_pagination(client):
    admin = await admin_token(client)
    await _seed(
        [{"event_name": "team.created", "competition_id": "cp"} for _ in range(5)]
    )
    page = await client.get(
        "/api/admin/audit-log",
        params={"competition_id": "cp", "limit": 2, "offset": 0},
        headers=_auth(admin),
    )
    body = page.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2


async def test_event_names_lists_distinct(client):
    admin = await admin_token(client)
    await _seed(
        [
            {"event_name": "team.created", "competition_id": "cn"},
            {"event_name": "team.created", "competition_id": "cn"},
            {"event_name": "challenge.solved", "competition_id": "cn"},
        ]
    )
    resp = await client.get("/api/admin/audit-log/event-names", headers=_auth(admin))
    names = resp.json()
    assert "team.created" in names and "challenge.solved" in names
    assert len(names) == len(set(names))  # distinct


async def test_change_password_emits_event(client):
    admin = await admin_token(client)
    resp = await client.post(
        "/api/auth/change-password",
        json={"current_password": "changeme", "new_password": "newpassword123"},
        headers=_auth(admin),
    )
    assert resp.status_code == 204
    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "user.password_changed"
                )
            )
        ).scalars().all()
    assert len(events) == 1
