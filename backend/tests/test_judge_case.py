"""Ignoring letter case (#451): a per-problem setting — the standard ICPC/Kattis
checker's default — carried to the harness on every job, part of the problem's
version fingerprint, and kept through clone and backup. Existing problems stay
case-sensitive."""

from db import SessionLocal
from models.judge_problem import JudgeProblem
from sqlalchemy import select
from tests.test_judge_submissions import FakeExecutor, _auth, _judge_all, _player, _setup, _submit
from utils.judge_worker import problem_version

import main  # noqa: F401, E402


def _base(comp, chal):
    return f"/api/competitions/{comp}/challenges/{chal}/judge"


async def _problem(chal) -> JudgeProblem:
    async with SessionLocal() as db:
        return await db.scalar(select(JudgeProblem).where(JudgeProblem.challenge_id == chal))


async def test_off_by_default_and_settable(client, object_storage):
    admin, comp, chal = await _setup(client)
    body = (await client.get(_base(comp, chal), headers=_auth(admin))).json()
    assert body["case_insensitive"] is False
    resp = await client.put(_base(comp, chal), json={"case_insensitive": True}, headers=_auth(admin))
    assert resp.status_code == 200 and resp.json()["case_insensitive"] is True
    # Omitting it leaves it alone.
    resp = await client.put(_base(comp, chal), json={"time_limit_ms": 3000}, headers=_auth(admin))
    assert resp.json()["case_insensitive"] is True


async def test_the_job_carries_it(client, object_storage):
    admin, comp, chal = await _setup(client)
    player = await _player(client, comp)
    await _submit(client, player, comp, chal)
    await client.put(_base(comp, chal), json={"case_insensitive": True}, headers=_auth(admin))
    await _submit(client, player, comp, chal)
    executor = FakeExecutor()
    await _judge_all(executor, object_storage)
    # Judged in order: the first was queued before the change but is judged
    # under the problem as it is at judging time — like any limit.
    assert [job.case_insensitive for job in executor.jobs] == [True, True]


async def test_it_changes_the_problem_version(client, object_storage):
    from models.judge import JUDGE_SETTINGS_ID, JudgeSettings

    admin, comp, chal = await _setup(client)
    async with SessionLocal() as db:
        settings = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
        before = problem_version(await _problem(chal), settings)
    await client.put(_base(comp, chal), json={"case_insensitive": True}, headers=_auth(admin))
    async with SessionLocal() as db:
        settings = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
        after = problem_version(await _problem(chal), settings)
    assert before != after


async def test_clone_keeps_it(client, object_storage):
    admin, comp, chal = await _setup(client)
    await client.put(_base(comp, chal), json={"case_insensitive": True}, headers=_auth(admin))
    clone = (
        await client.post(f"/api/competitions/{comp}/clone", json={"name": "Copy"}, headers=_auth(admin))
    ).json()
    new_chal = (
        await client.get(f"/api/competitions/{clone['id']}/challenges", headers=_auth(admin))
    ).json()[0]["id"]
    assert (await _problem(new_chal)).case_insensitive is True


async def test_backup_validates_it():
    import pytest

    from utils.backup import ImportError_, _validate_judge_problem_row

    row = {"id": "x", "competition_id": "c", "challenge_id": "p", "compare_mode": "token",
           "testcases": [], "object_key": None, "case_insensitive": "yes"}
    with pytest.raises(ImportError_):
        _validate_judge_problem_row(row)
    row["case_insensitive"] = True
    _validate_judge_problem_row(row)


async def test_problems_that_dont_use_it_keep_their_fingerprint(client, object_storage):
    """Adding the setting mustn't make every existing reference check look out
    of date: off, it isn't part of the fingerprint at all."""
    import hashlib
    import json

    from models.judge import JUDGE_SETTINGS_ID, JudgeSettings
    from utils.judge_worker import effective_limits

    admin, comp, chal = await _setup(client)
    async with SessionLocal() as db:
        settings = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
        problem = await _problem(chal)
        limits = effective_limits(problem, settings)
        limits.pop("case_insensitive")
        before_451 = hashlib.sha256(
            json.dumps({"testdata": problem.object_key, **limits}, sort_keys=True).encode()
        ).hexdigest()[:16]
        assert problem_version(problem, settings) == before_451
