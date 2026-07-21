"""GET /api/auth/me/permissions — effective permissions for frontend gating."""

from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "U"},
    )
    return resp.json()["access_token"]


async def test_admin_has_global_permissions(client):
    admin = await admin_token(client)
    resp = await client.get("/api/auth/me/permissions", headers=_auth(admin))
    assert resp.status_code == 200
    body = resp.json()
    # The seeded admin holds a global Administrator role.
    assert "create_competition" in body["global"]
    assert "manage_roles" in body["global"]


async def test_fresh_user_has_no_permissions(client):
    token = await _register(client, "nobody@example.com")
    resp = await client.get("/api/auth/me/permissions", headers=_auth(token))
    assert resp.json() == {"global": [], "by_competition": {}}


async def test_participant_permissions_are_scoped_to_their_competition(client):
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual",
                  "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()
    token = await _register(client, "joiner@example.com")
    await client.post(f"/api/competitions/{comp['id']}/join", headers=_auth(token))

    body = (
        await client.get("/api/auth/me/permissions", headers=_auth(token))
    ).json()
    assert body["global"] == []
    assert "challenge_view" in body["by_competition"][comp["id"]]
