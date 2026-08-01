"""Concurrency invariants on scoring (§13.2).

"The first correct submission is authoritative" and the multiple-choice guess
cap were both enforced by read-then-write: query, then insert. Two requests for
the same subject interleave between those steps, so both saw a clean slate and
both were graded — banking a flag's points N times, or spending N guesses on a
capped question.

Real concurrency isn't reproducible here (SQLite serialises writers, so the
interleaving the fix targets can't be provoked), and a test that can't fail
proves nothing. These pin the invariant instead: the schema rejects a second
awarded row, and the route's race-loser path records a duplicate rather than a
second award.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db import SessionLocal
from models.role import Role, RoleAssignment
from models.submission import Submission
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": email.split("@")[0],
        },
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _individual_competition(client) -> str:
    admin = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={"name": "CTF", "participation_mode": "individual"},
        headers=_auth(admin),
    )
    return resp.json()["id"]


async def _published_challenge(client, comp: str, flag: str, points: int) -> str:
    admin = await admin_token(client)
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": f"Chal {flag}", "points": points, "flag": flag},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
    )
    return chal


async def _join(comp: str, user_id: str) -> None:
    async with SessionLocal() as s:
        role = await s.scalar(select(Role).where(Role.name == "Participant"))
        s.add(RoleAssignment(user_id=user_id, competition_id=comp, role_id=role.id))
        await s.commit()


async def _submit(client, comp: str, chal: str, token: str, flag: str):
    return await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": flag},
        headers=_auth(token),
    )


async def test_schema_rejects_a_second_awarded_row_for_one_subject(client):
    """The invariant, at the only layer that can hold it under concurrency.

    Written directly against the table, bypassing the route, because the point
    is that the *database* refuses — not that the route remembered to check.
    """
    comp = await _individual_competition(client)
    chal = await _published_challenge(client, comp, "flag{a}", 100)
    player, pid = await _register(client, "ada@example.com")
    await _join(comp, pid)

    assert (await _submit(client, comp, chal, player, "flag{a}")).status_code == 200

    async with SessionLocal() as s:
        s.add(
            Submission(
                competition_id=comp,
                challenge_id=chal,
                user_id=pid,
                team_id=None,
                value="flag{a}",
                is_correct=True,
                is_duplicate=False,
                points_awarded=100,
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()

    # Duplicates and wrong answers stay unbounded — the index is partial.
    async with SessionLocal() as s:
        for is_correct, is_dup in ((True, True), (False, False), (False, False)):
            s.add(
                Submission(
                    competition_id=comp,
                    challenge_id=chal,
                    user_id=pid,
                    team_id=None,
                    value="whatever",
                    is_correct=is_correct,
                    is_duplicate=is_dup,
                    points_awarded=0,
                )
            )
        await s.commit()  # must not raise


async def test_race_loser_is_recorded_as_a_duplicate_not_a_second_award(
    client, monkeypatch
):
    """Drive the route's IntegrityError path deterministically.

    `subject_has_solved` is forced to report "not solved", which is exactly what
    the losing request sees in a real race: it read before the winner committed.
    The route must then absorb the constraint violation rather than 500, and the
    subject must not be paid twice.
    """
    comp = await _individual_competition(client)
    chal = await _published_challenge(client, comp, "flag{a}", 100)
    player, pid = await _register(client, "bob@example.com")
    await _join(comp, pid)

    assert (await _submit(client, comp, chal, player, "flag{a}")).status_code == 200

    import routers.submissions as submissions_router

    async def _stale_read(*_args, **_kwargs):
        return False

    monkeypatch.setattr(submissions_router, "subject_has_solved", _stale_read)

    resp = await _submit(client, comp, chal, player, "flag{a}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["correct"] is True
    assert body["already_solved"] is True
    assert body["points_awarded"] == 0

    async with SessionLocal() as s:
        awarded = (
            await s.scalars(
                select(Submission).where(
                    Submission.challenge_id == chal,
                    Submission.is_correct.is_(True),
                    Submission.is_duplicate.is_(False),
                )
            )
        ).all()
    assert len(awarded) == 1, "the race loser was awarded a second time"

    board = (
        await client.get(f"/api/competitions/{comp}/scoreboard", headers=_auth(player))
    ).json()
    assert board["entries"][0]["points"] == 100, "points were double-counted"

    # The attempt is still on the record (§13.2), as a duplicate worth nothing.
    async with SessionLocal() as s:
        dupe_points = (
            await s.execute(
                select(Submission.points_awarded).where(
                    Submission.challenge_id == chal,
                    Submission.is_duplicate.is_(True),
                )
            )
        ).scalars().all()
    assert dupe_points == [0]
