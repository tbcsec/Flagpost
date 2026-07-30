"""Personal API tokens (issue #75).

An administrator (manage_api_tokens) mints a token for a chosen user; the
token authenticates REST requests as that holder with their full effective
permission set. A holder can also view/revoke their own tokens without the
admin permission (self-service, /profile).
"""

from datetime import timedelta

from db import SessionLocal, utcnow
from models.api_token import ApiToken
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, name="Regular User", password="password123") -> dict:
    resp = await client.post(
        "/api/auth/register",
        json={"display_name": name, "password": password},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


async def _login(client, identifier: str, password: str) -> str:
    resp = await client.post(
        "/api/auth/login", json={"identifier": identifier, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _mint(client, admin: str, user_id: str, *, description="Test token", expires_in_days=30):
    resp = await client.post(
        "/api/api-tokens",
        json={
            "user_id": user_id,
            "description": description,
            "expires_in_days": expires_in_days,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- admin-only minting/listing/revoking ------------------------------------


async def test_non_admin_cannot_mint(client):
    reg = await _register(client)
    user_token = await _login(client, reg["user"]["display_name"], "password123")
    resp = await client.post(
        "/api/api-tokens",
        json={"user_id": reg["user"]["id"], "description": "x", "expires_in_days": 1},
        headers=_auth(user_token),
    )
    assert resp.status_code == 403, resp.text


async def test_non_admin_cannot_list_all(client):
    reg = await _register(client)
    user_token = await _login(client, reg["user"]["display_name"], "password123")
    resp = await client.get("/api/api-tokens", headers=_auth(user_token))
    assert resp.status_code == 403, resp.text


async def test_admin_mints_lists_and_revokes(client):
    admin = await admin_token(client)
    reg = await _register(client)
    holder_id = reg["user"]["id"]

    created = await _mint(client, admin, holder_id, description="CI bot")
    assert created["token"].startswith("flp_")
    assert created["user_id"] == holder_id
    assert created["description"] == "CI bot"
    assert created["revoked_at"] is None

    listed = await client.get("/api/api-tokens", headers=_auth(admin))
    assert listed.status_code == 200, listed.text
    ids = [t["id"] for t in listed.json()]
    assert created["id"] in ids
    # Never leaks the raw token or a hash on list.
    assert all("token" not in t and "token_hash" not in t for t in listed.json())

    revoked = await client.delete(f"/api/api-tokens/{created['id']}", headers=_auth(admin))
    assert revoked.status_code == 204, revoked.text

    listed_again = await client.get("/api/api-tokens", headers=_auth(admin))
    row = next(t for t in listed_again.json() if t["id"] == created["id"])
    assert row["revoked_at"] is not None


async def test_mint_for_unknown_user_404s(client):
    admin = await admin_token(client)
    resp = await client.post(
        "/api/api-tokens",
        json={"user_id": "does-not-exist", "description": "x", "expires_in_days": 1},
        headers=_auth(admin),
    )
    assert resp.status_code == 404, resp.text


# --- token authentication ----------------------------------------------------


async def test_token_authenticates_as_holder(client):
    admin = await admin_token(client)
    reg = await _register(client)
    holder_id = reg["user"]["id"]
    created = await _mint(client, admin, holder_id)

    resp = await client.get("/api/auth/me", headers=_auth(created["token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == holder_id

    # The holder's own (non-admin) permission set, not the minting admin's —
    # a token-authenticated request 403s exactly where the holder would.
    forbidden = await client.get("/api/api-tokens", headers=_auth(created["token"]))
    assert forbidden.status_code == 403, forbidden.text


async def test_revoked_token_401s(client):
    admin = await admin_token(client)
    reg = await _register(client)
    created = await _mint(client, admin, reg["user"]["id"])
    await client.delete(f"/api/api-tokens/{created['id']}", headers=_auth(admin))

    resp = await client.get("/api/auth/me", headers=_auth(created["token"]))
    assert resp.status_code == 401, resp.text


async def test_expired_token_401s(client):
    admin = await admin_token(client)
    reg = await _register(client)
    created = await _mint(client, admin, reg["user"]["id"], expires_in_days=1)

    # Force it into the past directly (no clock mocking needed).
    async with SessionLocal() as db:
        token = await db.get(ApiToken, created["id"])
        token.expires_at = utcnow() - timedelta(days=1)
        await db.commit()

    resp = await client.get("/api/auth/me", headers=_auth(created["token"]))
    assert resp.status_code == 401, resp.text


async def test_jwt_login_still_works(client):
    # Sanity: the flp_-prefix branch doesn't disturb the existing JWT path.
    admin = await admin_token(client)
    resp = await client.get("/api/auth/me", headers=_auth(admin))
    assert resp.status_code == 200, resp.text


async def test_invalid_bearer_token_401s(client):
    resp = await client.get("/api/auth/me", headers=_auth("flp_not-a-real-token"))
    assert resp.status_code == 401, resp.text


# --- self-service (own tokens, no manage_api_tokens needed) -----------------


async def test_holder_can_list_and_revoke_own_token(client):
    admin = await admin_token(client)
    reg = await _register(client)
    holder_token = await _login(client, reg["user"]["display_name"], "password123")
    created = await _mint(client, admin, reg["user"]["id"], description="Mine")

    mine = await client.get("/api/api-tokens/me", headers=_auth(holder_token))
    assert mine.status_code == 200, mine.text
    assert [t["id"] for t in mine.json()] == [created["id"]]

    revoke = await client.delete(f"/api/api-tokens/me/{created['id']}", headers=_auth(holder_token))
    assert revoke.status_code == 204, revoke.text

    mine_again = await client.get("/api/api-tokens/me", headers=_auth(holder_token))
    assert mine_again.json()[0]["revoked_at"] is not None


async def test_holder_cannot_revoke_someone_elses_token_via_self_route(client):
    admin = await admin_token(client)
    reg_a = await _register(client, name="Holder A")
    reg_b = await _register(client, name="Holder B")
    b_token = await _login(client, reg_b["user"]["display_name"], "password123")
    created = await _mint(client, admin, reg_a["user"]["id"])

    resp = await client.delete(f"/api/api-tokens/me/{created['id']}", headers=_auth(b_token))
    assert resp.status_code == 404, resp.text


async def test_self_list_only_returns_own_tokens(client):
    admin = await admin_token(client)
    reg_a = await _register(client, name="Holder A2")
    reg_b = await _register(client, name="Holder B2")
    a_token = await _login(client, reg_a["user"]["display_name"], "password123")
    await _mint(client, admin, reg_a["user"]["id"], description="A's token")
    await _mint(client, admin, reg_b["user"]["id"], description="B's token")

    mine = await client.get("/api/api-tokens/me", headers=_auth(a_token))
    assert mine.status_code == 200, mine.text
    assert len(mine.json()) == 1
    assert mine.json()[0]["description"] == "A's token"
