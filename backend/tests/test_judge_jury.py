"""The jury console (#450): the staff list, rejudging one or every submission,
overriding a verdict — and above all that points follow the latest verdict:
granted, revoked, moved to another submission, re-valued. The executor is the
scripted fake from test_judge_submissions."""

from datetime import timedelta

from sqlalchemy import select

from db import SessionLocal, utcnow
from models.audit_log import AuditLogEntry
from models.judge import JUDGE_SETTINGS_ID, JudgeSettings
from models.judging import CodeSubmission, Judging
from models.submission import Submission
from tests.test_judge_submissions import (
    FakeExecutor,
    _auth,
    _judge_all,
    _player,
    _setup,
    _submit,
    _verdict,
)
from utils import judge_worker, skills
from utils.event_bus import event_bus

import main  # noqa: F401, E402


def _url(comp, path):
    return f"/api/competitions/{comp}{path}"


async def _points(client, token, comp) -> dict[str, int]:
    board = (await client.get(_url(comp, "/scoreboard"), headers=_auth(token))).json()
    return {e["name"]: e["points"] for e in board["entries"]}


async def _rows() -> list[Submission]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(Submission).order_by(Submission.created_at))).all())


class Events:
    def __init__(self, *names):
        self.names, self.seen = names, []

    async def __call__(self, name, payload):
        self.seen.append((name, payload))

    def __enter__(self):
        for n in self.names:
            event_bus.subscribe(n, self, owner="test-jury")
        return self

    def __exit__(self, *exc):
        event_bus.unsubscribe_owner("test-jury")

    def of(self, name):
        return [p for n, p in self.seen if n == name]


# --- seeing ---------------------------------------------------------------------------


async def test_staff_list_queue_and_history(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    await _submit(client, alice, comp, chal)
    queue = (await client.get(_url(comp, "/judging-queue"), headers=_auth(admin))).json()
    assert queue["queued"] == 1 and queue["running"] == 0 and queue["judge_enabled"] is True
    assert queue["problems"] == 1

    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    page = (await client.get(_url(comp, "/judgings"), headers=_auth(admin))).json()
    assert page["total"] == 1
    [row] = page["items"]
    assert row["user_name"] == "alice" and row["challenge_title"] == "A + B"
    assert row["verdict"] == "wrong_answer" and row["origin"] == "submission"
    assert (await client.get(_url(comp, "/judgings?verdict=accepted"), headers=_auth(admin))).json()["total"] == 0

    history = (
        await client.get(_url(comp, f"/code-submissions/{row['code_submission_id']}/judgings"), headers=_auth(admin))
    ).json()
    assert [h["origin"] for h in history] == ["submission"]


async def test_competitors_cant_use_the_console(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    judging_id = (await _submit(client, alice, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(), object_storage)
    for method, path, body in (
        ("GET", "/judgings", None),
        ("GET", "/judging-queue", None),
        ("POST", f"/judgings/{judging_id}/rejudge", None),
        ("POST", f"/challenges/{chal}/rejudge", {}),
        ("POST", f"/judgings/{judging_id}/override", {"verdict": "wrong_answer", "reason": "nope"}),
    ):
        resp = await client.request(method, _url(comp, path), json=body, headers=_auth(alice))
        assert resp.status_code == 403, (method, path, resp.status_code)


# --- points follow the latest verdict ----------------------------------------------------


async def test_rejudge_to_failing_revokes_the_solve(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    judging_id = (await _submit(client, alice, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(), object_storage)
    assert (await _points(client, admin, comp))["alice"] == 100

    resp = await client.post(_url(comp, f"/judgings/{judging_id}/rejudge"), headers=_auth(admin))
    assert resp.status_code == 202, resp.text
    assert resp.json()["origin"] == "rejudge"
    # Asking twice while it waits is refused.
    again = await client.post(_url(comp, f"/judgings/{judging_id}/rejudge"), headers=_auth(admin))
    assert again.status_code == 409

    with Events("challenge.solve_revoked", "challenge.attempted") as events:
        await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    assert (await _points(client, admin, comp))["alice"] == 0
    assert len(events.of("challenge.solve_revoked")) == 1
    # A rejudge isn't a new attempt.
    assert events.of("challenge.attempted") == []
    # Still one row for the one code submission, now not correct.
    [row] = await _rows()
    assert not row.is_correct and row.points_awarded == 0


async def test_rejudge_to_accepted_grants_the_solve(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    judging_id = (await _submit(client, alice, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    await client.post(_url(comp, f"/judgings/{judging_id}/rejudge"), headers=_auth(admin))
    with Events("challenge.solved") as events:
        await _judge_all(FakeExecutor(), object_storage)
    assert (await _points(client, admin, comp))["alice"] == 100
    [solved] = events.of("challenge.solved")
    assert solved["is_first_blood"] is True


async def test_losing_the_award_promotes_the_next_accepted_submission(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    first = (await _submit(client, alice, comp, chal)).json()["id"]
    second = (await _submit(client, alice, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(), object_storage)
    rows = await _rows()
    assert [(r.is_correct, r.is_duplicate) for r in rows] == [(True, False), (True, True)]

    await client.post(_url(comp, f"/judgings/{first}/rejudge"), headers=_auth(admin))
    with Events("challenge.solve_revoked", "challenge.solved") as events:
        await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    rows = await _rows()
    # The first is no longer correct; the second now holds the award — and
    # alice keeps her points. Nothing is announced: she never stopped solving.
    assert [(r.is_correct, r.is_duplicate) for r in rows] == [(False, False), (True, False)]
    assert rows[1].points_awarded == 100
    assert (await _points(client, admin, comp))["alice"] == 100
    assert events.seen == []
    assert second


async def test_dynamic_values_follow_the_solve_count(client, object_storage):
    admin, comp, chal = await _setup(client)
    await client.patch(
        _url(comp, f"/challenges/{chal}"),
        json={"scoring_type": "dynamic", "points": 500, "min_points": 100, "decay": 2},
        headers=_auth(admin),
    )
    alice = await _player(client, comp, "alice")
    bob = await _player(client, comp, "bob")
    a = (await _submit(client, alice, comp, chal)).json()["id"]
    await _submit(client, bob, comp, chal)
    await _judge_all(FakeExecutor(), object_storage)
    both = await _points(client, admin, comp)
    assert both["alice"] == both["bob"] < 500  # two solves: decayed

    await client.post(_url(comp, f"/judgings/{a}/rejudge"), headers=_auth(admin))
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    after = await _points(client, admin, comp)
    # One solve left: bob's worth climbs back.
    assert after["alice"] == 0 and after["bob"] > both["bob"]


# --- override -----------------------------------------------------------------------------


async def test_override_counts_at_once_and_is_recorded(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    judging_id = (await _submit(client, alice, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)

    resp = await client.post(
        _url(comp, f"/judgings/{judging_id}/override"),
        json={"verdict": "accepted", "reason": "Output format is fine: trailing zeros allowed."},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["origin"] == "override" and body["verdict"] == "accepted"
    assert body["note"].startswith("Output format") and body["requested_by_name"]
    assert (await _points(client, admin, comp))["alice"] == 100

    # The competitor sees it was a judge's decision — but not staff's note.
    mine = (await client.get(_url(comp, f"/judgings/{body['id']}"), headers=_auth(alice))).json()
    assert mine["origin"] == "override" and mine["note"] is None

    # Attributable: the audit entry's actor is the staff member, not alice.
    async with SessionLocal() as db:
        entry = await db.scalar(
            select(AuditLogEntry).where(AuditLogEntry.event_name == "judging.overridden")
        )
        admin_id = (await client.get("/api/auth/me", headers=_auth(admin))).json()["id"]
    assert entry.user_id == admin_id
    assert entry.payload["submitter_user_id"] != admin_id


async def test_override_validation(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    judging_id = (await _submit(client, alice, comp, chal)).json()["id"]
    url = _url(comp, f"/judgings/{judging_id}/override")
    assert (await client.post(url, json={"verdict": "accepted", "reason": "  "}, headers=_auth(admin))).status_code == 422
    assert (await client.post(url, json={"verdict": "internal_error", "reason": "why"}, headers=_auth(admin))).status_code == 422


async def test_an_older_rejudge_cant_overturn_a_newer_override(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    judging_id = (await _submit(client, alice, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    # A rejudge is requested, then — before it runs — a judge overrides.
    await client.post(_url(comp, f"/judgings/{judging_id}/rejudge"), headers=_auth(admin))
    async with SessionLocal() as db:
        rejudge = await db.scalar(select(Judging).where(Judging.origin == "rejudge"))
        rejudge.created_at = utcnow() - timedelta(seconds=5)
        await db.commit()
    await client.post(
        _url(comp, f"/judgings/{judging_id}/override"),
        json={"verdict": "accepted", "reason": "Checked by hand."},
        headers=_auth(admin),
    )
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    # The override stands; the older rejudge's verdict is recorded but doesn't count.
    assert (await _points(client, admin, comp))["alice"] == 100

    # A rejudge asked for *after* the override does replace it.
    await client.post(_url(comp, f"/judgings/{judging_id}/rejudge"), headers=_auth(admin))
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    assert (await _points(client, admin, comp))["alice"] == 0


# --- bulk --------------------------------------------------------------------------------------


async def test_fix_a_test_case_and_rejudge_everything(client, object_storage):
    """#450's acceptance: a test case is fixed, the whole problem is rejudged,
    and awards and the scoreboard reconcile — including a previously accepted
    submission that now fails."""
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    bob = await _player(client, comp, "bob")
    await _submit(client, alice, comp, chal, source="print('alice')")
    await _submit(client, bob, comp, chal, source="print('bob')")
    # Under the broken test case, alice's (wrong) program passed and bob's
    # (right) one failed.
    by_source = {b"print('alice')": "accepted", b"print('bob')": "wrong_answer"}
    await _judge_all(FakeExecutor(*[lambda job: _verdict(by_source[job.source])(job)] * 2), object_storage)
    assert await _points(client, admin, comp) == {"alice": 100, "bob": 0}

    # Fix it — then rejudge every submission to the problem.
    by_source = {b"print('alice')": "wrong_answer", b"print('bob')": "accepted"}
    with Events("judging.rejudge_requested") as events:
        resp = await client.post(_url(comp, f"/challenges/{chal}/rejudge"), json={}, headers=_auth(admin))
    assert resp.json() == {"queued": 2, "skipped": 0, "overridden": 0}
    [requested] = events.of("judging.rejudge_requested")
    assert requested["count"] == 2

    # Asked again while those wait: nothing is queued twice.
    again = await client.post(_url(comp, f"/challenges/{chal}/rejudge"), json={}, headers=_auth(admin))
    assert again.json() == {"queued": 0, "skipped": 2, "overridden": 0}

    await _judge_all(FakeExecutor(*[lambda job: _verdict(by_source[job.source])(job)] * 2), object_storage)
    assert await _points(client, admin, comp) == {"bob": 100, "alice": 0}


async def test_bulk_rejudge_can_target_accepted_or_not(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    bob = await _player(client, comp, "bob")
    await _submit(client, alice, comp, chal, source="print(1)")
    await _submit(client, bob, comp, chal, source="print(2)")
    await _judge_all(FakeExecutor(_verdict("accepted"), _verdict("wrong_answer")), object_storage)
    url = _url(comp, f"/challenges/{chal}/rejudge")
    resp = await client.post(url, json={"only": "accepted"}, headers=_auth(admin))
    assert resp.json()["queued"] == 1
    async with SessionLocal() as db:
        target = await db.scalar(select(Judging).where(Judging.origin == "rejudge"))
        code = await db.get(CodeSubmission, target.code_submission_id)
    assert code.source_object_key  # alice's (the accepted one)
    assert code.user_id == (await client.get("/api/auth/me", headers=_auth(alice))).json()["id"]


async def test_example_runs_aren_t_rejudged(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    run = (await _submit(client, alice, comp, chal, kind="run")).json()["id"]
    await _judge_all(FakeExecutor(), object_storage)
    resp = await client.post(_url(comp, f"/judgings/{run}/rejudge"), headers=_auth(admin))
    assert resp.status_code == 400
    bulk = await client.post(_url(comp, f"/challenges/{chal}/rejudge"), json={}, headers=_auth(admin))
    assert bulk.json() == {"queued": 0, "skipped": 0, "overridden": 0}


async def test_the_award_moves_to_an_earlier_submission_that_becomes_correct(client, object_storage):
    """Alice's first submission failed and her second passed; a fix shows the
    first was right all along. The award moves to the earlier one — same
    points, but an earlier solve time on the board — and nothing is
    re-announced."""
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    first = (await _submit(client, alice, comp, chal, source="print('first')")).json()["id"]
    await _submit(client, alice, comp, chal, source="print('second')")
    await _judge_all(FakeExecutor(_verdict("wrong_answer"), _verdict("accepted")), object_storage)
    board = (await client.get(_url(comp, "/scoreboard"), headers=_auth(admin))).json()
    later_solve = board["entries"][0]["last_solve_at"]

    await client.post(_url(comp, f"/judgings/{first}/rejudge"), headers=_auth(admin))
    with Events("challenge.solved", "challenge.solve_revoked") as events:
        await _judge_all(FakeExecutor(), object_storage)
    rows = await _rows()
    assert [(r.is_correct, r.is_duplicate, r.points_awarded) for r in rows] == [
        (True, False, 100),
        (True, True, 0),
    ]
    assert events.seen == []
    board = (await client.get(_url(comp, "/scoreboard"), headers=_auth(admin))).json()
    [entry] = board["entries"]
    assert entry["points"] == 100 and entry["last_solve_at"] < later_solve


async def test_bulk_rejudge_leaves_overrides_alone(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    bob = await _player(client, comp, "bob")
    a = (await _submit(client, alice, comp, chal, source="print(1)")).json()["id"]
    await _submit(client, bob, comp, chal, source="print(2)")
    await _judge_all(FakeExecutor(_verdict("wrong_answer"), _verdict("wrong_answer")), object_storage)
    await client.post(
        _url(comp, f"/judgings/{a}/override"),
        json={"verdict": "accepted", "reason": "Checked by hand."},
        headers=_auth(admin),
    )
    resp = await client.post(_url(comp, f"/challenges/{chal}/rejudge"), json={}, headers=_auth(admin))
    # A bulk fix doesn't silently reverse a judge's deliberate decision.
    assert resp.json() == {"queued": 1, "skipped": 0, "overridden": 1}
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    assert (await _points(client, admin, comp))["alice"] == 100


async def test_bulk_rejudge_includes_submissions_still_being_judged(client, object_storage):
    """A judging already running may be using the old (broken) test data, so a
    bulk rejudge queues a fresh one for it — newer, so its verdict wins. Only a
    judging still waiting is skipped."""
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    bob = await _player(client, comp, "bob")
    await _submit(client, alice, comp, chal, source="print(1)")
    claim = await judge_worker.claim_next(SessionLocal)  # alice's: running, no verdict yet
    await _submit(client, bob, comp, chal, source="print(2)")  # bob's: still waiting

    resp = await client.post(
        _url(comp, f"/challenges/{chal}/rejudge"), json={"only": "not_accepted"}, headers=_auth(admin)
    )
    assert resp.json() == {"queued": 1, "skipped": 1, "overridden": 0}

    # The stale run passes under the old data; the rejudge, judged against the
    # fixed data, fails — and it's the one that counts.
    await judge_worker.run_judging(
        SessionLocal, claim, executor=FakeExecutor(_verdict("accepted")), storage=object_storage
    )
    assert (await _points(client, admin, comp))["alice"] == 100
    await _judge_all(FakeExecutor(_verdict("wrong_answer"), _verdict("wrong_answer")), object_storage)
    assert (await _points(client, admin, comp))["alice"] == 0


async def test_staff_rejudges_dont_count_against_the_submission_cap(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    for i in range(3):
        await _submit(client, alice, comp, chal, source=f"print({i})")
    await _judge_all(FakeExecutor(*[_verdict("wrong_answer")] * 3), object_storage)
    resp = await client.post(_url(comp, f"/challenges/{chal}/rejudge"), json={}, headers=_auth(admin))
    assert resp.json()["queued"] == 3
    # Three of alice's judgings are waiting — but staff queued them, not her.
    assert (await _submit(client, alice, comp, chal)).status_code == 202


async def test_an_earlier_submission_judged_last_still_takes_the_award(client, object_storage):
    """Two workers can finish out of order: alice's later submission is judged
    first and takes the award, then her earlier one passes too. The award
    belongs to the earlier one."""
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    first = (await _submit(client, alice, comp, chal, source="print('first')")).json()["id"]
    await _submit(client, alice, comp, chal, source="print('second')")
    async with SessionLocal() as db:
        (await db.get(JudgeSettings, JUDGE_SETTINGS_ID)).max_concurrent_judgings = 1
        # Claimed last: the worker takes the oldest queued judging first.
        (await db.get(Judging, first)).created_at = utcnow() + timedelta(seconds=5)
        await db.commit()
    await _judge_all(FakeExecutor(), object_storage)
    rows = await _rows()
    assert [(r.is_correct, r.is_duplicate, r.points_awarded) for r in rows] == [
        (True, False, 100),
        (True, True, 0),
    ]
    assert (await _points(client, admin, comp))["alice"] == 100


async def test_a_revoked_solve_refreshes_the_skills_web(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    judging_id = (await _submit(client, alice, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(), object_storage)
    await client.post(_url(comp, f"/judgings/{judging_id}/rejudge"), headers=_auth(admin))
    skills._cache["sentinel"] = (float("inf"), {})
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    assert "sentinel" not in skills._cache


async def test_a_regraded_solve_is_marked_for_automations(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    judging_id = (await _submit(client, alice, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    await client.post(_url(comp, f"/judgings/{judging_id}/rejudge"), headers=_auth(admin))
    with Events("challenge.solved") as events:
        await _judge_all(FakeExecutor(), object_storage)
    [solved] = events.of("challenge.solved")
    assert solved["regrade"] is True


async def test_queue_counts_programming_problems_only(client, object_storage):
    """The sidebar shows Judging only when the competition has a programming
    problem — drafts included, flag challenges not."""
    admin, comp, _chal = await _setup(client, publish=False)
    other = (
        await client.post("/api/competitions", json={"name": "Flags only"}, headers=_auth(admin))
    ).json()["id"]
    flag = await client.post(
        _url(other, "/challenges"),
        json={"title": "Warm-up", "points": 10, "flag": "flag{x}"},
        headers=_auth(admin),
    )
    assert flag.status_code == 201, flag.text
    for cid, expected in ((comp, 1), (other, 0)):
        queue = (await client.get(_url(cid, "/judging-queue"), headers=_auth(admin))).json()
        assert queue["problems"] == expected, cid
