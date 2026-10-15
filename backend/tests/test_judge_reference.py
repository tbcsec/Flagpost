"""An author's reference-solution check (#450): a solution they know is right,
run through the real queue against every test — without stopping at the first
failure — never scored, and kept off competitors' history and the jury
console. The executor is the scripted fake from test_judge_submissions."""

from sqlalchemy import select

from db import SessionLocal
from models.judge import JUDGE_SETTINGS_ID, JudgeSettings
from models.judging import Judging
from models.submission import Submission
from tests.test_judge_submissions import (
    FakeExecutor,
    _accepted,
    _auth,
    _judge_all,
    _player,
    _setup,
    _submit,
    _verdict,
)
from utils.judge_executor import JudgeResult, JudgeTestResult

import main  # noqa: F401, E402

SOLUTION = "a, b = map(int, input().split())\nprint(a + b)\n"


def _url(comp, chal, path="/judge/reference"):
    return f"/api/competitions/{comp}/challenges/{chal}{path}"


def _check(client, token, comp, chal, **over):
    return client.post(
        _url(comp, chal), json={"language": "python3", "source": SOLUTION, **over}, headers=_auth(token)
    )


def _per_test(*verdicts):
    """Every test reported, as a run_all harness does."""

    def result(job):
        return JudgeResult(
            verdict=next((v for v in verdicts if v != "accepted"), "accepted"),
            tests=tuple(
                JudgeTestResult(index=i, sample=t.sample, verdict=verdicts[i], time_ms=5,
                                wall_ms=6, memory_kb=900, output="x")
                for i, t in enumerate(job.tests)
            ),
        )

    return result


async def test_an_author_checks_a_draft_problem_against_every_test(client, object_storage):
    admin, comp, chal = await _setup(client, publish=False)
    resp = await _check(client, admin, comp, chal)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["judging"]["kind"] == "reference" and body["judging"]["status"] == "queued"
    assert body["source"] == SOLUTION and body["language_key"] == "python3"

    executor = FakeExecutor(_per_test("accepted", "wrong_answer", "accepted"))
    await _judge_all(executor, object_storage)
    [job] = executor.jobs
    # Every test, examples and hidden, and the harness told not to stop early.
    assert job.run_all is True and len(job.tests) == 3

    check = (await client.get(_url(comp, chal), headers=_auth(admin))).json()
    judging = check["judging"]
    assert judging["status"] == "done" and judging["verdict"] == "wrong_answer"
    assert [t["verdict"] for t in judging["tests"]] == ["accepted", "wrong_answer", "accepted"]
    # The author sees time and memory on hidden tests too.
    assert all(t["time_ms"] is not None for t in judging["tests"])
    assert check["stale"] is False and check["run_by_name"]

    # Never scored.
    async with SessionLocal() as db:
        assert (await db.scalars(select(Submission))).all() == []


async def test_submissions_and_runs_still_stop_at_the_first_failure(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    await _submit(client, player, comp, chal)
    await _submit(client, player, comp, chal, kind="run")
    executor = FakeExecutor()
    await _judge_all(executor, object_storage)
    assert [job.run_all for job in executor.jobs] == [False, False]


async def test_the_check_goes_out_of_date_when_the_tests_change(client, object_storage):
    admin, comp, chal = await _setup(client)
    await _check(client, admin, comp, chal)
    await _judge_all(FakeExecutor(), object_storage)
    assert (await client.get(_url(comp, chal), headers=_auth(admin))).json()["stale"] is False

    problem = (await client.get(_url(comp, chal, "/judge"), headers=_auth(admin))).json()
    case = problem["testcases"][-1]["id"]
    resp = await client.patch(
        _url(comp, chal, f"/judge/testcases/{case}"), json={"answer": "42"}, headers=_auth(admin)
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get(_url(comp, chal), headers=_auth(admin))).json()["stale"] is True

    # So does changing a limit; running it again is current.
    await _check(client, admin, comp, chal)
    await _judge_all(FakeExecutor(), object_storage)
    assert (await client.get(_url(comp, chal), headers=_auth(admin))).json()["stale"] is False
    await client.put(_url(comp, chal, "/judge"), json={"time_limit_ms": 3000}, headers=_auth(admin))
    assert (await client.get(_url(comp, chal), headers=_auth(admin))).json()["stale"] is True


async def test_one_check_at_a_time_per_problem(client, object_storage):
    admin, comp, chal = await _setup(client)
    assert (await _check(client, admin, comp, chal)).status_code == 202
    again = await _check(client, admin, comp, chal)
    assert again.status_code == 409 and "already running" in again.json()["detail"]
    await _judge_all(FakeExecutor(), object_storage)
    assert (await _check(client, admin, comp, chal)).status_code == 202


async def test_the_check_needs_test_cases(client, object_storage):
    admin, comp, chal = await _setup(client, samples=0, secrets=0, publish=False)
    assert (await _check(client, admin, comp, chal)).status_code == 409


async def test_the_check_needs_a_language_a_source_and_the_judge(client, object_storage):
    admin, comp, chal = await _setup(client)
    assert (await _check(client, admin, comp, chal, language="cobol")).status_code == 400
    assert (await _check(client, admin, comp, chal, source="  \n")).status_code == 400
    async with SessionLocal() as db:
        (await db.get(JudgeSettings, JUDGE_SETTINGS_ID)).enabled = False
        await db.commit()
    assert (await _check(client, admin, comp, chal)).status_code == 503


async def test_only_authors_can_check_and_competitors_cant_ask_for_one(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    assert (await _check(client, player, comp, chal)).status_code == 403
    assert (await client.get(_url(comp, chal), headers=_auth(player))).status_code == 403
    # Judging every hidden test without stopping tells more than a submission
    # does, so the competitor route refuses the kind outright.
    resp = await _submit(client, player, comp, chal, kind="reference")
    assert resp.status_code == 422


async def test_a_check_stays_out_of_history_the_console_and_the_cap(client, object_storage):
    admin, comp, chal = await _setup(client)
    await _check(client, admin, comp, chal)
    await _judge_all(FakeExecutor(), object_storage)
    for _ in range(2):
        await _check(client, admin, comp, chal)
        await _judge_all(FakeExecutor(), object_storage)

    # While one waits, the console's own counts don't include it — only the
    # site-wide load does.
    await _check(client, admin, comp, chal)
    queue = (await client.get(f"/api/competitions/{comp}/judging-queue", headers=_auth(admin))).json()
    assert queue["queued"] == 0 and queue["site_queued"] == 1
    await _judge_all(FakeExecutor(), object_storage)

    mine = await client.get(
        f"/api/competitions/{comp}/challenges/{chal}/judgings", headers=_auth(admin)
    )
    assert mine.json() == []
    console = await client.get(f"/api/competitions/{comp}/judgings", headers=_auth(admin))
    assert console.json()["total"] == 0

    # Three checks queued at once (on three problems' worth of attempts) don't
    # use up the author's own submission allowance.
    async with SessionLocal() as db:
        for j in (await db.scalars(select(Judging))).all():
            j.status = "queued"
        await db.commit()
    assert (await _submit(client, admin, comp, chal)).status_code == 202


async def test_no_check_yet(client, object_storage):
    admin, comp, chal = await _setup(client)
    resp = await client.get(_url(comp, chal), headers=_auth(admin))
    assert resp.status_code == 200
    assert resp.json() == {
        "judging": None, "run_by_name": None, "language_key": None, "source": None, "stale": False,
    }


async def test_compile_errors_and_verdict_shapes(client, object_storage):
    admin, comp, chal = await _setup(client)
    await _check(client, admin, comp, chal)
    await _judge_all(
        FakeExecutor(JudgeResult(verdict="compile_error", compile_output="boom", tests=())),
        object_storage,
    )
    judging = (await client.get(_url(comp, chal), headers=_auth(admin))).json()["judging"]
    assert judging["verdict"] == "compile_error" and judging["compile_output"] == "boom"
    assert judging["tests"] == [] and judging["tests_total"] == 3
    assert _accepted and _verdict  # shared helpers stay importable
