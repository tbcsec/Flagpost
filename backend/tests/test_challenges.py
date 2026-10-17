"""Challenge + category endpoints: flag secrecy, draft visibility, RBAC, events."""

import json

import pytest
from sqlalchemy import select

from db import SessionLocal
from models.attachment import Attachment
from models.audit_log import AuditLogEntry
from models.challenge import Challenge
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
                # Top-level in the ctfcli spec — a real challenge.yml carries it
                # here, not under `extra` (#262).
                "connection_info": "nc chal.example.com 1337",
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
    assert listing["Welcome"]["connection_info"] == "nc chal.example.com 1337"
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
    # connection_info completes the round-trip, back out as a TOP-LEVEL key so
    # the file stays readable by real ctfcli (#262).
    welcome = yaml.safe_load(out.read([n for n in ymls if n.startswith("welcome")][0]))
    assert welcome["connection_info"] == "nc chal.example.com 1337"
    assert "connection_info" not in welcome.get("extra", {})


async def test_challenge_yaml_deployment_block_roundtrips(client):
    """#320: an instancing deployment spec rides ctfcli import/export under
    extra.deployment, validated at the boundary like the authoring route."""
    import io
    import zipfile

    import yaml
    from sqlalchemy import select

    from db import SessionLocal
    from models.challenge_instancing import ChallengeDeployment

    admin = await admin_token(client)
    comp = await _make_competition(client)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("web/challenge.yml", yaml.safe_dump({
            "name": "Web Chal", "category": "web", "description": "pwn it", "value": 100,
            "extra": {"deployment": {
                "backend": "docker", "image": "ghcr.io/x/web:1", "exposure": "http",
                "ports": [8080], "env": {"MODE": "hard"}, "flag_mode": "unique_per_instance",
                "flag_template": "flag{web-<random>}", "per_subject_cap": 2, "lifetime_s": 1800,
            }},
        }))
        # An invalid deployment (tcp with no ports) is reported per-challenge, not fatal.
        zf.writestr("bad/challenge.yml", yaml.safe_dump({
            "name": "Bad Deploy", "category": "web", "description": "oops", "value": 50,
            "flags": ["flag{x}"],
            "extra": {"deployment": {"backend": "docker", "image": "img:1", "exposure": "tcp", "ports": []}},
        }))
        # A malformed env (a YAML list, not a mapping) must be a per-challenge
        # error string, NOT an uncaught AttributeError that 500s the whole import.
        zf.writestr("badenv/challenge.yml", yaml.safe_dump({
            "name": "Bad Env", "category": "web", "description": "oops2", "value": 50,
            "flags": ["flag{y}"],
            "extra": {"deployment": {"backend": "docker", "image": "img:1",
                                     "exposure": "none", "env": ["MODE=hard"]}},
        }))

    imp = await client.post(
        f"/api/competitions/{comp}/challenges/import",
        files={"file": ("c.zip", buf.getvalue(), "application/zip")}, headers=_auth(admin),
    )
    assert imp.status_code == 200, imp.text
    body = imp.json()
    assert body["created"] == 3  # all challenges import; only the bad DEPLOYMENTS are rejected
    assert any("Bad Deploy: deployment" in e for e in body["errors"])
    # The non-dict env is reported per-challenge, not a 500.
    assert any("Bad Env: deployment" in e and "env must be a mapping" in e for e in body["errors"])

    listing = {c["title"]: c for c in (await client.get(f"/api/competitions/{comp}/challenges", headers=_auth(admin))).json()}
    async with SessionLocal() as db:
        deps = {
            d.challenge_id: d for d in (await db.scalars(
                select(ChallengeDeployment).where(ChallengeDeployment.competition_id == comp)
            )).all()
        }
    web = deps[listing["Web Chal"]["id"]]
    assert web.exposure == "http" and web.ports == [8080] and web.flag_mode == "unique_per_instance"
    assert web.flag_template == "flag{web-<random>}" and web.per_subject_cap == 2 and web.lifetime_s == 1800
    assert web.env == {"MODE": "hard"}
    # The rejected deployments left no rows.
    assert listing["Bad Deploy"]["id"] not in deps
    assert listing["Bad Env"]["id"] not in deps

    # Export carries the deployment back out under extra.deployment.
    exp = await client.get(f"/api/competitions/{comp}/challenges/export", headers=_auth(admin))
    out = zipfile.ZipFile(io.BytesIO(exp.content))
    name = next(n for n in out.namelist() if n.startswith("web-chal") and n.endswith("challenge.yml"))
    d = yaml.safe_load(out.read(name))["extra"]["deployment"]
    assert d["backend"] == "docker" and d["exposure"] == "http" and d["ports"] == [8080]
    assert d["flag_mode"] == "unique_per_instance" and d["flag_template"] == "flag{web-<random>}"
    assert d["per_subject_cap"] == 2 and d["lifetime_s"] == 1800 and d["env"] == {"MODE": "hard"}
    assert "image" in d


async def test_challenge_yaml_rejects_resource_limits_that_truncate_to_unlimited(client):
    """GHSA-vgrr residual: a ctfcli zip (or a content pack, which imports
    through it) can't smuggle in resource limits the provisioners would
    int()-truncate to 0 — Docker's "unlimited" — nor a YAML ``.nan``. Each is a
    per-challenge deployment error, and no deployment row is written."""
    import io
    import zipfile

    import yaml
    from sqlalchemy import select

    from db import SessionLocal
    from models.challenge_instancing import ChallengeDeployment

    admin = await admin_token(client)
    comp = await _make_competition(client)

    bad = {
        "Tiny CPU": {"cpu": 1e-10},
        "Half Memory": {"memory_mb": 0.5},
        "Half Pids": {"pids": 0.5},
        "Below Floor": {"memory_mb": 8},
        "All Truncating": {"cpu": 1e-10, "memory_mb": 0.5, "pids": 0.5},
        "NaN CPU": {"cpu": float("nan")},  # safe_dump writes it as .nan
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, (title, limits) in enumerate(bad.items()):
            zf.writestr(f"c{i}/challenge.yml", yaml.safe_dump({
                "name": title, "category": "pwn", "description": "x", "value": 50,
                "flags": [f"flag{{{i}}}"],
                "extra": {"deployment": {
                    "backend": "docker", "image": "img:1", "exposure": "tcp",
                    "ports": [1337], "resource_limits": limits,
                }},
            }))
        zf.writestr("ok/challenge.yml", yaml.safe_dump({
            "name": "Sane Limits", "category": "pwn", "description": "x", "value": 50,
            "flags": ["flag{ok}"],
            "extra": {"deployment": {
                "backend": "docker", "image": "img:1", "exposure": "tcp", "ports": [1337],
                "resource_limits": {"cpu": 0.5, "memory_mb": 64, "pids": 32},
            }},
        }))
        # YAML writes these as 512.0 / 64.0: whole numbers, so accepted as ints.
        zf.writestr("whole/challenge.yml", yaml.safe_dump({
            "name": "Whole Floats", "category": "pwn", "description": "x", "value": 50,
            "flags": ["flag{whole}"],
            "extra": {"deployment": {
                "backend": "docker", "image": "img:1", "exposure": "tcp", "ports": [1337],
                "resource_limits": {"memory_mb": 512.0, "pids": 64.0},
            }},
        }))

    imp = await client.post(
        f"/api/competitions/{comp}/challenges/import",
        files={"file": ("c.zip", buf.getvalue(), "application/zip")}, headers=_auth(admin),
    )
    assert imp.status_code == 200, imp.text
    errors = imp.json()["errors"]
    for title in bad:
        assert any(
            e.startswith(f"{title}: deployment") and "resource_limits." in e for e in errors
        ), (title, errors)

    listing = {c["title"]: c["id"] for c in (await client.get(f"/api/competitions/{comp}/challenges", headers=_auth(admin))).json()}
    async with SessionLocal() as db:
        deps = {
            d.challenge_id: d for d in (await db.scalars(
                select(ChallengeDeployment).where(ChallengeDeployment.competition_id == comp)
            )).all()
        }
    assert set(deps) == {listing["Sane Limits"], listing["Whole Floats"]}
    assert deps[listing["Sane Limits"]].resource_limits == {"cpu": 0.5, "memory_mb": 64, "pids": 32}
    whole = deps[listing["Whole Floats"]].resource_limits
    assert whole == {"memory_mb": 512, "pids": 64}
    assert all(type(v) is int for v in whole.values())


async def test_connection_info_authored_and_withheld_while_locked(client):
    """#262: connection info reaches a competitor who can play the challenge, and
    is withheld while it's locked — it's an infrastructure address for content
    they haven't unlocked, unlike the description (which stays visible)."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            # Individual mode so a lone user is a subject; in team mode a
            # teamless user has no subject and is never gated.
            json={"name": "Conn", "participation_mode": "individual"},
            headers=_auth(admin),
        )
    ).json()["id"]

    base = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Base", "points": 100, "flag": "flag{base}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{base}/publish", headers=_auth(admin)
    )

    created = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={
            "title": "Gated",
            "points": 200,
            "flag": "flag{gate}",
            "prerequisites": [base],
            "connection_info": "nc box.example.com 1337",
        },
        headers=_auth(admin),
    )
    assert created.status_code == 201, created.text
    # Authoring round-trips on the create response (staff view).
    assert created.json()["connection_info"] == "nc box.example.com 1337"
    gated = created.json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{gated}/publish", headers=_auth(admin)
    )

    player, pid = await _register(client, "conn@example.com")
    await _assign_participant(pid, comp)

    # Locked: withheld on BOTH competitor read paths, while the description that
    # sits next to it stays readable.
    listing = {
        c["title"]: c
        for c in (
            await client.get(
                f"/api/competitions/{comp}/challenges", headers=_auth(player)
            )
        ).json()
    }
    assert listing["Gated"]["locked"] is True
    assert listing["Gated"]["connection_info"] is None
    detail = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{gated}", headers=_auth(player)
        )
    ).json()
    assert detail["locked"] is True and detail["connection_info"] is None

    # Staff are never redacted, locked or not.
    staff_detail = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{gated}", headers=_auth(admin)
        )
    ).json()
    assert staff_detail["connection_info"] == "nc box.example.com 1337"

    # Solving the prerequisite unlocks it → the address appears.
    await client.post(
        f"/api/competitions/{comp}/challenges/{base}/submit",
        json={"flag": "flag{base}"},
        headers=_auth(player),
    )
    unlocked = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{gated}", headers=_auth(player)
        )
    ).json()
    assert unlocked["locked"] is False
    assert unlocked["connection_info"] == "nc box.example.com 1337"

    # The redaction must never have been written back to the row (it's a real
    # column, so a plain assignment + autoflush would have UPDATEd it to NULL).
    async with SessionLocal() as session:
        stored = await session.get(Challenge, gated)
    assert stored.connection_info == "nc box.example.com 1337"


async def test_connection_info_is_editable_and_clearable(client):
    admin = await admin_token(client)
    comp = await _make_competition(client)
    cid = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Box", "points": 100, "connection_info": "https://a.example"},
            headers=_auth(admin),
        )
    ).json()["id"]

    # Infrastructure moves mid-event: PATCH it (the generic setattr path).
    patched = await client.patch(
        f"/api/competitions/{comp}/challenges/{cid}",
        json={"connection_info": "https://b.example"},
        headers=_auth(admin),
    )
    assert patched.status_code == 200
    assert patched.json()["connection_info"] == "https://b.example"

    # Explicit null clears it.
    cleared = await client.patch(
        f"/api/competitions/{comp}/challenges/{cid}",
        json={"connection_info": None},
        headers=_auth(admin),
    )
    assert cleared.json()["connection_info"] is None


async def test_connection_info_withheld_from_a_teamless_viewer_in_team_mode(client):
    """#262 bypass guard: in TEAM mode a competitor who never joins a team has no
    subject, so `locked` is False for them on every gated challenge. Keying the
    redaction off `locked` would have let anyone read gated addresses just by not
    joining a team — it's re-derived from solve history instead, and no solves at
    all means nothing is unlocked."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "TeamMode", "participation_mode": "team"},
            headers=_auth(admin),
        )
    ).json()["id"]
    base = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Base", "points": 100, "flag": "flag{base}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{base}/publish", headers=_auth(admin)
    )
    gated = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={
                "title": "Gated",
                "points": 200,
                "flag": "flag{gate}",
                "prerequisites": [base],
                "connection_info": "nc secret.example.com 1337",
            },
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{gated}/publish", headers=_auth(admin)
    )
    # An open one with no prerequisites stays visible to everyone — the redaction
    # must not over-reach into ungated content.
    open_id = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={
                "title": "Open",
                "points": 50,
                "flag": "flag{open}",
                "connection_info": "https://open.example.com",
            },
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{open_id}/publish", headers=_auth(admin)
    )

    player, pid = await _register(client, "teamless@example.com")
    await _assign_participant(pid, comp)  # joins the competition, but no team

    listing = {
        c["title"]: c
        for c in (
            await client.get(
                f"/api/competitions/{comp}/challenges", headers=_auth(player)
            )
        ).json()
    }
    # `locked` is False (no subject to gate) — yet the address is still withheld.
    assert listing["Gated"]["locked"] is False
    assert listing["Gated"]["connection_info"] is None
    assert listing["Open"]["connection_info"] == "https://open.example.com"

    detail = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{gated}", headers=_auth(player)
        )
    ).json()
    assert detail["connection_info"] is None


async def test_ctfcli_import_bounds_decompressed_member_size():
    """GHSA-wvjv: a zip member is read through a bounded reader that never pulls
    more than the cap, so a zip bomb (tiny compressed, enormous decompressed)
    can't force a huge allocation."""
    import io
    import zipfile

    from utils.challenge_yaml import _MemberTooLarge, _read_member

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.bin", b"\x00" * (2 * 1024 * 1024))  # 2 MiB, ~nothing compressed
    zf = zipfile.ZipFile(io.BytesIO(buf.getvalue()))

    with pytest.raises(_MemberTooLarge):
        _read_member(zf, "big.bin", 1024)  # cap below the member → refused (no giant alloc)
    # A cap above the real size returns the whole member.
    assert len(_read_member(zf, "big.bin", 4 * 1024 * 1024)) == 2 * 1024 * 1024


async def test_ctfcli_import_sanitises_traversal_attachment_filename(client):
    """GHSA-wvjv: a bundled filename is sanitised on import, so a traversal name
    (..\\..\\evil.bat) can't ride verbatim into the challenge-export zip as a path."""
    import io
    import zipfile

    import yaml

    admin = await admin_token(client)
    comp = await _make_competition(client)
    evil = "..\\..\\evil.bat"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "welcome/challenge.yml",
            yaml.safe_dump({
                "name": "Welcome", "category": "misc", "description": "hi",
                "value": 50, "flags": ["flag{hi}"], "files": [evil],
            }),
        )
        zf.writestr(f"welcome/{evil}", b"payload")

    imp = await client.post(
        f"/api/competitions/{comp}/challenges/import",
        files={"file": ("challenges.zip", buf.getvalue(), "application/zip")},
        headers=_auth(admin),
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["created"] == 1

    async with SessionLocal() as session:
        att = (
            await session.scalars(
                select(Attachment).where(Attachment.competition_id == comp)
            )
        ).first()
    assert att is not None
    # No path separator survives, so the export can't emit a traversal entry.
    assert "\\" not in att.filename and "/" not in att.filename


# --- ctfcli import/export containment, continued (GHSA-wvjv-56qv-9v42) -------


def _ctfcli_bundle(entries: list[tuple[str, bytes | str, int]]) -> bytes:
    """A ctfcli zip from (name, content, compression) entries, in order."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content, compression in entries:
            zf.writestr(name, content, compress_type=compression)
    return buf.getvalue()


def _ctfcli_manifest(name: str, **extra) -> str:
    import yaml

    return yaml.safe_dump(
        {"name": name, "category": "misc", "value": 10, "flags": ["flag{x}"], **extra}
    )


async def _ctfcli_import(client, comp: str, blob: bytes):
    admin = await admin_token(client)
    return await client.post(
        f"/api/competitions/{comp}/challenges/import",
        files={"file": ("challenges.zip", blob, "application/zip")},
        headers=_auth(admin),
    )


async def _attachment_names(comp: str) -> list[str]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(Attachment.filename).where(Attachment.competition_id == comp)
                )
            ).all()
        )


@pytest.mark.parametrize("compression", ["bzip2", "lzma"])
async def test_ctfcli_import_refuses_bzip2_and_lzma_members(client, compression):
    """A bzip2 or LZMA member inflates whole on the first read, past any cap, so
    neither a bundled file nor a manifest compressed that way is read at all."""
    import zipfile

    method = {"bzip2": zipfile.ZIP_BZIP2, "lzma": zipfile.ZIP_LZMA}[compression]
    deflate = zipfile.ZIP_DEFLATED
    comp = await _make_competition(client)
    blob = _ctfcli_bundle([
        ("a/challenge.yml", _ctfcli_manifest("A", files=["bomb.bin"]), deflate),
        ("a/bomb.bin", b"\0" * (4 << 20), method),
        ("b/challenge.yml", _ctfcli_manifest("B"), method),
    ])
    assert len(blob) < 8192  # 4 MiB, and then some, in a few KB

    resp = await _ctfcli_import(client, comp, blob)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 1  # A, without its file; B's manifest unread
    assert any("a/bomb.bin" in e and "isn't accepted" in e for e in body["errors"])
    assert any("b/challenge.yml" in e and "isn't accepted" in e for e in body["errors"])
    assert await _attachment_names(comp) == []


async def test_ctfcli_import_counts_over_cap_reads_toward_the_total(client, monkeypatch):
    """An over-cap member still inflated cap + 1 bytes to find that out: those
    count toward the aggregate, or many of them would inflate for free."""
    import zipfile

    from utils import challenge_yaml

    monkeypatch.setattr(challenge_yaml, "_MAX_MEMBER_BYTES", 1024)
    monkeypatch.setattr(challenge_yaml, "_MAX_TOTAL_DECOMPRESSED", 8 * 1024)
    deflate = zipfile.ZIP_DEFLATED
    entries = []
    for i in range(10):
        entries.append((f"c{i}/challenge.yml", _ctfcli_manifest(f"C{i}", files=["big.bin"]), deflate))
        entries.append((f"c{i}/big.bin", b"\0" * 4096, deflate))
    comp = await _make_competition(client)

    resp = await _ctfcli_import(client, comp, _ctfcli_bundle(entries))
    assert resp.status_code == 400, resp.text
    assert "total decompressed size" in resp.json()["detail"]


async def test_ctfcli_import_reads_each_named_file_once(client):
    import zipfile

    deflate = zipfile.ZIP_DEFLATED
    comp = await _make_competition(client)
    blob = _ctfcli_bundle([
        ("a/challenge.yml", _ctfcli_manifest("A", files=["f.txt"] * 5), deflate),
        ("a/f.txt", b"hello", deflate),
    ])
    resp = await _ctfcli_import(client, comp, blob)
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1
    assert await _attachment_names(comp) == ["f.txt"]


async def test_ctfcli_import_caps_the_member_count(client, monkeypatch):
    import zipfile

    from utils import challenge_yaml

    monkeypatch.setattr(challenge_yaml, "_MAX_MEMBERS", 5)
    deflate = zipfile.ZIP_DEFLATED
    comp = await _make_competition(client)
    blob = _ctfcli_bundle(
        [("a/challenge.yml", _ctfcli_manifest("A"), deflate)]
        + [(f"a/f{i}.txt", b"", deflate) for i in range(5)]
    )
    resp = await _ctfcli_import(client, comp, blob)
    assert resp.status_code == 400, resp.text
    assert "too many files" in resp.json()["detail"]
    async with SessionLocal() as session:
        assert await session.scalar(select(Challenge).where(Challenge.competition_id == comp)) is None


async def test_ctfcli_import_refuses_a_yaml_alias_bomb(client):
    """YAML aliases share nodes, so a short manifest can expand enormously the
    moment the importer str()s a value. Counted before anything expands it."""
    import zipfile

    tens = lambda ref: "[" + ", ".join([ref] * 10) + "]"  # noqa: E731
    manifest = "\n".join([
        "name: Bomb",
        "category: misc",
        f"l0: &l0 {tens('x')}",
        f"l1: &l1 {tens('*l0')}",
        f"l2: &l2 {tens('*l1')}",
        f"l3: &l3 {tens('*l2')}",
        "description: *l3",
    ])
    comp = await _make_competition(client)
    resp = await _ctfcli_import(
        client, comp, _ctfcli_bundle([("bomb/challenge.yml", manifest, zipfile.ZIP_DEFLATED)])
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 0
    assert any("aliases" in e for e in body["errors"])


async def test_ctfcli_export_cleans_stored_attachment_names(client, object_storage):
    """A stored name is only as safe as whatever wrote it — a row from before
    the importer cleaned names, or one restored from a backup — so the export
    makes each entry a unique leaf under its challenge's folder, and never lets
    one shadow the manifest."""
    import io
    import zipfile

    import yaml

    admin = await admin_token(client)
    comp = await _make_competition(client)
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Legacy", "points": 10},
            headers=_auth(admin),
        )
    ).json()["id"]
    stored = ["..\\..\\evil.bat", "../../etc/passwd", "a/..", "challenge.yml", "notes.txt", "notes.txt"]
    async with SessionLocal() as session:
        for i, name in enumerate(stored):
            key = f"{comp}/{chal}/{i}"
            object_storage.put(key, f"blob {i}".encode(), "application/octet-stream")
            session.add(Attachment(competition_id=comp, challenge_id=chal, filename=name,
                                   object_key=key, content_type="application/octet-stream",
                                   size_bytes=6))
        await session.commit()

    resp = await client.get(f"/api/competitions/{comp}/challenges/export", headers=_auth(admin))
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
        assert len(names) == len(set(names)) == len(stored) + 1
        for name in names:
            folder, _, leaf = name.partition("/")
            assert folder == "legacy" and leaf.strip(".") and "/" not in leaf and "\\" not in leaf
        manifest = yaml.safe_load(zf.read("legacy/challenge.yml"))
        assert manifest["name"] == "Legacy"
        assert sorted(f"legacy/{f}" for f in manifest["files"]) == sorted(
            n for n in names if n != "legacy/challenge.yml"
        )
        assert sorted(zf.read(f"legacy/{f}") for f in manifest["files"]) == sorted(
            f"blob {i}".encode() for i in range(len(stored))
        )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("..\\..\\evil.bat", ".._.._evil.bat"),
        ("../../etc/passwd", "passwd"),
        ("a/..", "file"),
        ("../..", "file"),
        ("...", "file"),
        (".", "file"),
        ("", "file"),
        (None, "file"),
        ("x\x00.txt", "x.txt"),
        (".hidden", ".hidden"),
        ("report.pdf", "report.pdf"),
    ],
)
def test_safe_filename_leaves_a_file_name_and_nothing_else(raw, expected):
    from utils.uploads import safe_filename

    assert safe_filename(raw) == expected
