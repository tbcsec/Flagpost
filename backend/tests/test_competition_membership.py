"""Competition join + visibility (pre-Tier-2 gap fixes).

Joining a competition is how a competitor gains the Participant role — and, for
individual-mode competitions (no teams), the *only* way in. Visibility is
enforced on reads: a private competition is hidden from non-members.
"""

from sqlalchemy import select

from auth.deps import user_has_permission
from db import SessionLocal
from models.audit_log import AuditLogEntry
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email, name="User") -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": name},
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _make_competition(client, *, visibility="public", mode="individual") -> dict:
    admin = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={"name": "CTF", "participation_mode": mode, "visibility": visibility},
        headers=_auth(admin),
    )
    return resp.json()


async def test_public_self_serve_join_grants_participant_access(client):
    comp = await _make_competition(client, visibility="public", mode="individual")
    token, user_id = await _register(client, "solo@example.com")

    # Individual-mode: no team to join — the competition join is the only path in.
    resp = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == comp["id"]

    async with SessionLocal() as session:
        assert await user_has_permission(
            session, user_id, "challenge_view", comp["id"]
        )
    # ...and the join event landed.
    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "competition.member_joined"
                )
            )
        ).scalars().all()
    assert len(events) == 1


async def test_join_is_idempotent(client):
    comp = await _make_competition(client, visibility="public")
    token, _ = await _register(client, "twice@example.com")

    await client.post(f"/api/competitions/{comp['id']}/join", headers=_auth(token))
    await client.post(f"/api/competitions/{comp['id']}/join", headers=_auth(token))

    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "competition.member_joined"
                )
            )
        ).scalars().all()
    # Re-joining doesn't grant a second role or re-emit.
    assert len(events) == 1


async def test_private_competition_rejects_self_serve_join(client):
    comp = await _make_competition(client, visibility="private")
    token, _ = await _register(client, "sneaky@example.com")
    resp = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert resp.status_code == 403


async def test_join_private_by_invite_code(client):
    comp = await _make_competition(client, visibility="private", mode="individual")
    token, user_id = await _register(client, "invited@example.com")

    resp = await client.post(
        "/api/competitions/join",
        json={"invite_code": comp["invite_code"]},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    async with SessionLocal() as session:
        assert await user_has_permission(
            session, user_id, "challenge_view", comp["id"]
        )


async def test_join_by_bad_code_404s(client):
    await _make_competition(client, visibility="private")
    token, _ = await _register(client, "wrongcode@example.com")
    resp = await client.post(
        "/api/competitions/join",
        json={"invite_code": "not-a-real-code"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_private_competition_hidden_from_non_members(client):
    private = await _make_competition(client, visibility="private")
    public = await _make_competition(client, visibility="public")
    token, _ = await _register(client, "outsider@example.com")

    # Listing hides the private competition.
    listing = await client.get("/api/competitions", headers=_auth(token))
    ids = {c["id"] for c in listing.json()}
    assert public["id"] in ids
    assert private["id"] not in ids

    # And a direct read 404s (existence not disclosed).
    direct = await client.get(
        f"/api/competitions/{private['id']}", headers=_auth(token)
    )
    assert direct.status_code == 404


async def test_member_sees_private_competition_after_joining(client):
    private = await _make_competition(client, visibility="private")
    token, _ = await _register(client, "member@example.com")
    await client.post(
        "/api/competitions/join",
        json={"invite_code": private["invite_code"]},
        headers=_auth(token),
    )
    listing = await client.get("/api/competitions", headers=_auth(token))
    assert private["id"] in {c["id"] for c in listing.json()}


async def test_admin_sees_all_competitions(client):
    private = await _make_competition(client, visibility="private")
    admin = await admin_token(client)
    listing = await client.get("/api/competitions", headers=_auth(admin))
    assert private["id"] in {c["id"] for c in listing.json()}


async def _global_delegate(client, email, permissions) -> str:
    """A registered user holding a custom site-wide role with ``permissions``."""
    admin = await admin_token(client)
    role = await client.post(
        "/api/roles",
        json={"name": f"Delegate {email}", "scope": "global", "permissions": permissions},
        headers=_auth(admin),
    )
    assert role.status_code == 201, role.text
    token, _ = await _register(client, email, name=email.split("@")[0])
    assigned = await client.post(
        "/api/roles/assignments",
        json={"email": email, "role_id": role.json()["id"], "competition_id": None},
        headers=_auth(admin),
    )
    assert assigned.status_code == 201, assigned.text
    return token


async def test_global_delegate_without_competition_reach_is_an_outsider(client):
    # A site-wide role carrying only global-scope grants reaches the Admin
    # section, not competitions: its holder sees a private competition no more
    # than any other user does (GHSA-q472-m9qw-8gq4).
    private = await _make_competition(client, visibility="private", mode="team")
    public = await _make_competition(client, visibility="public")
    token = await _global_delegate(
        client, "auditor@example.com", ["view_audit_log", "manage_pages"]
    )
    cid = private["id"]

    listing = await client.get("/api/competitions", headers=_auth(token))
    ids = {c["id"] for c in listing.json()}
    assert public["id"] in ids
    assert cid not in ids

    for path in (
        f"/api/competitions/{cid}",
        f"/api/competitions/{cid}/rules",
        f"/api/competitions/{cid}/registration-fields",
        f"/api/competitions/{cid}/teams",
    ):
        resp = await client.get(path, headers=_auth(token))
        assert resp.status_code == 404, (path, resp.text)

    # Creating a team is an entry into the competition — refused like a read.
    team = await client.post(
        f"/api/competitions/{cid}/teams", json={"name": "Team"}, headers=_auth(token)
    )
    assert team.status_code == 404, team.text
    async with SessionLocal() as session:
        me = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]
        assert not await user_has_permission(session, me, "challenge_view", cid)

    # The ordinary way in still works for them, as for anyone with the code.
    joined = await client.post(
        "/api/competitions/join",
        json={"invite_code": private["invite_code"]},
        headers=_auth(token),
    )
    assert joined.status_code == 200, joined.text


async def test_global_role_with_competition_reach_sees_every_competition(client):
    # A competition-scope grant held site-wide applies in every competition, so
    # its holder sees every competition — the Administrator's case, narrowed.
    private = await _make_competition(client, visibility="private")
    token = await _global_delegate(client, "moderator@example.com", ["ticket_view"])

    listing = await client.get("/api/competitions", headers=_auth(token))
    assert private["id"] in {c["id"] for c in listing.json()}
    direct = await client.get(
        f"/api/competitions/{private['id']}", headers=_auth(token)
    )
    assert direct.status_code == 200, direct.text


async def test_clone_needs_the_source_to_be_visible(client):
    # create_competition is global-scope: it lets its holder make competitions,
    # not reach into a private one to copy it out.
    private = await _make_competition(client, visibility="private")
    public = await _make_competition(client, visibility="public")
    token = await _global_delegate(client, "creator@example.com", ["create_competition"])

    hidden = await client.post(
        f"/api/competitions/{private['id']}/clone",
        json={"name": "Copy"},
        headers=_auth(token),
    )
    assert hidden.status_code == 404, hidden.text

    visible = await client.post(
        f"/api/competitions/{public['id']}/clone",
        json={"name": "Copy of public"},
        headers=_auth(token),
    )
    assert visible.status_code == 201, visible.text


async def test_malformed_or_unknown_global_grants_confer_no_reach(client):
    # Only a well-formed site-wide role with a known competition-scope key
    # reaches every competition. A stale key, an empty role, or a competition
    # role written without a competition (malformed) grants nothing — and a
    # stale key doesn't break the read either.
    from auth.membership import sees_every_competition
    from models.role import Role, RoleAssignment

    private = await _make_competition(client, visibility="private")
    token, user_id = await _register(client, "odd@example.com")
    async with SessionLocal() as db:
        participant = await db.scalar(select(Role).where(Role.name == "Participant"))
        stale = Role(name="Stale", scope="global", permissions=["no_such_permission"])
        empty = Role(name="Empty", scope="global", permissions=[])
        db.add_all([stale, empty])
        await db.flush()
        for role in (stale, empty, participant):
            db.add(RoleAssignment(user_id=user_id, competition_id=None, role_id=role.id))
        await db.commit()
        assert not await sees_every_competition(db, user_id)

    listing = await client.get("/api/competitions", headers=_auth(token))
    assert listing.status_code == 200, listing.text
    assert private["id"] not in {c["id"] for c in listing.json()}


async def test_role_assignment_needs_the_competition_to_be_visible(client):
    # Any assignment makes its holder a member, so a role delegate can't place
    # one — even an empty role — into a competition they can't see.
    private = await _make_competition(client, visibility="private")
    public = await _make_competition(client, visibility="public")
    token = await _global_delegate(client, "roles@example.com", ["manage_roles"])
    role = await client.post(
        "/api/roles",
        json={"name": "Observer", "scope": "competition", "permissions": []},
        headers=_auth(token),
    )
    assert role.status_code == 201, role.text

    def assign(competition_id):
        return client.post(
            "/api/roles/assignments",
            json={
                "email": "roles@example.com",
                "role_id": role.json()["id"],
                "competition_id": competition_id,
            },
            headers=_auth(token),
        )

    hidden = await assign(private["id"])
    assert hidden.status_code == 404, hidden.text
    direct = await client.get(f"/api/competitions/{private['id']}", headers=_auth(token))
    assert direct.status_code == 404

    visible = await assign(public["id"])
    assert visible.status_code == 201, visible.text


async def test_administrator_still_assigns_into_private_competitions(client):
    private = await _make_competition(client, visibility="private")
    admin = await admin_token(client)
    _, _ = await _register(client, "judge@example.com")
    roles = {r["name"]: r for r in (await client.get("/api/roles", headers=_auth(admin))).json()}
    resp = await client.post(
        "/api/roles/assignments",
        json={
            "email": "judge@example.com",
            "role_id": roles["Judge"]["id"],
            "competition_id": private["id"],
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text


async def test_role_delegate_neither_lists_nor_removes_unseen_assignments(client):
    # A private competition's roster is its members' business: a role delegate
    # without reach neither lists its assignments nor removes them.
    private = await _make_competition(client, visibility="private")
    admin = await admin_token(client)
    await _register(client, "staff@example.com", name="staff")
    roles = {r["name"]: r for r in (await client.get("/api/roles", headers=_auth(admin))).json()}
    judge = await client.post(
        "/api/roles/assignments",
        json={
            "email": "staff@example.com",
            "role_id": roles["Judge"]["id"],
            "competition_id": private["id"],
        },
        headers=_auth(admin),
    )
    assert judge.status_code == 201, judge.text
    token = await _global_delegate(client, "roster@example.com", ["manage_roles"])

    listing = await client.get("/api/roles/assignments", headers=_auth(token))
    assert listing.status_code == 200, listing.text
    assert private["id"] not in {a["competition_id"] for a in listing.json()}
    # Site-wide assignments stay listed (their own, at least).
    assert any(a["competition_id"] is None for a in listing.json())

    removed = await client.delete(
        f"/api/roles/assignments/{judge.json()['id']}", headers=_auth(token)
    )
    assert removed.status_code == 404, removed.text

    # The administrator still sees and manages it.
    full = await client.get("/api/roles/assignments", headers=_auth(admin))
    assert judge.json()["id"] in {a["id"] for a in full.json()}


async def test_team_join_checks_the_code_before_revealing_the_rules(client):
    # A private competition's rules go to someone holding its team code, not to
    # anyone who knows its id.
    admin = await admin_token(client)
    private = (
        await client.post(
            "/api/competitions",
            json={
                "name": "Invitational",
                "participation_mode": "team",
                "visibility": "private",
                "rules_override": {
                    "type": "doc",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "House rules"}]}
                    ],
                },
            },
            headers=_auth(admin),
        )
    ).json()
    captain, _ = await _register(client, "captain@example.com", name="captain")
    joined = await client.post(
        "/api/competitions/join",
        json={"invite_code": private["invite_code"], "accept_rules": True},
        headers=_auth(captain),
    )
    assert joined.status_code == 200, joined.text
    team = await client.post(
        f"/api/competitions/{private['id']}/teams", json={"name": "Crew"}, headers=_auth(captain)
    )
    assert team.status_code == 201, team.text

    outsider = await _global_delegate(client, "watcher@example.com", ["view_audit_log"])
    guess = await client.post(
        f"/api/competitions/{private['id']}/teams/join",
        json={"invite_code": "not-the-code"},
        headers=_auth(outsider),
    )
    assert guess.status_code == 404, guess.text
    assert "House rules" not in guess.text

    # With the real code, the ordinary flow resumes: accept the rules first.
    real = await client.post(
        f"/api/competitions/{private['id']}/teams/join",
        json={"invite_code": team.json()["invite_code"]},
        headers=_auth(outsider),
    )
    assert real.status_code == 403, real.text
    assert real.json()["detail"]["code"] == "rules_not_accepted"
