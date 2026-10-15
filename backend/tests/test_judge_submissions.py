"""Submitting code, the judging queue and the worker (#448, ADR-0042).

The executor is a scripted fake here (its real counterpart is exercised in
test_judge_executor / test_judge_executor_e2e), so these tests cover what the
platform does around a judging: the submit route's gates, the atomic claim,
recording the verdict through the shared award path — backdated — the retry
and fencing rules, the reaper, start-up recovery, and who may read what.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from db import SessionLocal, utcnow
from models.competition import Competition
from models.judge import JUDGE_SETTINGS_ID, JudgeLanguage, JudgeSettings
from models.judging import CodeSubmission, Judging, JudgingRun
from models.submission import Submission
from tests.conftest import admin_token
from utils import judge_worker
from utils.event_bus import event_bus
from utils.judge_executor import (
    JudgeExecutor,
    JudgeExecutorError,
    JudgeResult,
    JudgeTestResult,
)

import main  # noqa: F401, E402  (loads the judge module's routes)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class FakeExecutor(JudgeExecutor):
    """Returns scripted results (or raises), recording the jobs it was given."""

    kind = "fake"

    def __init__(self, *results):
        self.results = list(results)
        self.jobs = []
        self.cleaned = 0

    @classmethod
    def from_settings(cls, settings):
        return cls()

    async def run(self, job):
        self.jobs.append(job)
        outcome = self.results.pop(0) if self.results else _accepted(job)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome(job) if callable(outcome) else outcome

    async def validate(self):
        return []

    def time_budget_s(self, job):
        return 60.0

    async def cleanup(self, keep):
        self.cleaned += 1
        self.kept = set(keep)
        return 0


def _accepted(job, verdict="accepted"):
    return JudgeResult(
        verdict=verdict,
        tests=tuple(
            JudgeTestResult(
                index=i, sample=t.sample, verdict=verdict if i == len(job.tests) - 1 else "accepted",
                # Output on every test, hidden ones too: the read route must
                # still never show a hidden test's (defence in depth — the real
                # harness and executor already drop it).
                time_ms=10 + i, wall_ms=20, memory_kb=1000 + 100 * i, output="out",
            )
            for i, t in enumerate(job.tests)
        ),
    )


def _verdict(verdict):
    return lambda job: _accepted(job, verdict)


# --- fixtures -------------------------------------------------------------------------


async def _enable_judge(languages=("python3",)) -> None:
    async with SessionLocal() as db:
        if await db.get(JudgeSettings, JUDGE_SETTINGS_ID) is None:
            db.add(JudgeSettings(id=JUDGE_SETTINGS_ID, enabled=True, endpoint_url="http://judge:2375"))
        for key in languages:
            db.add(JudgeLanguage(key=key, name=key.title(), image_ref="python:3.14-slim",
                                 source_filename="solution.py", run_command=["python3", "{source}"]))
        await db.commit()


async def _setup(client, *, mode="individual", samples=1, secrets=2, publish=True):
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "Code Cup", "participation_mode": mode, "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]
    await _enable_judge()
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "A + B", "points": 100, "flag_type": "programming"},
            headers=_auth(admin),
        )
    ).json()["id"]
    for i in range(samples + secrets):
        resp = await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/judge/testcases",
            json={"input": f"{i} {i}", "answer": str(2 * i), "sample": i < samples},
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text
    if publish:
        resp = await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
        )
        assert resp.status_code == 200, resp.text
    return admin, comp, chal


async def _player(client, comp, name="coder") -> str:
    token = (
        await client.post(
            "/api/auth/register",
            json={"email": f"{name}@example.com", "password": "password123", "display_name": name},
        )
    ).json()["access_token"]
    resp = await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    assert resp.status_code in (200, 201, 204), resp.text
    return token


def _submit(client, token, comp, chal, **over):
    body = {"language": "python3", "source": "print(sum(map(int, input().split())))", **over}
    return client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit-code", json=body, headers=_auth(token)
    )


async def _judge_all(executor, object_storage):
    """Drive the worker until the queue is empty."""
    while True:
        tasks = await judge_worker.fill_slots(SessionLocal, executor=executor, storage=object_storage)
        if not tasks:
            return
        for task in tasks:
            await task


async def _judging(judging_id) -> Judging:
    async with SessionLocal() as db:
        return await db.get(Judging, judging_id)


@pytest.fixture(autouse=True)
def _no_live_worker():
    yield
    judge_worker._running.clear()


# --- submitting --------------------------------------------------------------------------


async def test_submit_queues_a_judging(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    seen = []

    async def capture(name, payload):
        seen.append(payload)

    event_bus.subscribe("judging.queued", capture, owner="test-judging")
    try:
        resp = await _submit(client, player, comp, chal)
    finally:
        event_bus.unsubscribe_owner("test-judging")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued" and body["queue_position"] == 1
    assert body["kind"] == "submit" and body["language_key"] == "python3"
    assert seen and seen[0]["judging_id"] == body["id"] and "source" not in seen[0]

    async with SessionLocal() as db:
        code = await db.scalar(select(CodeSubmission))
    assert object_storage.get(code.source_object_key) == b"print(sum(map(int, input().split())))"
    assert code.source_object_key.startswith(f"{comp}/judge-src/{chal}/")

    second = (await _submit(client, player, comp, chal)).json()
    assert second["queue_position"] == 2


async def test_submit_gates(client, monkeypatch):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)

    flag_chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "flag", "flag": "flag{x}"}, headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(f"/api/competitions/{comp}/challenges/{flag_chal}/publish", headers=_auth(admin))
    assert (await _submit(client, player, comp, flag_chal)).status_code == 400

    assert (await _submit(client, player, comp, chal, language="cobol")).status_code == 400
    assert (await _submit(client, player, comp, chal, source="   \n")).status_code == 400
    big = (await _submit(client, player, comp, chal, source="#" * (130 * 1024)))
    assert big.status_code == 413
    assert (await _submit(client, player, comp, chal, kind="debug")).status_code == 422

    # A language the problem doesn't allow.
    await _enable_judge(languages=("cpp",))
    await client.put(
        f"/api/competitions/{comp}/challenges/{chal}/judge",
        json={"allowed_languages": ["cpp"]}, headers=_auth(admin),
    )
    assert (await _submit(client, player, comp, chal)).status_code == 400

    # The judge switched off.
    async with SessionLocal() as db:
        settings = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
        settings.enabled = False
        await db.commit()
    assert (await _submit(client, player, comp, chal, language="cpp")).status_code == 503


async def test_module_off_404s(client):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    await client.put(
        f"/api/competitions/{comp}/modules/judge", json={"enabled": False}, headers=_auth(admin)
    )
    assert (await _submit(client, player, comp, chal)).status_code == 404


async def test_draft_is_invisible_to_competitors(client):
    admin, comp, chal = await _setup(client, publish=False)
    player = await _player(client, comp)
    assert (await _submit(client, player, comp, chal)).status_code == 404
    # Staff can test a draft.
    assert (await _submit(client, admin, comp, chal)).status_code == 202


async def test_run_needs_examples(client):
    admin, comp, chal = await _setup(client, samples=0, secrets=1)
    player = await _player(client, comp)
    assert (await _submit(client, player, comp, chal, kind="run")).status_code == 400
    assert (await _submit(client, player, comp, chal)).status_code == 202


async def test_in_flight_cap(client):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    for _ in range(3):
        assert (await _submit(client, player, comp, chal)).status_code == 202
    resp = await _submit(client, player, comp, chal)
    assert resp.status_code == 429 and "waiting to be judged" in resp.json()["detail"]


async def test_team_mode_needs_a_team(client):
    admin, comp, chal = await _setup(client, mode="team")
    player = await _player(client, comp)
    resp = await _submit(client, player, comp, chal)
    assert resp.status_code == 400 and "team" in resp.json()["detail"]


async def test_paused_competition_refuses(client):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    async with SessionLocal() as db:
        competition = await db.get(Competition, comp)
        competition.paused = True
        await db.commit()
    assert (await _submit(client, player, comp, chal)).status_code == 403


# --- the worker ------------------------------------------------------------------------------


async def test_accepted_awards_points_backdated(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    async with SessionLocal() as db:
        code = await db.scalar(select(CodeSubmission))
        # The verdict lands well after submission (a long queue).
        code.created_at = utcnow() - timedelta(minutes=30)
        await db.commit()
        submitted_at = code.created_at

    solved = []

    async def capture(name, payload):
        solved.append(payload)

    event_bus.subscribe("challenge.solved", capture, owner="test-judging")
    try:
        executor = FakeExecutor()
        await _judge_all(executor, object_storage)
    finally:
        event_bus.unsubscribe_owner("test-judging")

    job = executor.jobs[0]
    assert [t.sample for t in job.tests] == [True, False, False]
    assert job.source == b"print(sum(map(int, input().split())))"
    judging = await _judging(judging_id)
    assert judging.status == "done" and judging.verdict == "accepted"
    assert judging.tests_passed == 3 and judging.tests_total == 3
    async with SessionLocal() as db:
        sub = await db.get(Submission, judging.submission_id)
        runs = (await db.scalars(select(JudgingRun).where(JudgingRun.judging_id == judging_id))).all()
    assert sub.is_correct and sub.points_awarded == 100 and not sub.is_duplicate
    # Backdated to submission time, so the queue never costs first blood.
    assert abs((sub.created_at - submitted_at).total_seconds()) < 1
    # One row per code submission, whatever its judgings (#450).
    assert sub.value == f"code:{judging.code_submission_id}"
    assert len(runs) == 3
    assert solved and solved[0]["is_first_blood"] is True

    board = (await client.get(f"/api/competitions/{comp}/scoreboard", headers=_auth(player))).json()
    [entry] = board["entries"]
    assert entry["points"] == 100
    # The board's tie-break time is the submission time, not the verdict time.
    from datetime import datetime

    solve_at = datetime.fromisoformat(entry["last_solve_at"])
    assert abs((solve_at - submitted_at).total_seconds()) < 1


async def test_wrong_answer_is_logged_not_awarded(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)
    judging = await _judging(judging_id)
    assert judging.status == "done" and judging.verdict == "wrong_answer"
    async with SessionLocal() as db:
        sub = await db.get(Submission, judging.submission_id)
    assert not sub.is_correct and sub.points_awarded == 0


async def test_second_accept_is_a_duplicate(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    first = (await _submit(client, player, comp, chal)).json()["id"]
    second = (await _submit(client, player, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(), object_storage)
    async with SessionLocal() as db:
        subs = {
            j: await db.get(Submission, (await db.get(Judging, j)).submission_id)
            for j in (first, second)
        }
    assert subs[first].points_awarded == 100 and not subs[first].is_duplicate
    assert subs[second].is_duplicate and subs[second].points_awarded == 0


async def test_run_judges_examples_only_and_never_scores(client, object_storage):
    admin, comp, chal = await _setup(client, samples=2, secrets=2)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal, kind="run")).json()["id"]
    executor = FakeExecutor()
    await _judge_all(executor, object_storage)
    assert [t.sample for t in executor.jobs[0].tests] == [True, True]
    judging = await _judging(judging_id)
    assert judging.verdict == "accepted" and judging.submission_id is None
    assert judging.tests_total == 2
    async with SessionLocal() as db:
        assert (await db.scalar(select(Submission))) is None


async def test_judge_failure_retries_then_fails_without_scoring(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    executor = FakeExecutor(
        JudgeExecutorError("proxy down"),
        _verdict("internal_error"),
        JudgeExecutorError("still down"),
    )
    await _judge_all(executor, object_storage)
    judging = await _judging(judging_id)
    assert len(executor.jobs) == judge_worker.MAX_ATTEMPTS == 3
    assert judging.status == "failed" and judging.verdict == "internal_error"
    assert judging.error == "still down"
    async with SessionLocal() as db:
        assert (await db.scalar(select(Submission))) is None


async def test_a_transient_failure_then_success(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(JudgeExecutorError("blip")), object_storage)
    judging = await _judging(judging_id)
    assert judging.status == "done" and judging.verdict == "accepted" and judging.attempts == 2


async def test_a_removed_language_fails_without_retrying(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    async with SessionLocal() as db:
        lang = await db.scalar(select(JudgeLanguage).where(JudgeLanguage.key == "python3"))
        await db.delete(lang)
        await db.commit()
    executor = FakeExecutor()
    await _judge_all(executor, object_storage)
    judging = await _judging(judging_id)
    assert executor.jobs == [] and judging.attempts == 1
    assert judging.status == "failed" and "no longer available" in judging.error


async def test_first_blood_follows_submission_time_not_verdict_order(client, object_storage):
    """With concurrent judgings a later-submitted one can finish first. The
    read paths rank by (backdated) submission time, so the earliest submitter
    is announced as first blood when their verdict lands, too."""
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    bob = await _player(client, comp, "bob")
    await _submit(client, alice, comp, chal)
    await _submit(client, bob, comp, chal)
    async with SessionLocal() as db:
        (await db.get(JudgeSettings, JUDGE_SETTINGS_ID)).max_concurrent_judgings = 2
        await db.commit()
    first = await judge_worker.claim_next(SessionLocal)  # alice's
    second = await judge_worker.claim_next(SessionLocal)  # bob's
    solved = []

    async def capture(name, payload):
        solved.append(payload)

    event_bus.subscribe("challenge.solved", capture, owner="test-judging")
    try:
        await judge_worker.run_judging(SessionLocal, second, executor=FakeExecutor(), storage=object_storage)
        await judge_worker.run_judging(SessionLocal, first, executor=FakeExecutor(), storage=object_storage)
    finally:
        event_bus.unsubscribe_owner("test-judging")
    by_user = {p["user_id"]: p["is_first_blood"] for p in solved}
    solves = (
        await client.get(f"/api/competitions/{comp}/challenges/{chal}/solves", headers=_auth(admin))
    ).json()
    blood = [s for s in solves if s["is_first_blood"]]
    assert len(blood) == 1
    assert by_user[blood[0]["subject_id"]] is True


async def test_claim_is_atomic(client):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    await _submit(client, player, comp, chal)
    first = await judge_worker.claim_next(SessionLocal)
    assert first is not None and first.attempt == 1
    assert await judge_worker.claim_next(SessionLocal) is None


async def test_a_lost_claim_writes_nothing(client, object_storage):
    """A worker whose judging was reclaimed (and claimed again) can't write a
    second result or a second award — the attempt is the fencing token."""
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    stale = await judge_worker.claim_next(SessionLocal)
    # The reaper reclaims it and another pass claims it again.
    await judge_worker.reap_judgings(SessionLocal, now=utcnow() + timedelta(hours=1))
    fresh = await judge_worker.claim_next(SessionLocal)
    assert fresh.attempt == 2
    await judge_worker.run_judging(SessionLocal, stale, executor=FakeExecutor(), storage=object_storage)
    judging = await _judging(judging_id)
    assert judging.status == "running" and judging.submission_id is None
    await judge_worker.run_judging(SessionLocal, fresh, executor=FakeExecutor(), storage=object_storage)
    judging = await _judging(judging_id)
    assert judging.status == "done"
    async with SessionLocal() as db:
        assert len((await db.scalars(select(Submission))).all()) == 1


async def test_a_claim_lost_mid_judging_writes_nothing(client, object_storage):
    """The race the fence exists for: the judging is reclaimed — and claimed
    again — while the first worker's container is still running."""
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    stale = await judge_worker.claim_next(SessionLocal)
    taken = {}

    class Slow(FakeExecutor):
        async def run(self, job):
            await judge_worker.reap_judgings(SessionLocal, now=utcnow() + timedelta(hours=1))
            taken["claim"] = await judge_worker.claim_next(SessionLocal)
            return await super().run(job)

    await judge_worker.run_judging(SessionLocal, stale, executor=Slow(), storage=object_storage)
    judging = await _judging(judging_id)
    assert taken["claim"].attempt == 2
    assert judging.status == "running" and judging.verdict is None and judging.submission_id is None
    async with SessionLocal() as db:
        assert (await db.scalar(select(Submission))) is None
        assert (await db.scalar(select(JudgingRun))) is None
    # A failure report from the stale worker is fenced off the same way.
    await judge_worker._give_up_or_retry(SessionLocal, stale, "late error", retry=False)
    assert (await _judging(judging_id)).status == "running"


async def test_reaper_reclaims_overdue_and_gives_up_eventually(client):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    later = utcnow() + timedelta(hours=1)
    # Not overdue yet: left alone.
    await judge_worker.claim_next(SessionLocal)
    assert await judge_worker.reap_judgings(SessionLocal) == 0
    for attempt in range(1, judge_worker.MAX_ATTEMPTS):
        assert await judge_worker.reap_judgings(SessionLocal, now=later) == 1
        assert (await _judging(judging_id)).status == "queued"
        await judge_worker.claim_next(SessionLocal)
    await judge_worker.reap_judgings(SessionLocal, now=later)
    judging = await _judging(judging_id)
    assert judging.status == "failed" and judging.verdict == "internal_error"


async def test_recover_reclaims_only_overdue_judgings(client):
    """At start-up, a judging still inside its deadline may belong to another
    process (a rolling deploy's old worker): only overdue ones are reclaimed,
    and the container sweep is told which judgings are live."""
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    await judge_worker.claim_next(SessionLocal)
    executor = FakeExecutor()
    await judge_worker.recover(SessionLocal, executor=executor)
    assert (await _judging(judging_id)).status == "running"
    assert executor.cleaned == 1 and executor.kept == {judging_id}

    async with SessionLocal() as db:
        (await db.get(Judging, judging_id)).deadline_at = utcnow() - timedelta(seconds=1)
        await db.commit()
    await judge_worker.recover(SessionLocal, executor=executor)
    assert (await _judging(judging_id)).status == "queued"
    assert executor.kept == set()


async def test_reaper_counts_only_rows_it_changed(client, monkeypatch):
    """If the worker finishes a judging between the reaper's read and its
    update, the reaper must not report it failed."""
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    await _submit(client, player, comp, chal)
    async with SessionLocal() as db:
        judging = await db.scalar(select(Judging))
        judging.status, judging.attempts = "running", judge_worker.MAX_ATTEMPTS
        judging.deadline_at = utcnow() - timedelta(minutes=1)
        await db.commit()
    emitted = []

    async def record(judging, verdict):
        emitted.append(verdict)

    monkeypatch.setattr(judge_worker, "_emit_completed", record)
    # The row changes underneath: the fenced update matches nothing.
    monkeypatch.setattr(judge_worker, "_fenced", lambda claim: (Judging.id == "someone-else",))
    assert await judge_worker.reap_judgings(SessionLocal, executor=FakeExecutor()) == 0
    assert emitted == []


async def test_a_judging_deleted_mid_run_is_dropped_quietly(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    await _submit(client, player, comp, chal)
    claim = await judge_worker.claim_next(SessionLocal)

    class Deleting(FakeExecutor):
        async def run(self, job):
            async with SessionLocal() as db:
                await db.delete(await db.get(Judging, claim.judging_id))
                await db.commit()
            return await super().run(job)

    await judge_worker.run_judging(SessionLocal, claim, executor=Deleting(), storage=object_storage)
    async with SessionLocal() as db:
        assert (await db.scalar(select(Submission))) is None


async def test_disabled_judge_claims_nothing(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    await _submit(client, player, comp, chal)
    async with SessionLocal() as db:
        (await db.get(JudgeSettings, JUDGE_SETTINGS_ID)).enabled = False
        await db.commit()
    assert await judge_worker.fill_slots(SessionLocal, executor=FakeExecutor(), storage=object_storage) == []


async def test_concurrency_limit(client, object_storage):
    admin, comp, chal = await _setup(client)
    a = await _player(client, comp, "a")
    b = await _player(client, comp, "b")
    await _submit(client, a, comp, chal)
    await _submit(client, b, comp, chal)
    tasks = await judge_worker.fill_slots(SessionLocal, executor=FakeExecutor(), storage=object_storage)
    assert len(tasks) == 1  # the default: one judging at a time
    await tasks[0]


# --- reading -----------------------------------------------------------------------------------


async def test_reads_are_by_ownership(client, object_storage):
    admin, comp, chal = await _setup(client)
    alice = await _player(client, comp, "alice")
    bob = await _player(client, comp, "bob")
    judging_id = (await _submit(client, alice, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)

    mine = (await client.get(f"/api/competitions/{comp}/judgings/{judging_id}", headers=_auth(alice))).json()
    assert mine["verdict"] == "wrong_answer" and mine["error"] is None
    sample, *secret = mine["tests"]
    assert sample["sample"] and sample["output"] == "out" and sample["time_ms"] == 10
    # Hidden tests: position and verdict only.
    assert all(t["time_ms"] is None and t["memory_kb"] is None and t["output"] is None for t in secret)
    source = (await client.get(f"/api/competitions/{comp}/judgings/{judging_id}/source", headers=_auth(alice))).json()
    assert source["source"].startswith("print(")

    for path in ("", "/source"):
        resp = await client.get(f"/api/competitions/{comp}/judgings/{judging_id}{path}", headers=_auth(bob))
        assert resp.status_code == 404

    # The judging's maxima are over the examples too, or they'd carry what the
    # hidden tests took.
    assert mine["max_time_ms"] == 10 and mine["max_memory_kb"] == 1000

    staff = (await client.get(f"/api/competitions/{comp}/judgings/{judging_id}", headers=_auth(admin))).json()
    assert staff["tests"][1]["time_ms"] is not None
    assert staff["max_time_ms"] == 12 and staff["max_memory_kb"] == 1200

    history = (await client.get(f"/api/competitions/{comp}/challenges/{chal}/judgings", headers=_auth(alice))).json()
    assert [h["id"] for h in history] == [judging_id]
    assert (await client.get(f"/api/competitions/{comp}/challenges/{chal}/judgings", headers=_auth(bob))).json() == []


async def test_teammates_share_history(client):
    admin, comp, chal = await _setup(client, mode="team")
    alice = await _player(client, comp, "alice")
    bob = await _player(client, comp, "bob")
    team = (await client.post(f"/api/competitions/{comp}/teams", json={"name": "Byte"}, headers=_auth(alice))).json()
    joined = await client.post(
        f"/api/competitions/{comp}/teams/join", json={"invite_code": team["invite_code"]}, headers=_auth(bob)
    )
    assert joined.status_code in (200, 201), joined.text
    judging_id = (await _submit(client, alice, comp, chal)).json()["id"]
    resp = await client.get(f"/api/competitions/{comp}/judgings/{judging_id}", headers=_auth(bob))
    assert resp.status_code == 200
    history = (await client.get(f"/api/competitions/{comp}/challenges/{chal}/judgings", headers=_auth(bob))).json()
    assert [h["id"] for h in history] == [judging_id]


async def test_staff_see_the_internal_error(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(*[JudgeExecutorError("proxy down")] * 3), object_storage)
    mine = (await client.get(f"/api/competitions/{comp}/judgings/{judging_id}", headers=_auth(player))).json()
    staff = (await client.get(f"/api/competitions/{comp}/judgings/{judging_id}", headers=_auth(admin))).json()
    assert mine["verdict"] == "internal_error" and mine["error"] is None
    assert staff["error"] == "proxy down"


# --- lifecycle ------------------------------------------------------------------------------------


async def test_run_sources_are_not_kept(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    judging_id = (await _submit(client, player, comp, chal, kind="run")).json()["id"]
    async with SessionLocal() as db:
        key = (await db.scalar(select(CodeSubmission))).source_object_key
    await _judge_all(FakeExecutor(), object_storage)
    assert not object_storage.exists(key)
    resp = await client.get(f"/api/competitions/{comp}/judgings/{judging_id}/source", headers=_auth(player))
    assert resp.status_code == 404
    # A scored submission keeps its source.
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(), object_storage)
    resp = await client.get(f"/api/competitions/{comp}/judgings/{judging_id}/source", headers=_auth(player))
    assert resp.status_code == 200


async def test_user_delete_removes_their_sources(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    await _submit(client, player, comp, chal)
    async with SessionLocal() as db:
        code = await db.scalar(select(CodeSubmission))
        key, user_id = code.source_object_key, code.user_id
    resp = await client.delete(f"/api/users/{user_id}", headers=_auth(admin))
    assert resp.status_code == 204, resp.text
    assert not object_storage.exists(key)


async def test_challenge_delete_removes_sources(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    await _submit(client, player, comp, chal)
    async with SessionLocal() as db:
        key = (await db.scalar(select(CodeSubmission))).source_object_key
    assert object_storage.exists(key)
    resp = await client.delete(f"/api/competitions/{comp}/challenges/{chal}", headers=_auth(admin))
    assert resp.status_code == 204
    assert not object_storage.exists(key)


async def test_competition_purge_removes_sources(client, object_storage):
    from utils.retention import delete_competition_tree

    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    await _submit(client, player, comp, chal)
    async with SessionLocal() as db:
        key = (await db.scalar(select(CodeSubmission))).source_object_key
        await delete_competition_tree(db, object_storage, await db.get(Competition, comp))
    assert not object_storage.exists(key)


# --- the problem page's API (#449) ------------------------------------------------------------


async def test_problem_view_shows_examples_never_hidden_tests(client):
    admin, comp, chal = await _setup(client, samples=1, secrets=2)
    player = await _player(client, comp)
    async with SessionLocal() as db:
        lang = await db.scalar(select(JudgeLanguage).where(JudgeLanguage.key == "python3"))
        lang.time_multiplier = 1.5
        await db.commit()
    body = (
        await client.get(f"/api/competitions/{comp}/challenges/{chal}/problem", headers=_auth(player))
    ).json()
    assert body["time_limit_ms"] == 2000 and body["memory_limit_mb"] == 256
    assert body["compare_mode"] == "token" and body["judge_ready"] is True
    assert body["languages"] == [
        {"key": "python3", "name": "Python3", "time_limit_ms": 3000, "extension": ".py"}
    ]
    # Only the example — the hidden tests' data never leaves the server.
    assert body["examples"] == [{"index": 0, "input": "0 0\n", "answer": "0\n", "truncated": False}]


async def test_problem_view_respects_allowed_languages_and_visibility(client):
    admin, comp, chal = await _setup(client, publish=False)
    player = await _player(client, comp)
    url = f"/api/competitions/{comp}/challenges/{chal}/problem"
    assert (await client.get(url, headers=_auth(player))).status_code == 404  # a draft
    await _enable_judge(languages=("cpp",))
    await client.put(
        f"/api/competitions/{comp}/challenges/{chal}/judge",
        json={"allowed_languages": ["cpp"]}, headers=_auth(admin),
    )
    body = (await client.get(url, headers=_auth(admin))).json()
    assert [lang["key"] for lang in body["languages"]] == ["cpp"]

    flag_chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges", json={"title": "f", "flag": "flag{f}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    resp = await client.get(f"/api/competitions/{comp}/challenges/{flag_chal}/problem", headers=_auth(admin))
    assert resp.status_code == 400


async def test_submitter_gets_live_frames(client, object_storage, monkeypatch):
    from realtime import manager

    frames = []

    async def record(room_type, room_id, message, **kw):
        frames.append((room_type, room_id, message))

    monkeypatch.setattr(manager, "broadcast", record)
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    me = (await client.get("/api/auth/me", headers=_auth(player))).json()["id"]
    judging_id = (await _submit(client, player, comp, chal)).json()["id"]
    await _judge_all(FakeExecutor(_verdict("wrong_answer")), object_storage)

    mine = [m for t, room, m in frames if t == "user" and room == me and m.get("type") == "judging"]
    assert [(m["status"], m["verdict"]) for m in mine] == [
        ("queued", None), ("running", None), ("done", "wrong_answer"),
    ]
    assert all(m["judging_id"] == judging_id and m["challenge_id"] == chal for m in mine)
    # Ids and state only — what the competitor may see is the REST read's call.
    assert set(mine[0]) == {"type", "competition_id", "challenge_id", "judging_id", "status", "verdict"}
