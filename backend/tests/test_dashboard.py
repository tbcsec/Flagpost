"""Dashboard read endpoints (Phase 1, ROADMAP #16): aggregate stats, recent
solves, challenge health (staff-gated), personal standing, and scoping/RBAC."""

from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def _competition(client, mode="team") -> str:
    admin = await admin_token(client)
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": mode, "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _published_challenge(client, comp, flag="flag{a}", points=100) -> str:
    admin = await admin_token(client)
    cid = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": f"Chal {flag}", "points": points, "flag": flag},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/publish", headers=_auth(admin)
    )
    return cid


async def _team_player(client, comp, email, team) -> str:
    token = await _register(client, email)
    await client.post(
        f"/api/competitions/{comp}/teams", json={"name": team}, headers=_auth(token)
    )
    return token


async def _submit(client, comp, chal, token, flag):
    return await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": flag},
        headers=_auth(token),
    )


async def test_stats_reflect_activity(client):
    comp = await _competition(client)
    c1 = await _published_challenge(client, comp, "flag{a}", 100)
    await _published_challenge(client, comp, "flag{b}", 200)  # published, unsolved
    token = await _team_player(client, comp, "p1@example.com", "Alpha")

    await _submit(client, comp, c1, token, "flag{wrong}")  # attempt, no solve
    await _submit(client, comp, c1, token, "flag{a}")  # solve

    stats = (
        await client.get(f"/api/competitions/{comp}/dashboard/stats", headers=_auth(token))
    ).json()
    assert stats["total_submissions"] == 2
    assert stats["total_solves"] == 1
    assert stats["recent_solves_1h"] == 1
    assert stats["published_challenges"] == 2
    assert stats["active_participants"] == 1  # one team


async def test_stats_active_participants_individual_mode(client):
    from db import SessionLocal
    from sqlalchemy import select
    from models.role import Role, RoleAssignment

    comp = await _competition(client, mode="individual")
    token = await _register(client, "solo@example.com")
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()
    async with SessionLocal() as session:
        role = await session.scalar(select(Role).where(Role.name == "Participant"))
        session.add(RoleAssignment(user_id=me["id"], competition_id=comp, role_id=role.id))
        await session.commit()

    stats = (
        await client.get(f"/api/competitions/{comp}/dashboard/stats", headers=_auth(token))
    ).json()
    assert stats["active_participants"] == 1


async def test_recent_solves_lists_subject_names(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp, "flag{a}", 250)
    token = await _team_player(client, comp, "p1@example.com", "Null Terminators")
    await _submit(client, comp, chal, token, "flag{a}")

    feed = (
        await client.get(f"/api/competitions/{comp}/dashboard/recent-solves", headers=_auth(token))
    ).json()
    assert len(feed) == 1
    assert feed[0]["subject_name"] == "Null Terminators"
    assert feed[0]["challenge_title"] == "Chal flag{a}"
    assert feed[0]["points"] == 250


async def test_challenge_health_requires_analytics_permission(client):
    comp = await _competition(client)
    await _published_challenge(client, comp)
    # A plain participant has challenge_view but not view_competition_analytics.
    token = await _team_player(client, comp, "p1@example.com", "Alpha")
    resp = await client.get(
        f"/api/competitions/{comp}/dashboard/challenge-health", headers=_auth(token)
    )
    assert resp.status_code == 403


async def test_challenge_health_reports_solves_and_attempts(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp, "flag{a}", 100)
    admin = await admin_token(client)
    token = await _team_player(client, comp, "p1@example.com", "Alpha")
    await _submit(client, comp, chal, token, "flag{no}")
    await _submit(client, comp, chal, token, "flag{a}")

    health = (
        await client.get(
            f"/api/competitions/{comp}/dashboard/challenge-health", headers=_auth(admin)
        )
    ).json()
    row = next(h for h in health if h["challenge_id"] == chal)
    assert row["solves"] == 1
    assert row["attempts"] == 2


async def test_my_standing(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp, "flag{a}", 100)
    token = await _team_player(client, comp, "p1@example.com", "Alpha")
    await _submit(client, comp, chal, token, "flag{a}")

    me = (
        await client.get(f"/api/competitions/{comp}/dashboard/me", headers=_auth(token))
    ).json()
    assert me["rank"] == 1
    assert me["points"] == 100
    assert me["solved_count"] == 1


async def test_dashboard_requires_competition_access(client):
    comp = await _competition(client)
    outsider = await _register(client, "outsider@example.com")  # no role
    resp = await client.get(
        f"/api/competitions/{comp}/dashboard/stats", headers=_auth(outsider)
    )
    assert resp.status_code == 403


# --- New manager sections (#332) -------------------------------------------


async def test_unsolved_challenges_lists_zero_solve_published(client):
    comp = await _competition(client)
    solved = await _published_challenge(client, comp, "flag{s}", 100)
    unsolved = await _published_challenge(client, comp, "flag{u}", 200)
    admin = await admin_token(client)
    token = await _team_player(client, comp, "p1@example.com", "Alpha")
    await _submit(client, comp, unsolved, token, "flag{no}")  # attempt, still unsolved
    await _submit(client, comp, solved, token, "flag{s}")  # solved

    rows = (
        await client.get(
            f"/api/competitions/{comp}/dashboard/unsolved-challenges", headers=_auth(admin)
        )
    ).json()
    ids = [r["challenge_id"] for r in rows]
    assert unsolved in ids and solved not in ids
    row = next(r for r in rows if r["challenge_id"] == unsolved)
    assert row["attempts"] == 1 and row["points"] == 200


async def test_unsolved_challenges_requires_analytics(client):
    comp = await _competition(client)
    token = await _team_player(client, comp, "p1@example.com", "Alpha")
    resp = await client.get(
        f"/api/competitions/{comp}/dashboard/unsolved-challenges", headers=_auth(token)
    )
    assert resp.status_code == 403


async def test_difficulty_progress_buckets_total_and_solved(client):
    from db import SessionLocal
    from models.challenge import Challenge

    comp = await _competition(client)
    easy = await _published_challenge(client, comp, "flag{e}", 100)
    hard = await _published_challenge(client, comp, "flag{h}", 500)
    admin = await admin_token(client)
    async with SessionLocal() as db:
        (await db.get(Challenge, easy)).difficulty = "easy"
        (await db.get(Challenge, hard)).difficulty = "hard"
        await db.commit()
    token = await _team_player(client, comp, "p1@example.com", "Alpha")
    await _submit(client, comp, hard, token, "flag{h}")  # solve the hard one

    rows = (
        await client.get(
            f"/api/competitions/{comp}/dashboard/difficulty-progress", headers=_auth(admin)
        )
    ).json()
    by = {r["difficulty"]: r for r in rows}
    assert by["easy"]["total"] == 1 and by["easy"]["solved"] == 0
    assert by["hard"]["total"] == 1 and by["hard"]["solved"] == 1


async def test_team_activity_reports_submissions_and_last_active(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp, "flag{a}", 100)
    admin = await admin_token(client)
    a = await _team_player(client, comp, "a@example.com", "Alpha")
    b = await _team_player(client, comp, "b@example.com", "Beta")
    await _submit(client, comp, chal, a, "flag{no}")
    await _submit(client, comp, chal, b, "flag{no}")

    rows = (
        await client.get(
            f"/api/competitions/{comp}/dashboard/team-activity", headers=_auth(admin)
        )
    ).json()
    by = {r["name"]: r for r in rows}
    assert set(by) == {"Alpha", "Beta"}
    assert by["Alpha"]["submissions"] == 1 and by["Alpha"]["last_active"] is not None


async def test_brute_force_counts_wrong_and_excludes_clean(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp, "flag{a}", 100)
    admin = await admin_token(client)
    guesser = await _team_player(client, comp, "g@example.com", "Guessers")
    clean = await _team_player(client, comp, "c@example.com", "Cleans")
    for f in ("flag{1}", "flag{2}", "flag{3}"):
        await _submit(client, comp, chal, guesser, f)  # 3 wrong
    await _submit(client, comp, chal, clean, "flag{a}")  # 1 right, 0 wrong

    rows = (
        await client.get(
            f"/api/competitions/{comp}/dashboard/brute-force", headers=_auth(admin)
        )
    ).json()
    names = [r["name"] for r in rows]
    assert "Guessers" in names
    assert "Cleans" not in names  # HAVING wrong > 0 excludes the clean team
    g = next(r for r in rows if r["name"] == "Guessers")
    assert g["wrong"] == 3 and g["total"] == 3


async def test_moderation_feed_filters_to_allowlist_and_names_actor(client):
    from db import SessionLocal
    from models.audit_log import AuditLogEntry

    comp = await _competition(client)
    admin = await admin_token(client)
    me = (await client.get("/api/auth/me", headers=_auth(admin))).json()
    async with SessionLocal() as db:
        db.add(AuditLogEntry(event_name="score.adjusted", competition_id=comp, user_id=me["id"]))
        db.add(AuditLogEntry(event_name="challenge.created", competition_id=comp, user_id=me["id"]))
        await db.commit()

    rows = (
        await client.get(
            f"/api/competitions/{comp}/dashboard/moderation-feed", headers=_auth(admin)
        )
    ).json()
    events = [r["event_name"] for r in rows]
    assert "score.adjusted" in events
    assert "challenge.created" not in events  # not on the moderation allowlist
    adj = next(r for r in rows if r["event_name"] == "score.adjusted")
    assert adj["actor_name"] == me["display_name"]


async def test_instance_health_aggregates_status_and_failures(client):
    from db import SessionLocal
    from models.challenge_instancing import ChallengeDeployment, ChallengeInstance

    comp = await _competition(client)
    chal = await _published_challenge(client, comp, "flag{a}", 100)
    admin = await admin_token(client)
    me = (await client.get("/api/auth/me", headers=_auth(admin))).json()
    async with SessionLocal() as db:
        dep = ChallengeDeployment(challenge_id=chal, competition_id=comp, backend="docker")
        db.add(dep)
        await db.flush()
        db.add(ChallengeInstance(challenge_id=chal, deployment_id=dep.id, user_id=me["id"], competition_id=comp, status="running"))
        db.add(ChallengeInstance(challenge_id=chal, deployment_id=dep.id, user_id=me["id"], competition_id=comp, status="failed", failure_reason="oom"))
        await db.commit()

    health = (
        await client.get(
            f"/api/competitions/{comp}/dashboard/instance-health", headers=_auth(admin)
        )
    ).json()
    by = {s["status"]: s["count"] for s in health["active_by_status"]}
    assert by.get("running") == 1
    assert "failed" not in by  # failed is terminal, not an active status
    assert len(health["failures"]) == 1
    assert health["failures"][0]["reason"] == "oom"
    assert health["failures"][0]["challenge_title"] == "Chal flag{a}"


async def test_instance_health_requires_instance_view(client):
    comp = await _competition(client)
    token = await _team_player(client, comp, "p1@example.com", "Alpha")
    resp = await client.get(
        f"/api/competitions/{comp}/dashboard/instance-health", headers=_auth(token)
    )
    assert resp.status_code == 403


# --- Layout customization (Phase 6, §10.2–10.5) ----------------------------


async def test_layout_defaults_to_null_then_round_trips(client):
    comp = await _competition(client)
    admin = await admin_token(client)

    # No saved layout yet → null (frontend falls back to the code default).
    got = await client.get(
        f"/api/competitions/{comp}/dashboard/layout", headers=_auth(admin)
    )
    assert got.status_code == 200
    assert got.json() is None

    entries = [
        {"widget_id": "stats", "x": 0, "y": 0, "w": 12, "h": 2, "hidden": False},
        {"widget_id": "activity", "x": 0, "y": 2, "w": 6, "h": 5, "hidden": True},
    ]
    put = await client.put(
        f"/api/competitions/{comp}/dashboard/layout",
        json={"entries": entries},
        headers=_auth(admin),
    )
    assert put.status_code == 200
    assert put.json()["entries"] == entries

    # Read back — persisted verbatim.
    got = (
        await client.get(
            f"/api/competitions/{comp}/dashboard/layout", headers=_auth(admin)
        )
    ).json()
    assert got["dashboard_key"] == "manager"
    assert got["entries"] == entries


async def test_layout_put_is_upsert(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    first = [{"widget_id": "stats", "x": 0, "y": 0, "w": 12, "h": 2, "hidden": False}]
    second = [{"widget_id": "standing", "x": 0, "y": 0, "w": 12, "h": 2, "hidden": False}]
    await client.put(
        f"/api/competitions/{comp}/dashboard/layout",
        json={"entries": first},
        headers=_auth(admin),
    )
    await client.put(
        f"/api/competitions/{comp}/dashboard/layout",
        json={"entries": second},
        headers=_auth(admin),
    )
    got = (
        await client.get(
            f"/api/competitions/{comp}/dashboard/layout", headers=_auth(admin)
        )
    ).json()
    assert got["entries"] == second


async def test_layout_reset_deletes_saved(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    await client.put(
        f"/api/competitions/{comp}/dashboard/layout",
        json={"entries": [{"widget_id": "stats", "x": 0, "y": 0, "w": 12, "h": 2}]},
        headers=_auth(admin),
    )
    delete = await client.delete(
        f"/api/competitions/{comp}/dashboard/layout", headers=_auth(admin)
    )
    assert delete.status_code == 204
    got = await client.get(
        f"/api/competitions/{comp}/dashboard/layout", headers=_auth(admin)
    )
    assert got.json() is None
    # Idempotent — resetting again is a no-op, not a 404.
    again = await client.delete(
        f"/api/competitions/{comp}/dashboard/layout", headers=_auth(admin)
    )
    assert again.status_code == 204


async def test_layout_is_per_user(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    await client.put(
        f"/api/competitions/{comp}/dashboard/layout",
        json={"entries": [{"widget_id": "stats", "x": 0, "y": 0, "w": 12, "h": 2}]},
        headers=_auth(admin),
    )
    # A Judge (holds customize_dashboard) sees their own empty layout, not admin's.
    judge = await _register(client, "judge@example.com")
    me = (await client.get("/api/auth/me", headers=_auth(judge))).json()
    from db import SessionLocal
    from sqlalchemy import select
    from models.role import Role, RoleAssignment

    async with SessionLocal() as session:
        role = await session.scalar(select(Role).where(Role.name == "Judge"))
        session.add(
            RoleAssignment(user_id=me["id"], competition_id=comp, role_id=role.id)
        )
        await session.commit()

    got = await client.get(
        f"/api/competitions/{comp}/dashboard/layout", headers=_auth(judge)
    )
    assert got.json() is None


async def test_layout_requires_customize_permission(client):
    comp = await _competition(client)
    # A plain participant lacks customize_dashboard.
    token = await _team_player(client, comp, "p1@example.com", "Alpha")
    resp = await client.get(
        f"/api/competitions/{comp}/dashboard/layout", headers=_auth(token)
    )
    assert resp.status_code == 403


async def test_layout_rejects_unknown_key(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    resp = await client.get(
        f"/api/competitions/{comp}/dashboard/layout?dashboard_key=bogus",
        headers=_auth(admin),
    )
    assert resp.status_code == 400


async def test_layout_get_drops_pre_2d_shape_instead_of_500(client):
    """A layout saved before issue #21 (the {cols,rows} flow shape) must not
    500 on read: get_layout drops the unrecognized entries so the client falls
    back to the default (backward-compat reset)."""
    comp = await _competition(client)
    admin = await admin_token(client)
    me = (await client.get("/api/auth/me", headers=_auth(admin))).json()

    from db import SessionLocal
    from models.dashboard_layout import DashboardLayout

    async with SessionLocal() as db:
        db.add(
            DashboardLayout(
                user_id=me["id"],
                dashboard_key="manager",
                layout_json=[
                    {"widget_id": "stats", "cols": 4, "rows": 1, "hidden": False},
                    {"widget_id": "activity", "cols": 2, "rows": 2, "hidden": True},
                ],
            )
        )
        await db.commit()

    got = await client.get(
        f"/api/competitions/{comp}/dashboard/layout", headers=_auth(admin)
    )
    assert got.status_code == 200
    assert got.json() == {"dashboard_key": "manager", "entries": []}
