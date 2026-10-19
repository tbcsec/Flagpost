"""manage_modules permission (#168): enabling/disabling a competition's optional
modules is gated on the new competition-scoped manage_modules, split out of
edit_competition so it can be delegated or withheld on its own."""

from sqlalchemy import select

from db import SessionLocal
from models.role import Role, RoleAssignment
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _competition(client) -> str:
    admin = await admin_token(client)
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _grant_custom_role(user_id: str, competition_id: str, name: str, perms: list[str]) -> None:
    async with SessionLocal() as db:
        role = Role(name=name, scope="competition", permissions=perms)
        db.add(role)
        await db.flush()
        db.add(RoleAssignment(user_id=user_id, competition_id=competition_id, role_id=role.id))
        await db.commit()


async def test_module_catalog_lists_optional_modules(client):
    """The at-creation picker source (#252): the site-level catalog lists the
    optional modules by id + name, and never the required-core ones."""
    admin = await admin_token(client)
    resp = await client.get("/api/modules", headers=_auth(admin))
    assert resp.status_code == 200
    entries = resp.json()
    ids = {m["id"] for m in entries}
    assert {"ai", "analytics", "automations", "certificates", "feedback"} <= ids
    # Required-core modules are always on and never offered as opt-outs.
    assert "challenges" not in ids
    assert "scoring" not in ids
    # Every entry carries a display name and a one-line description for the row.
    assert all(m["name"] for m in entries)
    assert all(m["description"] for m in entries)


async def test_module_catalog_requires_create_competition(client):
    """Gated on create_competition — a plain participant can't read it."""
    token, _ = await _register(client, "nocreate@example.com")
    resp = await client.get("/api/modules", headers=_auth(token))
    assert resp.status_code == 403


async def test_edit_competition_alone_cannot_manage_modules(client):
    """The point of #168: edit_competition no longer implies module management."""
    comp = await _competition(client)
    token, uid = await _register(client, "settings-only@example.com")
    await _grant_custom_role(uid, comp, "Settings only", ["edit_competition"])
    auth = _auth(token)

    listing = await client.get(f"/api/competitions/{comp}/modules", headers=auth)
    assert listing.status_code == 403
    toggled = await client.put(
        f"/api/competitions/{comp}/modules/analytics",
        json={"enabled": False},
        headers=auth,
    )
    assert toggled.status_code == 403


async def test_manage_modules_grants_the_management_screen(client):
    comp = await _competition(client)
    token, uid = await _register(client, "modmgr@example.com")
    await _grant_custom_role(uid, comp, "Module manager", ["challenge_view", "manage_modules"])
    auth = _auth(token)

    listing = await client.get(f"/api/competitions/{comp}/modules", headers=auth)
    assert listing.status_code == 200
    off = await client.put(
        f"/api/competitions/{comp}/modules/analytics", json={"enabled": False}, headers=auth
    )
    assert off.status_code == 200 and off.json()["enabled"] is False
    on = await client.put(
        f"/api/competitions/{comp}/modules/analytics", json={"enabled": True}, headers=auth
    )
    assert on.status_code == 200 and on.json()["enabled"] is True


async def test_judge_retains_module_management(client):
    """Regression: Judge (a built-in role) keeps module management — manage_modules
    is in JUDGE_PERMISSIONS and reaches existing installs via the startup re-sync."""
    comp = await _competition(client)
    token, uid = await _register(client, "thejudge@example.com")
    async with SessionLocal() as db:
        judge = await db.scalar(select(Role).where(Role.name == "Judge"))
        db.add(RoleAssignment(user_id=uid, competition_id=comp, role_id=judge.id))
        await db.commit()

    r = await client.put(
        f"/api/competitions/{comp}/modules/analytics", json={"enabled": False}, headers=_auth(token)
    )
    assert r.status_code == 200


async def test_manage_modules_in_catalog_under_competition_management(client):
    admin = await admin_token(client)
    cat = (await client.get("/api/roles/catalog", headers=_auth(admin))).json()
    entry = next((c for c in cat if c["key"] == "manage_modules"), None)
    assert entry is not None
    assert entry["scope"] == "competition"
    assert entry["category"] == "Competition Management"


async def test_inert_modules_report_when_they_need_site_setup(client):
    """#502: AI, challenge instances and the code judge do nothing until an
    administrator switches them on site-wide. The competition inventory, the
    toggle response and the at-creation catalog all say which still need it."""
    from models.ai import AI_SETTINGS_ID, AiSettings

    admin = await admin_token(client)
    comp = await _competition(client)

    def waiting(entries) -> set[str]:
        return {m["id"] for m in entries if m["needs_setup"]}

    inventory = (await client.get(f"/api/competitions/{comp}/modules", headers=_auth(admin))).json()
    assert waiting(inventory) == {"ai", "instances", "judge"}
    assert all(isinstance(m["description"], str) for m in inventory)
    catalog = (await client.get("/api/modules", headers=_auth(admin))).json()
    assert waiting(catalog) == {"ai", "instances", "judge"}

    # Switch the AI assistant on site-wide: it no longer needs setup anywhere.
    async with SessionLocal() as db:
        row = await db.get(AiSettings, AI_SETTINGS_ID)
        if row is None:
            row = AiSettings(id=AI_SETTINGS_ID)
            db.add(row)
        row.enabled = True
        row.base_url = "https://ai.example.com/v1"
        row.model = "model"
        await db.commit()

    inventory = (await client.get(f"/api/competitions/{comp}/modules", headers=_auth(admin))).json()
    assert waiting(inventory) == {"instances", "judge"}

    # The judge configured but switched off still needs setup; switched on, only
    # the judge clears.
    from models.judge import JUDGE_SETTINGS_ID, JudgeSettings

    async with SessionLocal() as db:
        db.add(JudgeSettings(id=JUDGE_SETTINGS_ID, enabled=False))
        await db.commit()
    inventory = (await client.get(f"/api/competitions/{comp}/modules", headers=_auth(admin))).json()
    assert waiting(inventory) == {"instances", "judge"}
    async with SessionLocal() as db:
        (await db.get(JudgeSettings, JUDGE_SETTINGS_ID)).enabled = True
        await db.commit()
    inventory = (await client.get(f"/api/competitions/{comp}/modules", headers=_auth(admin))).json()
    assert waiting(inventory) == {"instances"}
    toggled = (
        await client.put(
            f"/api/competitions/{comp}/modules/instances",
            json={"enabled": False},
            headers=_auth(admin),
        )
    ).json()
    assert toggled["needs_setup"] is True and toggled["enabled"] is False
    assert toggled["description"]


async def test_modules_in_use_follows_site_setup_or_existing_data(client):
    """#511: the sidebar's AI transcripts and Instances entries show only when
    the module is switched on site-wide, or the competition already has its
    data. A member without the page's permission learns nothing."""
    from models.ai import AI_SETTINGS_ID, AiConversation, AiSettings
    from models.challenge_instancing import ChallengeDeployment

    admin = await admin_token(client)
    comp = await _competition(client)
    ada, ada_id = await _register(client, "ada@example.com")
    await _grant_custom_role(ada_id, comp, "Member", ["challenge_view"])
    url = f"/api/competitions/{comp}/modules/in-use"

    # Fresh install: nothing configured, no data.
    assert (await client.get(url, headers=_auth(admin))).json() == {"ai": False, "instances": False}
    # A plain member holds neither page's permission: always false.
    assert (await client.get(url, headers=_auth(ada))).json() == {"ai": False, "instances": False}

    # Data from an earlier configuration counts: a deployment spec here.
    async with SessionLocal() as db:
        chal = (
            await client.post(
                f"/api/competitions/{comp}/challenges",
                json={"title": "Pwn", "points": 100, "flag": "flag{x}"},
                headers=_auth(admin),
            )
        ).json()["id"]
        db.add(ChallengeDeployment(competition_id=comp, challenge_id=chal, backend="docker", image_ref="img:1"))
        await db.commit()
    assert (await client.get(url, headers=_auth(admin))).json() == {"ai": False, "instances": True}

    # Switching AI on site-wide makes it of use everywhere, with no data yet.
    async with SessionLocal() as db:
        db.add(AiSettings(id=AI_SETTINGS_ID, enabled=True, base_url="https://ai.example.com/v1", model="m"))
        await db.commit()
    assert (await client.get(url, headers=_auth(admin))).json() == {"ai": True, "instances": True}

    # And a conversation left behind counts once it's switched off again.
    async with SessionLocal() as db:
        (await db.get(AiSettings, AI_SETTINGS_ID)).enabled = False
        db.add(AiConversation(competition_id=comp, user_id=ada_id, assistant_type="competitor"))
        await db.commit()
    assert (await client.get(url, headers=_auth(admin))).json()["ai"] is True
    # Still nothing for the member.
    assert (await client.get(url, headers=_auth(ada))).json() == {"ai": False, "instances": False}

    # Instancing switched on site-wide makes it of use in a competition with
    # no instance data of its own.
    from models.challenge_instancing import INSTANCE_SETTINGS_ID, InstanceSettings

    other = await _competition(client)
    other_url = f"/api/competitions/{other}/modules/in-use"
    assert (await client.get(other_url, headers=_auth(admin))).json()["instances"] is False
    async with SessionLocal() as db:
        db.add(InstanceSettings(id=INSTANCE_SETTINGS_ID, enabled=True, backend="docker", endpoint_url="http://proxy:2375"))
        await db.commit()
    assert (await client.get(other_url, headers=_auth(admin))).json()["instances"] is True

    # A Judge of `comp` alone holds both page permissions there and nothing in
    # `other`: the answers are scoped to the competition asked about.
    judge, judge_id = await _register(client, "judge@example.com")
    judge_role = next(r for r in (await client.get("/api/roles", headers=_auth(admin))).json() if r["name"] == "Judge")
    assert (
        await client.post(
            "/api/roles/assignments",
            json={"user_id": judge_id, "role_id": judge_role["id"], "competition_id": comp},
            headers=_auth(admin),
        )
    ).status_code == 201
    assert (await client.get(url, headers=_auth(judge))).json() == {"ai": True, "instances": True}
    assert (await client.get(other_url, headers=_auth(judge))).status_code == 403

    # One permission answers for one module only.
    ops, ops_id = await _register(client, "ops@example.com")
    await _grant_custom_role(ops_id, comp, "Ops", ["challenge_view", "instance_view"])
    assert (await client.get(url, headers=_auth(ops))).json() == {"ai": False, "instances": True}

    # Instance records left behind count on their own — even destroyed ones —
    # once the spec that made them is gone (the FK is off under SQLite here;
    # the row's competition_id is what the read scopes on).
    from models.challenge_instancing import ChallengeInstance

    leftovers = await _competition(client)
    async with SessionLocal() as db:
        (await db.get(InstanceSettings, INSTANCE_SETTINGS_ID)).enabled = False
        spec = await db.scalar(select(ChallengeDeployment).limit(1))
        db.add(
            ChallengeInstance(
                competition_id=leftovers,
                challenge_id=spec.challenge_id,
                deployment_id=spec.id,
                user_id=ada_id,
                status="destroyed",
            )
        )
        await db.commit()
    assert (await client.get(f"/api/competitions/{leftovers}/modules/in-use", headers=_auth(admin))).json()["instances"] is True
