"""Competition cloning (Phase 9): copies config (settings/categories/challenges/
hints/attachments/surveys/module state) into a fresh competition with a new name
and a clean slate — no participants, submissions, or scores carried over."""

from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def _competition(client, admin, **over) -> str:
    body = {
        "name": "Baseline",
        "participation_mode": "individual",
        "visibility": "private",
        "description": "The template",
        **over,
    }
    return (await client.post("/api/competitions", json=body, headers=_auth(admin))).json()["id"]


async def _challenge(client, admin, comp, flag="flag{clone}", points=100, category_id=None):
    body = {
        "title": "Chal",
        "points": points,
        "flag": flag,
        # Copied to the clone, unlike release_at (#262).
        "connection_info": "nc box.example.com 1337",
    }
    if category_id:
        body["category_id"] = category_id
    cid = (
        await client.post(
            f"/api/competitions/{comp}/challenges", json=body, headers=_auth(admin)
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/publish", headers=_auth(admin)
    )
    return cid


async def _clone(client, admin, comp, name="Clone"):
    return await client.post(
        f"/api/competitions/{comp}/clone", json={"name": name}, headers=_auth(admin)
    )


async def test_clone_copies_config_with_new_name_and_clean_slate(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin, start_at="2030-01-01T00:00:00Z")
    # A category + a challenge referencing it, plus a hint.
    cat = (
        await client.post(
            f"/api/competitions/{comp}/categories", json={"name": "Web"}, headers=_auth(admin)
        )
    ).json()["id"]
    chal = await _challenge(client, admin, comp, flag="flag{same}", category_id=cat)
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints",
        json={"body": "look harder", "cost": 10},
        headers=_auth(admin),
    )
    # A hidden, scheduled hint must clone as hidden/scheduled — never published (#213).
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints",
        json={
            "body": "secret hint",
            "cost": 0,
            "hidden": True,
            "release_at": "2030-01-01T00:00:00Z",
        },
        headers=_auth(admin),
    )

    resp = await _clone(client, admin, comp, name="Round 2")
    assert resp.status_code == 201, resp.text
    clone = resp.json()
    assert clone["name"] == "Round 2"
    assert clone["id"] != comp
    assert clone["participation_mode"] == "individual"
    assert clone["visibility"] == "private"
    assert clone["description"] == "The template"
    # Schedule cleared, fresh invite code.
    assert clone["start_at"] is None
    assert clone["invite_code"] != (
        await client.get(f"/api/competitions/{comp}", headers=_auth(admin))
    ).json()["invite_code"]

    # Challenges + categories carried over.
    cats = (
        await client.get(f"/api/competitions/{clone['id']}/categories", headers=_auth(admin))
    ).json()
    assert [c["name"] for c in cats] == ["Web"]
    chals = (
        await client.get(f"/api/competitions/{clone['id']}/challenges", headers=_auth(admin))
    ).json()
    assert len(chals) == 1 and chals[0]["title"] == "Chal"
    # The cloned challenge is categorized under the *clone's* category, not the source's.
    assert chals[0]["category_id"] == cats[0]["id"]
    # Connection info comes along — a clone usually re-runs the same event, and
    # silently dropping authored data would be worse than editing it (#262).
    assert chals[0]["connection_info"] == "nc box.example.com 1337"
    new_chal = chals[0]["id"]
    hints = (
        await client.get(
            f"/api/competitions/{clone['id']}/challenges/{new_chal}/hints", headers=_auth(admin)
        )
    ).json()
    assert len(hints) == 2
    hidden = next(h for h in hints if h["body"] == "secret hint")
    assert hidden["hidden"] is True and hidden["release_at"] is not None
    visible = next(h for h in hints if h["body"] == "look harder")
    assert visible["hidden"] is False


async def test_cloned_flag_still_solves(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin, visibility="public")
    await _challenge(client, admin, comp, flag="flag{secret}")

    clone = (await _clone(client, admin, comp)).json()
    new_chal = (
        await client.get(f"/api/competitions/{clone['id']}/challenges", headers=_auth(admin))
    ).json()[0]["id"]

    # A brand-new competitor joins the CLONE and solves with the original flag.
    player = await _register(client, "solver@example.com")
    await client.post(f"/api/competitions/{clone['id']}/join", headers=_auth(player))
    solve = await client.post(
        f"/api/competitions/{clone['id']}/challenges/{new_chal}/submit",
        json={"flag": "flag{secret}"},
        headers=_auth(player),
    )
    assert solve.json()["correct"] is True


async def test_clone_duplicates_attachments(client, object_storage):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    chal = await _challenge(client, admin, comp)
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/attachments",
        files={"file": ("handout.zip", b"PK\x03\x04clone-me", "application/zip")},
        headers=_auth(admin),
    )

    clone = (await _clone(client, admin, comp)).json()
    new_chal = (
        await client.get(f"/api/competitions/{clone['id']}/challenges", headers=_auth(admin))
    ).json()[0]["id"]
    atts = (
        await client.get(
            f"/api/competitions/{clone['id']}/challenges/{new_chal}/attachments",
            headers=_auth(admin),
        )
    ).json()
    assert len(atts) == 1 and atts[0]["filename"] == "handout.zip"
    # The stored object was duplicated under the clone's namespace, same bytes
    # (object_key isn't serialized, §attachment schema — inspect storage directly).
    clone_keys = [k for k in object_storage._objects if k.startswith(f"{clone['id']}/")]
    assert len(clone_keys) == 1
    assert object_storage.get(clone_keys[0]) == b"PK\x03\x04clone-me"


async def test_clone_copies_surveys_closed(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    survey = (
        await client.post(
            f"/api/competitions/{comp}/surveys",
            json={"title": "Feedback", "description": "?"},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/surveys/{survey}/questions",
        json={"prompt": "Rate us", "type": "rating_1_5"},
        headers=_auth(admin),
    )
    await client.post(f"/api/competitions/{comp}/surveys/{survey}/open", headers=_auth(admin))

    clone = (await _clone(client, admin, comp)).json()
    surveys = (
        await client.get(f"/api/competitions/{clone['id']}/surveys", headers=_auth(admin))
    ).json()
    assert len(surveys) == 1 and surveys[0]["title"] == "Feedback"
    assert surveys[0]["is_open"] is False  # cloned as a closed template
    detail = (
        await client.get(
            f"/api/competitions/{clone['id']}/surveys/{surveys[0]['id']}", headers=_auth(admin)
        )
    ).json()
    assert len(detail["questions"]) == 1


async def test_clone_leaves_participants_and_solves_behind(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin, visibility="public")
    chal = await _challenge(client, admin, comp, flag="flag{x}")
    player = await _register(client, "orig@example.com")
    await client.post(f"/api/competitions/{comp}/join", headers=_auth(player))
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{x}"},
        headers=_auth(player),
    )

    clone = (await _clone(client, admin, comp)).json()
    # Clean slate: the clone's scoreboard has no participants/solves.
    board = (
        await client.get(f"/api/competitions/{clone['id']}/scoreboard", headers=_auth(admin))
    ).json()
    assert board["entries"] == []


async def test_clone_requires_create_permission_and_404(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    outsider = await _register(client, "outsider@example.com")
    denied = await _clone(client, outsider, comp)
    assert denied.status_code == 403

    missing = await client.post(
        "/api/competitions/does-not-exist/clone", json={"name": "X"}, headers=_auth(admin)
    )
    assert missing.status_code == 404
