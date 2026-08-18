"""Post-event report aggregation (#134, ADR-0030, Stage 2).

Builds one controlled competition — engineered solve rates, tickets with
timestamped messages + a resolved audit event, and challenge ratings — then
asserts every report section, with particular attention to the new computes
(engagement funnel, difficulty calibration, ticket response/resolution times)
that don't already have coverage via the analytics endpoints.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from models.challenge import Challenge
from models.competition import Competition
from models.feedback import ChallengeRating
from models.team import Team, TeamMembership
from models.ticket import Ticket, TicketMessage
from utils.report_data import build_report_data
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> str:
    return (
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
        )
    ).json()["access_token"]


async def _me_id(client, token: str) -> str:
    return (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]


async def _competition(client) -> str:
    admin = await admin_token(client)
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _challenge(client, comp, title, points, flag) -> str:
    admin = await admin_token(client)
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": title, "points": points, "flag": flag},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
    )
    return chal


async def _participant(client, comp, email) -> str:
    token = await _register(client, email)
    assert (
        await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    ).status_code == 200
    return token


async def _submit(client, comp, chal, token, flag) -> bool:
    return (
        await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/submit",
            json={"flag": flag},
            headers=_auth(token),
        )
    ).json()["correct"]


async def _load(comp: str) -> Competition:
    async with SessionLocal() as db:
        return await db.get(Competition, comp)


async def _seed(client) -> dict:
    """A finished individual-mode competition with engineered numbers."""
    comp = await _competition(client)
    admin = await admin_token(client)
    admin_id = await _me_id(client, admin)

    easy = await _challenge(client, comp, "Easy", 100, "flag{easy}")
    normal = await _challenge(client, comp, "Normal", 200, "flag{normal}")
    unsolved = await _challenge(client, comp, "Unsolved", 300, "flag{unsolved}")

    ada = await _participant(client, comp, "ada@example.com")
    bob = await _participant(client, comp, "bob@example.com")
    cara = await _participant(client, comp, "cara@example.com")
    ada_id = await _me_id(client, ada)
    bob_id = await _me_id(client, bob)
    cara_id = await _me_id(client, cara)

    # Solves (order matters for first blood): ada first-bloods Easy and Normal.
    assert await _submit(client, comp, easy, ada, "flag{easy}") is True
    assert await _submit(client, comp, easy, cara, "wrong") is False
    assert await _submit(client, comp, normal, ada, "flag{normal}") is True
    assert await _submit(client, comp, normal, bob, "flag{normal}") is True
    assert await _submit(client, comp, unsolved, ada, "wrong") is False

    base = datetime.now(timezone.utc).replace(microsecond=0)
    async with SessionLocal() as db:
        competition = await db.get(Competition, comp)
        competition.difficulty_tiers = ["easy", "medium", "hard"]
        competition.challenge_ratings_enabled = True
        competition.start_at = base - timedelta(hours=3)
        # Comfortably after the just-made submissions (whose sub-second times can
        # sit past a floored `base`); _effective_end then windows to the last
        # submission, keeping all five inside the final-day window.
        competition.end_at = base + timedelta(hours=1)
        for cid, tier in ((easy, "easy"), (normal, "medium"), (unsolved, "hard")):
            chal = await db.get(Challenge, cid)
            chal.difficulty = tier

        # Ticket T1: challenge-linked, opener cara, first staff reply at +120s
        # (an internal note at +60s must NOT count), resolved at +600s.
        t1 = Ticket(
            competition_id=comp,
            subject="stuck on Easy",
            status="resolved",
            challenge_id=easy,
            opener_user_id=cara_id,
            created_at=base,
        )
        db.add(t1)
        await db.flush()
        db.add_all(
            [
                TicketMessage(
                    competition_id=comp, ticket_id=t1.id, author_user_id=cara_id,
                    body="help", is_internal=False, created_at=base,
                ),
                TicketMessage(
                    competition_id=comp, ticket_id=t1.id, author_user_id=admin_id,
                    body="note", is_internal=True, created_at=base + timedelta(seconds=60),
                ),
                TicketMessage(
                    competition_id=comp, ticket_id=t1.id, author_user_id=admin_id,
                    body="try X", is_internal=False, created_at=base + timedelta(seconds=120),
                ),
            ]
        )
        db.add(
            AuditLogEntry(
                event_name="ticket.resolved",
                payload={"competition_id": comp, "ticket_id": t1.id},
                competition_id=comp,
                created_at=base + timedelta(seconds=600),
            )
        )
        # Ticket T2: general (no challenge), opener bob, never answered/resolved.
        db.add(
            Ticket(
                competition_id=comp, subject="account", status="open",
                challenge_id=None, opener_user_id=bob_id, created_at=base,
            )
        )
        # Ratings on Normal: 5 + 4 → avg 4.5.
        db.add_all(
            [
                ChallengeRating(competition_id=comp, challenge_id=normal, user_id=ada_id, rating=5),
                ChallengeRating(competition_id=comp, challenge_id=normal, user_id=bob_id, rating=4),
            ]
        )
        await db.commit()

    return {"comp": comp, "easy": easy, "normal": normal, "unsolved": unsolved}


async def test_report_data_full(client):
    ids = await _seed(client)
    competition = await _load(ids["comp"])
    async with SessionLocal() as db:
        data = await build_report_data(db, competition, sections=list(("overview", "participation", "results", "challenges", "support", "feedback")))

    # --- overview ---
    ov = data["overview"]
    assert ov["participants"] == 3
    assert ov["published_challenges"] == 3
    assert ov["total_solves"] == 3  # Easy 1 + Normal 2 + Unsolved 0
    assert ov["avg_rating"] == 4.5
    assert ov["highlights"]["most_solved"]["title"] == "Normal"
    assert ov["highlights"]["hardest"]["title"] == "Unsolved"
    assert ov["highlights"]["first_blood_leader"] == {"name": "ada", "count": 2}

    # --- participation: the funnel + invariants ---
    part = data["participation"]
    assert part["funnel"] == {
        "registered": 3, "active": 3, "scored": 2, "active_final_day": 3,
    }
    assert sum(part["activity_by_hour"]) == 5  # five total submissions
    assert part["solve_velocity"][-1]["cumulative"] == 3  # all solves accounted for

    # --- results: ranking + distribution ---
    res = data["results"]
    assert [e["name"] for e in res["podium"]] == ["ada", "bob", "cara"]
    assert res["podium"][0]["points"] == 300
    assert sum(b["count"] for b in res["score_distribution"]) == 3
    assert len(res["score_distribution"]) == 10

    # --- challenges: calibration + never-solved + rollup ---
    ch = data["challenges"]
    assert {c["title"] for c in ch["table"]} == {"Easy", "Normal", "Unsolved"}
    calib = ch["difficulty_calibration"]
    assert len(calib) == 1
    assert calib[0]["title"] == "Easy"
    assert calib[0]["direction"] == "harder_than_labelled"
    assert [n["title"] for n in ch["never_solved"]] == ["Unsolved"]
    assert ch["never_solved"][0]["attempt_count"] == 1
    rollup = {r["category"]: r for r in ch["category_rollup"]}
    assert rollup["Uncategorised"]["points"] == 600 and rollup["Uncategorised"]["solves"] == 3

    # --- support: response + resolution times from messages/audit ---
    sup = data["support"]
    assert sup["total_opened"] == 2
    assert sup["resolved_count"] == 1
    assert sup["avg_first_response_seconds"] == 120  # internal note at +60 skipped
    assert sup["avg_resolution_seconds"] == 600
    by_chal = {r["title"]: r["count"] for r in sup["tickets_by_challenge"]}
    assert by_chal == {"Easy": 1, "General / account": 1}

    # --- feedback: challenge ratings ---
    fb = data["feedback"]
    assert fb["challenge_ratings"] == [
        {"title": "Normal", "avg_rating": 4.5, "rating_count": 2}
    ]


async def test_build_report_data_selects_sections(client):
    """Only requested (and known) sections are built; unknown ids are ignored."""
    comp = await _competition(client)
    competition = await _load(comp)
    async with SessionLocal() as db:
        data = await build_report_data(
            db, competition, sections=["overview", "bogus"]
        )
    assert set(data) == {"meta", "overview"}
    assert data["meta"]["sections"] == ["overview"]
    assert "participation" not in data


async def test_out_of_window_events_are_counted(client):
    """Registrations/solves that predate a (later-set) start_at must still be
    counted — regression for _day_series clipping to [start, end] and dropping
    everything before the scheduled start, which under-reported the curves."""
    comp = await _competition(client)
    easy = await _challenge(client, comp, "Easy", 100, "flag{easy}")
    ada = await _participant(client, comp, "ada@example.com")
    bob = await _participant(client, comp, "bob@example.com")
    assert await _submit(client, comp, easy, ada, "flag{easy}") is True
    assert await _submit(client, comp, easy, bob, "flag{easy}") is True
    # Schedule the event into the future, so every join/solve above predates it.
    async with SessionLocal() as db:
        competition = await db.get(Competition, comp)
        future = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)
        competition.start_at = future
        competition.end_at = future + timedelta(days=1)
        await db.commit()

    competition = await _load(comp)
    async with SessionLocal() as db:
        data = await build_report_data(db, competition, sections=["overview", "participation"])
    part = data["participation"]
    assert part["registration_curve"][-1]["cumulative"] == 2  # both registrations kept
    assert part["solve_velocity"][-1]["cumulative"] == data["overview"]["total_solves"] == 2


async def test_funnel_excludes_non_participant_submitter(client):
    """A staff member who submits a flag without joining must not push the funnel
    above `registered` — it stays monotonic (regression: active/scored counted
    every distinct submitter, not just registered subjects)."""
    comp = await _competition(client)
    admin = await admin_token(client)
    easy = await _challenge(client, comp, "Easy", 100, "flag{easy}")
    ada = await _participant(client, comp, "ada@example.com")
    assert await _submit(client, comp, easy, ada, "flag{easy}") is True
    await _submit(client, comp, easy, admin, "flag{easy}")  # staff test, not a participant

    competition = await _load(comp)
    async with SessionLocal() as db:
        data = await build_report_data(db, competition, sections=["participation"])
    f = data["participation"]["funnel"]
    assert f["registered"] == 1
    assert f["active"] == 1  # admin's submission excluded
    assert f["scored"] == 1
    assert f["registered"] >= f["active"] >= f["scored"]


async def test_resolution_excludes_reopened_ticket(client):
    """A ticket resolved then reopened (status back to open) must be excluded from
    both resolved_count and avg_resolution_seconds, so the two agree."""
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    ada_id = await _me_id(client, ada)
    base = datetime.now(timezone.utc).replace(microsecond=0)
    async with SessionLocal() as db:
        ticket = Ticket(
            competition_id=comp, subject="x", status="open",
            challenge_id=None, opener_user_id=ada_id, created_at=base,
        )
        db.add(ticket)
        await db.flush()
        db.add(
            AuditLogEntry(
                event_name="ticket.resolved",
                payload={"competition_id": comp, "ticket_id": ticket.id},
                competition_id=comp,
                created_at=base + timedelta(seconds=600),
            )
        )
        await db.commit()

    competition = await _load(comp)
    async with SessionLocal() as db:
        data = await build_report_data(db, competition, sections=["support"])
    sup = data["support"]
    assert sup["resolved_count"] == 0
    assert sup["avg_resolution_seconds"] is None


async def test_team_size_distribution_includes_empty_teams(client):
    """Every registered team is bucketed, including a member-less one, so the
    distribution sums to the registered-team count (regression: the membership
    GROUP BY dropped empty teams)."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "Team CTF", "participation_mode": "team", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]
    u1 = await _me_id(client, await _register(client, "u1@example.com"))
    u2 = await _me_id(client, await _register(client, "u2@example.com"))
    async with SessionLocal() as db:
        alpha = Team(competition_id=comp, name="Alpha")
        bravo = Team(competition_id=comp, name="Bravo")  # no members
        db.add_all([alpha, bravo])
        await db.flush()
        db.add_all(
            [
                TeamMembership(competition_id=comp, team_id=alpha.id, user_id=u1),
                TeamMembership(competition_id=comp, team_id=alpha.id, user_id=u2),
            ]
        )
        await db.commit()

    competition = await _load(comp)
    async with SessionLocal() as db:
        data = await build_report_data(db, competition, sections=["participation"])
    part = data["participation"]
    dist = part["team_size_distribution"]
    assert sum(dist.values()) == part["funnel"]["registered"] == 2
    assert dist["1"] == 1  # Bravo (empty) is bucketed, not dropped
    assert dist["2-3"] == 1  # Alpha (2 members)
