"""Personal API tokens (issue #75).

Tokens are **self-minted and self-only**: a user creates one for their own
account and it authenticates REST requests as them with their own effective
permission set. Nobody — administrator or otherwise — can mint a token that
acts as another account.

``manage_api_tokens`` is oversight, not issuance: list every token and revoke
any of them.
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


async def _mint(client, actor: str, *, description="Test token", expires_in_days=30):
    """Mint a token for whoever ``actor`` is — the only kind of mint there is."""
    resp = await client.post(
        "/api/api-tokens",
        json={"description": description, "expires_in_days": expires_in_days},
        headers=_auth(actor),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- self-only minting -------------------------------------------------------


async def test_any_user_can_mint_for_themselves(client):
    """No permission is needed to issue a credential for your own account."""
    reg = await _register(client)
    user_token = await _login(client, reg["user"]["display_name"], "password123")

    created = await _mint(client, user_token, description="CI bot")
    assert created["token"].startswith("flp_")
    assert created["user_id"] == reg["user"]["id"]
    assert created["description"] == "CI bot"
    assert created["revoked_at"] is None


async def test_admin_cannot_mint_a_token_for_another_user(client):
    """Regression test for the privilege-escalation shape this feature had.

    The create route has no holder field, so supplying one must not redirect
    the token: an administrator posting another account's id still ends up with
    a token for *themselves*, which is useless as an impersonation primitive.
    """
    admin = await admin_token(client)
    victim = await _register(client, name="Victim")

    resp = await client.post(
        "/api/api-tokens",
        json={
            "user_id": victim["user"]["id"],  # ignored — no such field exists
            "description": "escalation attempt",
            "expires_in_days": 30,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()

    # The token belongs to the admin who asked for it, never to the victim.
    assert created["user_id"] != victim["user"]["id"]

    me = await client.get("/api/auth/me", headers=_auth(created["token"]))
    assert me.status_code == 200, me.text
    assert me.json()["id"] != victim["user"]["id"]


async def test_token_management_permission_does_not_grant_impersonation(client):
    """`manage_api_tokens` must be an oversight grant, not a way to act as
    someone else — the whole reason minting moved to self-service."""
    admin = await admin_token(client)
    # A custom global role whose only power is token oversight.
    role = await client.post(
        "/api/roles",
        json={
            "name": "Integrations",
            "scope": "global",
            "permissions": ["manage_api_tokens"],
        },
        headers=_auth(admin),
    )
    assert role.status_code == 201, role.text
    reg = await _register(client, name="Integrations Lead")
    assign = await client.post(
        "/api/roles/assignments",
        json={"email": reg["user"]["display_name"], "role_id": role.json()["id"]},
        headers=_auth(admin),
    )
    assert assign.status_code == 201, assign.text
    lead = await _login(client, reg["user"]["display_name"], "password123")

    # They can see the oversight list...
    assert (await client.get("/api/api-tokens", headers=_auth(lead))).status_code == 200

    # ...but a token they mint is theirs, and carries only their own authority.
    created = await _mint(client, lead, description="not an escalation")
    assert created["user_id"] == reg["user"]["id"]
    escalated = await client.get("/api/users", headers=_auth(created["token"]))
    assert escalated.status_code == 403, escalated.text


# --- token authentication ----------------------------------------------------


async def test_token_authenticates_as_its_owner(client):
    reg = await _register(client)
    user_token = await _login(client, reg["user"]["display_name"], "password123")
    created = await _mint(client, user_token)

    resp = await client.get("/api/auth/me", headers=_auth(created["token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == reg["user"]["id"]

    # The owner's own (non-admin) permission set — it 403s exactly where they do.
    forbidden = await client.get("/api/api-tokens", headers=_auth(created["token"]))
    assert forbidden.status_code == 403, forbidden.text


async def test_revoked_token_401s(client):
    reg = await _register(client)
    user_token = await _login(client, reg["user"]["display_name"], "password123")
    created = await _mint(client, user_token)
    await client.delete(
        f"/api/api-tokens/me/{created['id']}", headers=_auth(user_token)
    )

    resp = await client.get("/api/auth/me", headers=_auth(created["token"]))
    assert resp.status_code == 401, resp.text


async def test_expired_token_401s(client):
    reg = await _register(client)
    user_token = await _login(client, reg["user"]["display_name"], "password123")
    created = await _mint(client, user_token, expires_in_days=1)

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


# --- self-service list/revoke -----------------------------------------------


async def test_owner_can_list_and_revoke_own_token(client):
    reg = await _register(client)
    user_token = await _login(client, reg["user"]["display_name"], "password123")
    created = await _mint(client, user_token, description="Mine")

    mine = await client.get("/api/api-tokens/me", headers=_auth(user_token))
    assert mine.status_code == 200, mine.text
    assert [t["id"] for t in mine.json()] == [created["id"]]

    revoke = await client.delete(
        f"/api/api-tokens/me/{created['id']}", headers=_auth(user_token)
    )
    assert revoke.status_code == 204, revoke.text

    mine_again = await client.get("/api/api-tokens/me", headers=_auth(user_token))
    assert mine_again.json()[0]["revoked_at"] is not None


async def test_cannot_revoke_someone_elses_token_via_self_route(client):
    reg_a = await _register(client, name="Holder A")
    reg_b = await _register(client, name="Holder B")
    a_token = await _login(client, reg_a["user"]["display_name"], "password123")
    b_token = await _login(client, reg_b["user"]["display_name"], "password123")
    created = await _mint(client, a_token)

    resp = await client.delete(
        f"/api/api-tokens/me/{created['id']}", headers=_auth(b_token)
    )
    assert resp.status_code == 404, resp.text


async def test_self_list_only_returns_own_tokens(client):
    reg_a = await _register(client, name="Holder A2")
    reg_b = await _register(client, name="Holder B2")
    a_token = await _login(client, reg_a["user"]["display_name"], "password123")
    b_token = await _login(client, reg_b["user"]["display_name"], "password123")
    await _mint(client, a_token, description="A's token")
    await _mint(client, b_token, description="B's token")

    mine = await client.get("/api/api-tokens/me", headers=_auth(a_token))
    assert mine.status_code == 200, mine.text
    assert len(mine.json()) == 1
    assert mine.json()[0]["description"] == "A's token"


# --- oversight (manage_api_tokens): list all, revoke any --------------------


async def test_admin_lists_every_token_and_revokes_any(client):
    admin = await admin_token(client)
    reg = await _register(client)
    user_token = await _login(client, reg["user"]["display_name"], "password123")
    created = await _mint(client, user_token, description="Someone else's")

    listed = await client.get("/api/api-tokens", headers=_auth(admin))
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert created["id"] in [t["id"] for t in rows]
    # The holder's name is resolved for the cross-account view.
    row = next(t for t in rows if t["id"] == created["id"])
    assert row["user_display_name"] == reg["user"]["display_name"]
    # Never leaks the raw token or a hash on list.
    assert all("token" not in t and "token_hash" not in t for t in rows)

    revoked = await client.delete(
        f"/api/api-tokens/{created['id']}", headers=_auth(admin)
    )
    assert revoked.status_code == 204, revoked.text

    # Revocation is effective immediately for the holder.
    resp = await client.get("/api/auth/me", headers=_auth(created["token"]))
    assert resp.status_code == 401, resp.text


async def test_non_admin_cannot_list_all(client):
    reg = await _register(client)
    user_token = await _login(client, reg["user"]["display_name"], "password123")
    resp = await client.get("/api/api-tokens", headers=_auth(user_token))
    assert resp.status_code == 403, resp.text


async def test_non_admin_cannot_revoke_someone_elses_token(client):
    reg_a = await _register(client, name="Holder A3")
    reg_b = await _register(client, name="Holder B3")
    a_token = await _login(client, reg_a["user"]["display_name"], "password123")
    b_token = await _login(client, reg_b["user"]["display_name"], "password123")
    created = await _mint(client, a_token)

    resp = await client.delete(
        f"/api/api-tokens/{created['id']}", headers=_auth(b_token)
    )
    assert resp.status_code == 403, resp.text
