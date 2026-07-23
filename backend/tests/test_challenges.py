"""Challenge + category endpoints: flag secrecy, draft visibility, RBAC, events."""

import json

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
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


async def _make_competition(client) -> str:
    token = await admin_token(client)
    resp = await client.post(
        "/api/competitions", json={"name": "CTF"}, headers=_auth(token)
    )
    return resp.json()["id"]


async def _assign_participant(user_id: str, competition_id: str) -> None:
    """Give a user the viewer-level Participant role for one competition (§7.5)."""
    async with SessionLocal() as session:
        role = await session.scalar(
            select(Role).where(Role.name == "Participant")
        )
        session.add(
            RoleAssignment(
                user_id=user_id, competition_id=competition_id, role_id=role.id
            )
        )
        await session.commit()


async def _events(name: str):
    async with SessionLocal() as session:
        return (
            await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.event_name == name)
            )
        ).scalars().all()


FLAG_WORDS = ("flag_hash", "flag_salt", "flag_regex", "supersecret", "changeme-flag")


async def test_create_challenge_hides_flag_material_everywhere(client):
    comp = await _make_competition(client)
    token = await admin_token(client)

    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={
            "title": "Baby RSA",
            "points": 250,
            "flag": "supersecret",
            "case_insensitive": True,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["has_flag"] is True
    assert body["state"] == "draft"

    # No flag material in create, list, or detail responses (§13.2).
    listing = (
        await client.get(
            f"/api/competitions/{comp}/challenges", headers=_auth(token)
        )
    ).json()
    detail = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{body['id']}",
            headers=_auth(token),
        )
    ).json()
    for payload in (body, listing, detail):
        text = json.dumps(payload)
        for word in FLAG_WORDS:
            assert word not in text, f"flag material {word!r} leaked in {text[:200]}"

    assert len(await _events("challenge.created")) == 1


async def test_plain_user_cannot_view_or_create(client):
    comp = await _make_competition(client)
    token, _ = await _register(client, "outsider@example.com")

    assert (
        await client.get(
            f"/api/competitions/{comp}/challenges", headers=_auth(token)
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Nope"},
            headers=_auth(token),
        )
    ).status_code == 403


async def test_viewer_sees_published_only_and_drafts_404(client):
    comp = await _make_competition(client)
    admin = await admin_token(client)

    draft = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Draft", "flag": "x-flag"},
            headers=_auth(admin),
        )
    ).json()
    published = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Live", "flag": "y-flag"},
            headers=_auth(admin),
        )
    ).json()
    await client.post(
        f"/api/competitions/{comp}/challenges/{published['id']}/publish",
        headers=_auth(admin),
    )

    viewer_token, viewer_id = await _register(client, "viewer@example.com")
    await _assign_participant(viewer_id, comp)

    listing = (
        await client.get(
            f"/api/competitions/{comp}/challenges", headers=_auth(viewer_token)
        )
    ).json()
    assert [c["title"] for c in listing] == ["Live"]

    # Draft detail is a 404 for viewers, indistinguishable from missing.
    resp = await client.get(
        f"/api/competitions/{comp}/challenges/{draft['id']}",
        headers=_auth(viewer_token),
    )
    assert resp.status_code == 404

    # Admin still sees both.
    admin_listing = (
        await client.get(
            f"/api/competitions/{comp}/challenges", headers=_auth(admin)
        )
    ).json()
    assert {c["title"] for c in admin_listing} == {"Draft", "Live"}


async def test_publish_requires_flag_and_emits_event(client):
    comp = await _make_competition(client)
    admin = await admin_token(client)

    flagless = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "No flag yet"},
            headers=_auth(admin),
        )
    ).json()
    assert flagless["has_flag"] is False

    blocked = await client.post(
        f"/api/competitions/{comp}/challenges/{flagless['id']}/publish",
        headers=_auth(admin),
    )
    assert blocked.status_code == 400

    await client.patch(
        f"/api/competitions/{comp}/challenges/{flagless['id']}",
        json={"flag": "now-set"},
        headers=_auth(admin),
    )
    published = await client.post(
        f"/api/competitions/{comp}/challenges/{flagless['id']}/publish",
        headers=_auth(admin),
    )
    assert published.status_code == 200
    assert published.json()["state"] == "published"
    assert len(await _events("challenge.published")) == 1

    # Unpublish returns it to draft via challenge.updated.
    back = await client.post(
        f"/api/competitions/{comp}/challenges/{flagless['id']}/unpublish",
        headers=_auth(admin),
    )
    assert back.json()["state"] == "draft"


async def test_update_flag_settings_requires_reentering_flag(client):
    comp = await _make_competition(client)
    admin = await admin_token(client)
    challenge = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "C", "flag": "abc"},
            headers=_auth(admin),
        )
    ).json()

    # Flipping case_insensitive without re-supplying the flag would desync the
    # stored hash -> 400.
    resp = await client.patch(
        f"/api/competitions/{comp}/challenges/{challenge['id']}",
        json={"case_insensitive": True},
        headers=_auth(admin),
    )
    assert resp.status_code == 400

    # Supplying the flag alongside works.
    ok = await client.patch(
        f"/api/competitions/{comp}/challenges/{challenge['id']}",
        json={"case_insensitive": True, "flag": "abc"},
        headers=_auth(admin),
    )
    assert ok.status_code == 200
    updated_events = await _events("challenge.updated")
    assert updated_events[-1].payload["changed_fields"] == [
        "case_insensitive",
        "flag",
    ]


async def test_regex_flag_type(client):
    comp = await _make_competition(client)
    admin = await admin_token(client)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "Regex", "flag_type": "regex", "flag": r"CTF\{[0-9]+\}"},
        headers=_auth(admin),
    )
    assert resp.status_code == 201
    assert resp.json()["has_flag"] is True
    assert resp.json()["flag_type"] == "regex"


async def test_delete_challenge(client):
    comp = await _make_competition(client)
    admin = await admin_token(client)
    challenge = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Doomed", "flag": "z"},
            headers=_auth(admin),
        )
    ).json()

    resp = await client.delete(
        f"/api/competitions/{comp}/challenges/{challenge['id']}",
        headers=_auth(admin),
    )
    assert resp.status_code == 204
    assert (
        await client.get(
            f"/api/competitions/{comp}/challenges/{challenge['id']}",
            headers=_auth(admin),
        )
    ).status_code == 404
    assert len(await _events("challenge.deleted")) == 1


async def test_categories_crud_and_set_null_on_delete(client):
    comp = await _make_competition(client)
    admin = await admin_token(client)

    category = (
        await client.post(
            f"/api/competitions/{comp}/categories",
            json={"name": "web"},
            headers=_auth(admin),
        )
    ).json()
    assert len(await _events("category.created")) == 1

    dup = await client.post(
        f"/api/competitions/{comp}/categories",
        json={"name": "web"},
        headers=_auth(admin),
    )
    assert dup.status_code == 409

    challenge = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "XSS", "category_id": category["id"], "flag": "f"},
            headers=_auth(admin),
        )
    ).json()
    assert challenge["category_id"] == category["id"]

    # Deleting the category uncategorizes, never deletes, the challenge.
    await client.delete(
        f"/api/competitions/{comp}/categories/{category['id']}",
        headers=_auth(admin),
    )
    after = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{challenge['id']}",
            headers=_auth(admin),
        )
    ).json()
    assert after["category_id"] is None
    assert len(await _events("category.deleted")) == 1


async def test_category_from_another_competition_is_rejected(client):
    admin = await admin_token(client)
    comp_a = await _make_competition(client)
    comp_b = (
        await client.post(
            "/api/competitions", json={"name": "Other"}, headers=_auth(admin)
        )
    ).json()["id"]
    category_b = (
        await client.post(
            f"/api/competitions/{comp_b}/categories",
            json={"name": "pwn"},
            headers=_auth(admin),
        )
    ).json()

    resp = await client.post(
        f"/api/competitions/{comp_a}/challenges",
        json={"title": "Smuggled", "category_id": category_b["id"]},
        headers=_auth(admin),
    )
    assert resp.status_code == 400


# --- bulk YAML import/export (ctfcli) ----------------------------------------


async def test_challenge_yaml_import_and_export_roundtrip(client):
    import io
    import zipfile

    import yaml

    admin = await admin_token(client)
    comp = await _make_competition(client)

    # Build a ctfcli-style import zip with two challenges (static + dynamic).
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "welcome/challenge.yml",
            yaml.safe_dump({
                "name": "Welcome",
                "category": "misc",
                "description": "Say hi",
                "value": 50,
                "flags": ["flag{hi}"],
                "tags": ["easy-tag"],
                "state": "visible",
                "hints": [{"content": "wave", "cost": 5}],
            }),
        )
        zf.writestr(
            "hard/challenge.yml",
            yaml.safe_dump({
                "name": "Hard One",
                "category": "pwn",
                "description": "tough",
                "type": "dynamic",
                "value": 500,
                "extra": {"initial": 500, "decay": 20, "minimum": 100, "difficulty": "Hard"},
                "flags": [{"type": "regex", "content": "flag\\{.*\\}"}],
                "prerequisites": ["Welcome"],
            }),
        )

    imp = await client.post(
        f"/api/competitions/{comp}/challenges/import",
        files={"file": ("challenges.zip", buf.getvalue(), "application/zip")},
        headers=_auth(admin),
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["created"] == 2

    listing = {c["title"]: c for c in (await client.get(f"/api/competitions/{comp}/challenges", headers=_auth(admin))).json()}
    assert set(listing) == {"Welcome", "Hard One"}
    assert listing["Hard One"]["scoring_type"] == "dynamic"
    assert listing["Hard One"]["decay"] == 20 and listing["Hard One"]["difficulty"] == "Hard"
    # Prerequisite resolved by title → the Welcome challenge's id.
    assert listing["Hard One"]["prerequisites"] == [listing["Welcome"]["id"]]

    # A re-import is additive: both titles already exist → skipped.
    again = await client.post(
        f"/api/competitions/{comp}/challenges/import",
        files={"file": ("challenges.zip", buf.getvalue(), "application/zip")},
        headers=_auth(admin),
    )
    assert again.json() == {"created": 0, "skipped": 2, "errors": []}

    # Export returns a zip with a challenge.yml per challenge.
    exp = await client.get(f"/api/competitions/{comp}/challenges/export", headers=_auth(admin))
    assert exp.status_code == 200
    out = zipfile.ZipFile(io.BytesIO(exp.content))
    ymls = [n for n in out.namelist() if n.endswith("challenge.yml")]
    assert len(ymls) == 2
    # The regex flag round-trips; the static one is omitted (hashed).
    hard = yaml.safe_load(out.read([n for n in ymls if n.startswith("hard-one")][0]))
    assert hard["flags"] == [{"type": "regex", "content": "flag\\{.*\\}"}]
