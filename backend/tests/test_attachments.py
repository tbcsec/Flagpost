"""Attachment endpoints: storage, signed URLs, RBAC, scoping (§13.3)."""

from sqlalchemy import select

from db import SessionLocal
from models.role import Role, RoleAssignment
from tests.conftest import admin_token


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


async def _setup_challenge(client, publish=False) -> tuple[str, str, str]:
    """Return (admin_token, competition_id, challenge_id)."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions", json={"name": "CTF"}, headers=_auth(admin)
        )
    ).json()["id"]
    challenge = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Files", "flag": "f"},
            headers=_auth(admin),
        )
    ).json()
    if publish:
        await client.post(
            f"/api/competitions/{comp}/challenges/{challenge['id']}/publish",
            headers=_auth(admin),
        )
    return admin, comp, challenge["id"]


def _upload(client, comp, chal, token, name="handout.zip", content=b"PK\x03\x04data"):
    return client.post(
        f"/api/competitions/{comp}/challenges/{chal}/attachments",
        files={"file": (name, content, "application/zip")},
        headers=_auth(token),
    )


async def test_upload_stores_object_under_namespaced_key(client, object_storage):
    admin, comp, chal = await _setup_challenge(client)

    resp = await _upload(client, comp, chal, admin)
    assert resp.status_code == 201
    body = resp.json()
    assert body["filename"] == "handout.zip"
    assert body["size_bytes"] == len(b"PK\x03\x04data")
    # The storage key is namespaced by competition + challenge (§13.3) and is
    # not exposed in the response.
    assert "object_key" not in body

    async with SessionLocal() as session:
        from models.attachment import Attachment

        attachment = await session.scalar(select(Attachment))
    assert attachment.object_key.startswith(f"{comp}/{chal}/")
    assert object_storage.exists(attachment.object_key)
    assert object_storage.read(attachment.object_key) == b"PK\x03\x04data"


async def test_signed_url_is_gated_and_scoped(client):
    admin, comp, chal = await _setup_challenge(client, publish=True)
    attachment = (await _upload(client, comp, chal, admin)).json()

    # A participant (viewer) on a published challenge can get a signed URL.
    viewer_token, viewer_id = await _register(client, "viewer@example.com")
    await _assign_participant(viewer_id, comp)
    resp = await client.get(
        f"/api/competitions/{comp}/challenges/{chal}/attachments/{attachment['id']}/url",
        headers=_auth(viewer_token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith("memory://")
    assert body["expires_in_seconds"] > 0

    # An outsider with no role in the competition is refused (403).
    outsider, _ = await _register(client, "outsider@example.com")
    denied = await client.get(
        f"/api/competitions/{comp}/challenges/{chal}/attachments/{attachment['id']}/url",
        headers=_auth(outsider),
    )
    assert denied.status_code == 403


async def test_draft_attachments_hidden_from_viewers(client):
    admin, comp, chal = await _setup_challenge(client, publish=False)  # draft
    attachment = (await _upload(client, comp, chal, admin)).json()

    viewer_token, viewer_id = await _register(client, "viewer@example.com")
    await _assign_participant(viewer_id, comp)

    # The challenge is a draft, so its attachments 404 for a viewer (same gate
    # as the challenge itself).
    listing = await client.get(
        f"/api/competitions/{comp}/challenges/{chal}/attachments",
        headers=_auth(viewer_token),
    )
    assert listing.status_code == 404
    url = await client.get(
        f"/api/competitions/{comp}/challenges/{chal}/attachments/{attachment['id']}/url",
        headers=_auth(viewer_token),
    )
    assert url.status_code == 404


async def test_participant_cannot_upload(client):
    admin, comp, chal = await _setup_challenge(client, publish=True)
    viewer_token, viewer_id = await _register(client, "viewer@example.com")
    await _assign_participant(viewer_id, comp)

    resp = await _upload(client, comp, chal, viewer_token)
    assert resp.status_code == 403


async def test_delete_removes_object_and_row(client, object_storage):
    admin, comp, chal = await _setup_challenge(client)
    attachment = (await _upload(client, comp, chal, admin)).json()

    async with SessionLocal() as session:
        from models.attachment import Attachment

        key = (await session.scalar(select(Attachment.object_key)))
    assert object_storage.exists(key)

    resp = await client.delete(
        f"/api/competitions/{comp}/challenges/{chal}/attachments/{attachment['id']}",
        headers=_auth(admin),
    )
    assert resp.status_code == 204
    assert not object_storage.exists(key)

    listing = await client.get(
        f"/api/competitions/{comp}/challenges/{chal}/attachments",
        headers=_auth(admin),
    )
    assert listing.json() == []


async def test_deleting_challenge_cleans_up_objects(client, object_storage):
    admin, comp, chal = await _setup_challenge(client)
    await _upload(client, comp, chal, admin)

    async with SessionLocal() as session:
        from models.attachment import Attachment

        key = await session.scalar(select(Attachment.object_key))
    assert object_storage.exists(key)

    await client.delete(
        f"/api/competitions/{comp}/challenges/{chal}", headers=_auth(admin)
    )
    # Rows cascade; the object must be removed too, not orphaned (§13.3).
    assert not object_storage.exists(key)


async def test_empty_file_rejected(client):
    admin, comp, chal = await _setup_challenge(client)
    resp = await _upload(client, comp, chal, admin, content=b"")
    assert resp.status_code == 400
