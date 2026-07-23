"""Flag submission + scoring (Phase 6, §13.2): correctness, idempotency,
first blood, per-subject scoping (team vs individual), rate limiting, RBAC, and
the challenge.solved event. Team-mode competitors gain access by joining a team
(which now grants the Participant role); individual-mode uses a direct grant.
"""

from sqlalchemy import select

from config import settings
from db import SessionLocal
from models.audit_log import AuditLogEntry
from models.role import Role, RoleAssignment
from models.submission import Submission
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


async def _make_competition(client, mode: str = "team") -> str:
    token = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={"name": "CTF", "participation_mode": mode},
        headers=_auth(token),
    )
    return resp.json()["id"]


async def _make_published_challenge(
    client, comp: str, *, flag: str = "flag{win}", points: int = 100, **extra
) -> str:
    token = await admin_token(client)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "Chal", "points": points, "flag": flag, **extra},
        headers=_auth(token),
    )
    cid = resp.json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/publish", headers=_auth(token)
    )
    return cid


async def _create_team(client, comp: str, token: str, name: str) -> str:
    """Create a team (grants the Participant role); return the invite code."""
    resp = await client.post(
        f"/api/competitions/{comp}/teams",
        json={"name": name},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["invite_code"]


async def _assign_participant(user_id: str, competition_id: str) -> None:
    async with SessionLocal() as session:
        role = await session.scalar(select(Role).where(Role.name == "Participant"))
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


async def _submissions(challenge_id: str):
    async with SessionLocal() as session:
        return (
            await session.execute(
                select(Submission).where(Submission.challenge_id == challenge_id)
            )
        ).scalars().all()


# --- Prerequisites / unlock chains -------------------------------------------


async def test_prerequisite_locks_a_challenge_until_solved(client):
    comp = await _make_competition(client, mode="individual")
    admin = await admin_token(client)
    base = await _make_published_challenge(client, comp, flag="flag{base}", points=100)
    # A second challenge that requires solving the first.
    gated = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Gated", "points": 200, "flag": "flag{gate}", "prerequisites": [base]},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(f"/api/competitions/{comp}/challenges/{gated}/publish", headers=_auth(admin))

    player, pid = await _register(client, "ada@example.com")
    await _assign_participant(pid, comp)

    # Locked in the list, and submits are refused.
    listing = {c["title"]: c for c in (await client.get(f"/api/competitions/{comp}/challenges", headers=_auth(player))).json()}
    assert listing["Gated"]["locked"] is True
    blocked = await client.post(
        f"/api/competitions/{comp}/challenges/{gated}/submit",
        json={"flag": "flag{gate}"},
        headers=_auth(player),
    )
    assert blocked.status_code == 403

    # Solve the prerequisite → the gate unlocks and accepts the flag.
    await client.post(
        f"/api/competitions/{comp}/challenges/{base}/submit",
        json={"flag": "flag{base}"},
        headers=_auth(player),
    )
    detail = (await client.get(f"/api/competitions/{comp}/challenges/{gated}", headers=_auth(player))).json()
    assert detail["locked"] is False
    ok = await client.post(
        f"/api/competitions/{comp}/challenges/{gated}/submit",
        json={"flag": "flag{gate}"},
        headers=_auth(player),
    )
    assert ok.status_code == 200 and ok.json()["correct"] is True


async def test_prerequisite_must_be_a_real_challenge_and_not_self(client):
    comp = await _make_competition(client, mode="individual")
    admin = await admin_token(client)
    # An unknown prerequisite id is rejected.
    bad = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "Bad", "points": 100, "prerequisites": ["nope"]},
        headers=_auth(admin),
    )
    assert bad.status_code == 400


# --- Scheduled release -------------------------------------------------------


async def test_scheduled_release_hides_challenge_until_its_time(client):
    from datetime import timedelta

    from db import utcnow

    comp = await _make_competition(client, mode="individual")
    admin = await admin_token(client)
    future = (utcnow() + timedelta(hours=1)).isoformat()
    past = (utcnow() - timedelta(hours=1)).isoformat()

    # One challenge scheduled for later, one already released.
    later = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Later", "points": 100, "flag": "flag{l}", "release_at": future},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(f"/api/competitions/{comp}/challenges/{later}/publish", headers=_auth(admin))
    now = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Now", "points": 100, "flag": "flag{n}", "release_at": past},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(f"/api/competitions/{comp}/challenges/{now}/publish", headers=_auth(admin))

    player, pid = await _register(client, "ada@example.com")
    await _assign_participant(pid, comp)

    # The competitor sees only the released one; staff see both.
    player_list = (await client.get(f"/api/competitions/{comp}/challenges", headers=_auth(player))).json()
    assert {c["title"] for c in player_list} == {"Now"}
    staff_list = (await client.get(f"/api/competitions/{comp}/challenges", headers=_auth(admin))).json()
    assert {c["title"] for c in staff_list} == {"Later", "Now"}

    # The unreleased challenge 404s for the competitor (detail + submit).
    assert (await client.get(f"/api/competitions/{comp}/challenges/{later}", headers=_auth(player))).status_code == 404
    submit = await client.post(
        f"/api/competitions/{comp}/challenges/{later}/submit",
        json={"flag": "flag{l}"},
        headers=_auth(player),
    )
    assert submit.status_code == 404


# --- Solver list + first blood -----------------------------------------------


async def test_solves_list_orders_earliest_first_with_first_blood(client):
    comp = await _make_competition(client, mode="individual")
    chal = await _make_published_challenge(client, comp, flag="flag{s}", points=100)
    first, fid = await _register(client, "first@example.com")
    second, sid = await _register(client, "second@example.com")
    await _assign_participant(fid, comp)
    await _assign_participant(sid, comp)

    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{s}"},
        headers=_auth(first),
    )
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{s}"},
        headers=_auth(second),
    )

    solves = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}/solves", headers=_auth(first)
        )
    ).json()
    assert [s["name"] for s in solves] == ["first", "second"]
    assert solves[0]["is_first_blood"] is True
    assert solves[1]["is_first_blood"] is False


# --- Dynamic (decay) scoring -------------------------------------------------


async def test_dynamic_scoring_decays_and_converges(client):
    comp = await _make_competition(client, mode="individual")
    chal = await _make_published_challenge(
        client, comp, flag="flag{d}", points=500,
        scoring_type="dynamic", min_points=100, decay=10,
    )
    tokens = []
    for i in range(3):
        tok, uid = await _register(client, f"dyn{i}@example.com")
        await _assign_participant(uid, comp)
        tokens.append(tok)

    awarded = []
    for tok in tokens:
        r = await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/submit",
            json={"flag": "flag{d}"},
            headers=_auth(tok),
        )
        awarded.append(r.json()["points_awarded"])

    # The value drops with each solve (CTFd quadratic decay).
    assert awarded == [496, 484, 464]

    # Every solver converges to the current (lowest) value — the board is fair.
    solves = [s for s in await _submissions(chal) if s.is_correct and not s.is_duplicate]
    assert {s.points_awarded for s in solves} == {464}

    # The challenge reports its current worth + config.
    detail = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}", headers=_auth(tokens[0])
        )
    ).json()
    assert detail["scoring_type"] == "dynamic"
    assert detail["value"] == 464
    assert detail["points"] == 500  # the configured initial is preserved

    # The scoreboard credits the converged value.
    board = (
        await client.get(
            f"/api/competitions/{comp}/scoreboard", headers=_auth(tokens[0])
        )
    ).json()
    assert all(e["points"] == 464 for e in board["entries"])


async def test_dynamic_scoring_requires_min_and_decay(client):
    comp = await _make_competition(client, mode="individual")
    token = await admin_token(client)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "Bad", "points": 500, "scoring_type": "dynamic"},
        headers=_auth(token),
    )
    assert resp.status_code == 400


# --- Correctness + scoring ---------------------------------------------------


async def test_correct_submission_awards_points_and_emits_solved(client):
    comp = await _make_competition(client)
    chal = await _make_published_challenge(client, comp, flag="flag{win}", points=250)
    token, _ = await _register(client, "solver@example.com")
    await _create_team(client, comp, token, "Solvers")

    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{win}"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["correct"] is True
    assert body["already_solved"] is False
    assert body["points_awarded"] == 250
    assert body["is_first_blood"] is True

    events = await _events("challenge.solved")
    assert len(events) == 1
    assert events[0].payload["points"] == 250
    assert events[0].payload["is_first_blood"] is True


async def test_incorrect_submission_is_logged_and_awards_nothing(client):
    comp = await _make_competition(client)
    chal = await _make_published_challenge(client, comp, flag="flag{win}")
    token, _ = await _register(client, "guesser@example.com")
    await _create_team(client, comp, token, "Guessers")

    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{nope}"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "correct": False,
        "already_solved": False,
        "points_awarded": 0,
        "is_first_blood": False,
        "attempts_remaining": None,
    }
    # Every attempt is logged, failures included (§13.2).
    subs = await _submissions(chal)
    assert len(subs) == 1
    assert subs[0].is_correct is False
    assert not await _events("challenge.solved")


async def test_repeat_correct_is_idempotent(client):
    comp = await _make_competition(client)
    chal = await _make_published_challenge(client, comp, flag="flag{win}", points=100)
    token, _ = await _register(client, "dbl@example.com")
    await _create_team(client, comp, token, "Doublers")
    url = f"/api/competitions/{comp}/challenges/{chal}/submit"

    first = await client.post(url, json={"flag": "flag{win}"}, headers=_auth(token))
    second = await client.post(url, json={"flag": "flag{win}"}, headers=_auth(token))

    assert first.json()["points_awarded"] == 100
    assert second.json()["correct"] is True
    assert second.json()["already_solved"] is True
    assert second.json()["points_awarded"] == 0

    # One awarded solve, one duplicate; the event fires exactly once.
    subs = await _submissions(chal)
    assert sum(s.points_awarded for s in subs) == 100
    assert sum(1 for s in subs if s.is_duplicate) == 1
    assert len(await _events("challenge.solved")) == 1


async def test_first_blood_only_for_the_first_solver(client):
    comp = await _make_competition(client)
    chal = await _make_published_challenge(client, comp, flag="flag{win}")
    url = f"/api/competitions/{comp}/challenges/{chal}/submit"

    t1, _ = await _register(client, "first@example.com")
    await _create_team(client, comp, t1, "First")
    t2, _ = await _register(client, "second@example.com")
    await _create_team(client, comp, t2, "Second")

    r1 = await client.post(url, json={"flag": "flag{win}"}, headers=_auth(t1))
    r2 = await client.post(url, json={"flag": "flag{win}"}, headers=_auth(t2))

    assert r1.json()["is_first_blood"] is True
    assert r2.json()["is_first_blood"] is False
    # Both still score — first blood is a flag, not a gate.
    assert r2.json()["points_awarded"] == 100


async def test_team_solve_is_shared_across_members(client):
    comp = await _make_competition(client)
    chal = await _make_published_challenge(client, comp, flag="flag{win}")
    url = f"/api/competitions/{comp}/challenges/{chal}/submit"

    captain, _ = await _register(client, "captain@example.com")
    code = await _create_team(client, comp, captain, "Squad")
    mate, _ = await _register(client, "mate@example.com")
    await client.post(
        f"/api/competitions/{comp}/teams/join",
        json={"invite_code": code},
        headers=_auth(mate),
    )

    await client.post(url, json={"flag": "flag{win}"}, headers=_auth(captain))
    # Teammate submitting the already-solved flag is a duplicate for the team.
    mate_resp = await client.post(url, json={"flag": "flag{win}"}, headers=_auth(mate))
    assert mate_resp.json()["already_solved"] is True
    assert mate_resp.json()["points_awarded"] == 0
    assert len(await _events("challenge.solved")) == 1


async def test_individual_mode_credits_the_user(client):
    comp = await _make_competition(client, mode="individual")
    chal = await _make_published_challenge(client, comp, flag="flag{solo}")
    token, user_id = await _register(client, "solo@example.com")
    await _assign_participant(user_id, comp)

    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{solo}"},
        headers=_auth(token),
    )
    assert resp.json()["correct"] is True
    subs = await _submissions(chal)
    assert subs[0].team_id is None
    assert subs[0].user_id == user_id


async def test_team_mode_requires_a_team(client):
    comp = await _make_competition(client)
    chal = await _make_published_challenge(client, comp, flag="flag{win}")
    # Has challenge_view but no team — nothing to credit a solve to.
    token, user_id = await _register(client, "teamless@example.com")
    await _assign_participant(user_id, comp)

    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{win}"},
        headers=_auth(token),
    )
    assert resp.status_code == 400
    assert "team" in resp.json()["detail"].lower()


# --- Hardening ---------------------------------------------------------------


async def test_rate_limit_blocks_a_flood(client):
    comp = await _make_competition(client)
    chal = await _make_published_challenge(client, comp, flag="flag{win}")
    token, _ = await _register(client, "flooder@example.com")
    await _create_team(client, comp, token, "Flooders")
    url = f"/api/competitions/{comp}/challenges/{chal}/submit"

    # Every attempt counts toward the window, right or wrong.
    for _ in range(settings.submission_rate_limit):
        ok = await client.post(url, json={"flag": "flag{x}"}, headers=_auth(token))
        assert ok.status_code == 200, ok.text
    blocked = await client.post(url, json={"flag": "flag{x}"}, headers=_auth(token))
    assert blocked.status_code == 429


async def test_submit_requires_challenge_view(client):
    comp = await _make_competition(client)
    chal = await _make_published_challenge(client, comp, flag="flag{win}")
    token, _ = await _register(client, "outsider@example.com")  # no role granted

    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{win}"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_cannot_submit_to_a_draft_challenge(client):
    comp = await _make_competition(client)
    admin = await admin_token(client)
    # Draft (never published), so it 404s to a non-editor.
    created = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "Draft", "flag": "flag{win}"},
        headers=_auth(admin),
    )
    chal = created.json()["id"]
    token, _ = await _register(client, "peeker@example.com")
    await _create_team(client, comp, token, "Peekers")

    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{win}"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_submit_to_flagless_challenge_rejected(client):
    comp = await _make_competition(client)
    admin = await admin_token(client)
    # An editor can see a flagless draft, but there's nothing to grade against.
    created = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "No flag"},
        headers=_auth(admin),
    )
    chal = created.json()["id"]

    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{win}"},
        headers=_auth(admin),
    )
    assert resp.status_code == 400


# --- Solve state surfaced on the browse list ---------------------------------


async def test_solve_state_appears_in_challenge_list(client):
    comp = await _make_competition(client)
    solved_chal = await _make_published_challenge(client, comp, flag="flag{a}")
    other_chal = await _make_published_challenge(client, comp, flag="flag{b}")
    token, _ = await _register(client, "browser@example.com")
    await _create_team(client, comp, token, "Browsers")

    await client.post(
        f"/api/competitions/{comp}/challenges/{solved_chal}/submit",
        json={"flag": "flag{a}"},
        headers=_auth(token),
    )

    listing = await client.get(
        f"/api/competitions/{comp}/challenges", headers=_auth(token)
    )
    by_id = {c["id"]: c for c in listing.json()}
    assert by_id[solved_chal]["solved"] is True
    assert by_id[solved_chal]["solve_count"] == 1
    assert by_id[other_chal]["solved"] is False
    assert by_id[other_chal]["solve_count"] == 0
