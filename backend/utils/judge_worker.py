"""The code judge's worker loop and reaper (#448, ADR-0042 §2–§4).

Judging is driven by **its own loop, not the event bus**: the bus cancels every
handler after 10 seconds, background ones included, and a judging routinely
runs longer. The loop starts where the scheduler starts — in-process for a
single-worker deployment, in the ``python -m scheduler`` sidecar otherwise — so
one process judges (bar a rolling deploy's overlap, which the fencing below
makes safe). It polls every second (a submission in the same
process also wakes it at once) and runs up to ``max_concurrent_judgings`` at a
time (default 1, ADR-0042 §5).

**Claiming** is one conditional ``UPDATE … WHERE status = 'queued'`` checking
the row count, which also bumps ``attempts``. That attempt number is the
judging's *fencing token*: finishing is another conditional update that
requires the row still be ``running`` at the same attempt, so a worker that
lost its claim (the reaper reclaimed a stuck row and it was claimed again) can
never write a second result or a second award.

**Failure.** ``JudgeExecutorError`` (the runtime was unreachable, no result
came back) and the harness's own ``internal_error`` mean no verdict about the
submission, so the judging is retried — up to ``MAX_ATTEMPTS`` claims — then
recorded as ``failed`` / ``internal_error``. Nothing is ever awarded or
penalised for the judge's own failure.

**Awarding.** A ``submit`` judging that reaches a verdict is recorded through
the shared award path (``utils.grading``) as an ordinary ``Submission`` —
correct or not, as a flag attempt is — **backdated to when the code was
submitted**, so queueing never costs anyone first blood or a freeze cutoff.
``run`` judgings (examples only) are never recorded or scored.

**Stuck judgings.** A claim sets a deadline: the executor's own time budget for
the job, plus slack. ``reap_judgings`` (on the shared scheduler tick, like
``reap_instances``) reclaims anything still ``running`` past it, which is what
recovers from a worker killed mid-judging, and sweeps containers no live
judging owns. The worker runs the same pass as it starts. Only *overdue* rows
are ever reclaimed: normally one process judges, but two can overlap (a rolling
deploy starts the new process before stopping the old), and a judging inside
its deadline may be the other's.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, update

from db import utcnow
from models.challenge import Challenge
from models.competition import Competition
from models.judge import (
    DEFAULT_MEMORY_LIMIT_MB,
    DEFAULT_OUTPUT_LIMIT_KB,
    DEFAULT_TIME_LIMIT_MS,
    JUDGE_SETTINGS_ID,
    JudgeLanguage,
    JudgeSettings,
)
from models.judge_problem import DEFAULT_FLOAT_TOLERANCE, JudgeProblem
from models.judging import CodeSubmission, Judging, JudgingRun
from models.submission import Submission
from utils import judge_testdata as td
from utils.event_bus import event_bus
from utils.judge_executor import (
    JudgeExecutor,
    JudgeExecutorError,
    JudgeJob,
    JudgeResult,
    JudgeTest,
    executor_for,
    make_job,
)
from utils.grading import emit_grade, emit_regrade, record_grade, regrade
from utils.judge_live import push_judging
from utils.scoring import Subject

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 1.0
# How often to look while the judge is switched off (nothing can be queued
# then: the submit route refuses).
IDLE_POLL_INTERVAL_S = 15.0
MAX_ATTEMPTS = 3
# A claimed judging's deadline before its real budget is known (loading the
# test data and source happens after the claim).
CLAIM_GRACE = timedelta(minutes=5)
# On top of the executor's budget for the judging itself (compile + tests),
# what a run may spend around it: a cold image pull (up to 5 minutes), the
# container lifecycle calls (create/upload/start/logs/remove, about 4 more at
# worst), and a busy host. Too short, and a slow first pull of a big image
# gets reclaimed mid-run and judged twice.
DEADLINE_SLACK = timedelta(minutes=10)
# Bounds the reaper's work per tick.
REAP_BATCH = 50

_task: asyncio.Task | None = None
_wake: asyncio.Event | None = None
_running: set[asyncio.Task] = set()


def wake() -> None:
    """Nudge the in-process loop (a submission just arrived). A no-op when the
    worker runs in another process — it polls."""
    if _wake is not None:
        _wake.set()


def start(db_factory) -> None:
    """Launch the loop (idempotent). Requires a running event loop."""
    global _task, _wake
    if _task is not None and not _task.done():
        return
    _wake = asyncio.Event()
    _task = asyncio.ensure_future(_loop(db_factory))


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
    for task in list(_running):
        task.cancel()


async def _loop(db_factory) -> None:
    try:
        await recover(db_factory)
    except Exception:  # noqa: BLE001 — recovery failing must not stop judging
        logger.exception("judge worker start-up recovery failed")
    while True:
        enabled = True
        try:
            async with db_factory() as db:
                enabled = await _settings(db) is not None
            if enabled:
                await fill_slots(db_factory)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a bad pass must not kill the loop
            logger.exception("judge worker pass failed")
        try:
            await asyncio.wait_for(
                _wake.wait(), timeout=POLL_INTERVAL_S if enabled else IDLE_POLL_INTERVAL_S
            )
        except TimeoutError:
            pass
        _wake.clear()


async def _settings(db) -> JudgeSettings | None:
    settings = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
    return settings if settings is not None and settings.enabled else None


async def fill_slots(
    db_factory, *, executor: JudgeExecutor | None = None, storage=None
) -> list[asyncio.Task]:
    """Claim queued judgings up to the concurrency limit and start them."""
    async with db_factory() as db:
        settings = await _settings(db)
        if settings is None:
            return []
        capacity = max(1, settings.max_concurrent_judgings) - len(_running)
    started = []
    for _ in range(capacity):
        claim = await claim_next(db_factory)
        if claim is None:
            break
        task = asyncio.ensure_future(
            run_judging(db_factory, claim, executor=executor, storage=storage)
        )
        _running.add(task)
        task.add_done_callback(_finished)
        started.append(task)
    return started


def _finished(task: asyncio.Task) -> None:
    _running.discard(task)
    wake()  # a slot is free


@dataclass(frozen=True)
class Claim:
    judging_id: str
    attempt: int


async def claim_next(db_factory, *, now: datetime | None = None) -> Claim | None:
    """Atomically take the oldest queued judging, or None if there is none."""
    now = now or utcnow()
    async with db_factory() as db:
        candidates = (
            await db.scalars(
                select(Judging.id)
                .where(Judging.status == "queued")
                .order_by(Judging.created_at, Judging.id)
                .limit(5)
            )
        ).all()
        for judging_id in candidates:
            claimed = await db.execute(
                update(Judging)
                .where(Judging.id == judging_id, Judging.status == "queued")
                .values(
                    status="running",
                    claimed_at=now,
                    deadline_at=now + CLAIM_GRACE,
                    attempts=Judging.attempts + 1,
                )
            )
            if claimed.rowcount == 1:
                row = (
                    await db.execute(
                        select(
                            Judging.attempts, Judging.competition_id,
                            Judging.challenge_id, Judging.user_id,
                        ).where(Judging.id == judging_id)
                    )
                ).one()
                await db.commit()
                await push_judging(
                    competition_id=row.competition_id, challenge_id=row.challenge_id,
                    judging_id=judging_id, user_id=row.user_id, status="running",
                )
                return Claim(judging_id, row.attempts)
        return None


# --- one judging -------------------------------------------------------------------


async def run_judging(
    db_factory, claim: Claim, *, executor: JudgeExecutor | None = None, storage=None
) -> None:
    if storage is None:
        from storage import get_storage

        storage = get_storage()
    try:
        job, executor = await _prepare(db_factory, claim, storage, executor)
    except JudgeExecutorError as exc:
        await _give_up_or_retry(db_factory, claim, str(exc), retry=False)
        await _discard_run_source(db_factory, claim, storage)
        return
    except Exception as exc:  # noqa: BLE001 — storage hiccup etc.: retry
        logger.exception("preparing judging %s failed", claim.judging_id)
        await _give_up_or_retry(db_factory, claim, f"preparing the judging failed: {exc}")
        await _discard_run_source(db_factory, claim, storage)
        return
    if job is None:
        return  # lost the claim

    try:
        result = await executor.run(job)
    except JudgeExecutorError as exc:
        await _give_up_or_retry(db_factory, claim, str(exc))
        await _discard_run_source(db_factory, claim, storage)
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("judging %s failed", claim.judging_id)
        await _give_up_or_retry(db_factory, claim, f"the judge failed: {exc}")
        await _discard_run_source(db_factory, claim, storage)
        return

    if result.verdict == "internal_error":
        await _give_up_or_retry(db_factory, claim, result.error or "the judge reported an internal error")
        await _discard_run_source(db_factory, claim, storage)
        return
    if job.run_all and result.verdict != "compile_error" and len(result.tests) < len(job.tests):
        # The harness stopped early although asked not to: it predates #450.
        # The check still reports what ran; the missing tests show as not run.
        logger.warning(
            "judging %s: the judge harness ran %d of %d tests — rebuild it "
            "(make -C backend/judge_harness) for full reference checks",
            claim.judging_id, len(result.tests), len(job.tests),
        )
    try:
        await _finish(db_factory, claim, result, tests_total=len(job.tests))
    except Exception as exc:  # noqa: BLE001 — e.g. a lock timeout: retry, don't strand it
        logger.exception("recording judging %s failed", claim.judging_id)
        await _give_up_or_retry(db_factory, claim, f"recording the verdict failed: {exc}")
        return
    await _discard_run_source(db_factory, claim, storage)


async def _prepare(db_factory, claim: Claim, storage, executor) -> tuple[JudgeJob | None, JudgeExecutor]:
    """Load everything the job needs and push the deadline out to its budget.
    Raises ``JudgeExecutorError`` for a judging that can never run (its
    language or problem is gone) — those aren't retried."""
    async with db_factory() as db:
        judging = await db.get(Judging, claim.judging_id)
        if judging is None or judging.status != "running" or judging.attempts != claim.attempt:
            return None, executor
        settings = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
        if settings is None or not settings.enabled:
            raise JudgeExecutorError("the code judge has been turned off")
        code = await db.get(CodeSubmission, judging.code_submission_id)
        problem = await db.scalar(
            select(JudgeProblem).where(
                JudgeProblem.challenge_id == judging.challenge_id,
                JudgeProblem.competition_id == judging.competition_id,
            )
        )
        language = await db.scalar(
            select(JudgeLanguage).where(JudgeLanguage.key == code.language_key)
        )
        if problem is None or not problem.testcases:
            raise JudgeExecutorError("the problem has no test cases")
        if language is None or not language.enabled:
            raise JudgeExecutorError(f"the language {code.language_key!r} is no longer available")

        source = await asyncio.to_thread(storage.get, code.source_object_key)
        cases = await asyncio.to_thread(td.load, storage, problem.object_key, problem.testcases)
        if judging.kind == "run":
            cases = [c for c in cases if c.sample]
        if not cases:
            raise JudgeExecutorError("the problem has no tests to run")

        limits = effective_limits(problem, settings)
        job = make_job(
            judging_id=judging.id,
            image_ref=language.image_ref,
            source_filename=language.source_filename,
            source=source,
            compile_command=language.compile_command,
            run_command=language.run_command,
            time_multiplier=language.time_multiplier,
            time_limit_ms=limits["time_limit_ms"],
            memory_limit_mb=limits["memory_limit_mb"],
            output_limit_kb=limits["output_limit_kb"],
            compare_mode=limits["compare_mode"],
            float_tolerance=limits["float_tolerance"],
            case_insensitive=limits["case_insensitive"],
            tests=[JudgeTest(sample=c.sample, input=c.input, answer=c.answer) for c in cases],
            # An author's reference check reports every test (#450).
            run_all=judging.kind == "reference",
        )
        executor = executor or executor_for(settings)
        deadline = utcnow() + timedelta(seconds=executor.time_budget_s(job)) + DEADLINE_SLACK
        moved = await db.execute(
            update(Judging)
            .where(
                Judging.id == claim.judging_id,
                Judging.status == "running",
                Judging.attempts == claim.attempt,
            )
            .values(deadline_at=deadline, problem_version=problem_version(problem, settings))
        )
        if moved.rowcount != 1:
            return None, executor
        await db.commit()
        return job, executor


def effective_limits(problem: JudgeProblem, settings: JudgeSettings) -> dict:
    """The limits and output check a judging of this problem runs under: the
    problem's own, else the site defaults, else the built-in ones."""
    return {
        "time_limit_ms": problem.time_limit_ms or settings.default_time_limit_ms or DEFAULT_TIME_LIMIT_MS,
        "memory_limit_mb": problem.memory_limit_mb or settings.default_memory_limit_mb or DEFAULT_MEMORY_LIMIT_MB,
        "output_limit_kb": problem.output_limit_kb or settings.default_output_limit_kb or DEFAULT_OUTPUT_LIMIT_KB,
        "compare_mode": problem.compare_mode,
        "float_tolerance": problem.float_tolerance or DEFAULT_FLOAT_TOLERANCE,
        "case_insensitive": bool(problem.case_insensitive),
    }


def problem_version(problem: JudgeProblem, settings: JudgeSettings) -> str:
    """A short fingerprint of what a judging ran against: the test data (a new
    object key on every edit) and the limits. A reference check whose version
    differs from the problem's current one is out of date (#450)."""
    limits = effective_limits(problem, settings)
    if not limits["case_insensitive"]:
        # Added in #451: absent when off, so a problem that doesn't use it
        # keeps the fingerprint it had (no reference check goes stale).
        limits.pop("case_insensitive")
    basis = json.dumps({"testdata": problem.object_key, **limits}, sort_keys=True)
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def _fenced(claim: Claim):
    return (
        Judging.id == claim.judging_id,
        Judging.status == "running",
        Judging.attempts == claim.attempt,
    )


async def _discard_run_source(db_factory, claim: Claim, storage) -> None:
    """Drop the source of a finished examples-only run: a scratch try isn't
    history worth keeping, and storing every one would let a competitor fill
    storage at the rate limit. Scored submissions keep theirs."""
    async with db_factory() as db:
        judging = await db.get(Judging, claim.judging_id)
        if (
            judging is None
            or judging.kind != "run"
            or judging.status not in ("done", "failed")
            or judging.attempts != claim.attempt
        ):
            return
        code = await db.get(CodeSubmission, judging.code_submission_id)
        if code is None:
            return
        key = code.source_object_key
    try:
        await asyncio.to_thread(storage.delete, key)
    except Exception:  # noqa: BLE001 — an orphaned object is harmless
        logger.warning("couldn't delete the source of run %s", claim.judging_id)


async def _finish(db_factory, claim: Claim, result: JudgeResult, *, tests_total: int) -> None:
    async with db_factory() as db:
        judging = await db.get(Judging, claim.judging_id)
        if judging is None:
            return  # deleted mid-run (its challenge, competition or user went)
        finished = await db.execute(
            update(Judging)
            .where(*_fenced(claim))
            .values(
                status="done",
                verdict=result.verdict,
                finished_at=utcnow(),
                compile_output=result.compile_output or None,
                max_time_ms=result.max_time_ms,
                max_memory_kb=result.max_memory_kb,
                tests_passed=sum(1 for t in result.tests if t.verdict == "accepted"),
                # What this judging ran against — the problem's test cases may
                # have been edited since.
                tests_total=tests_total,
                error=None,
            )
        )
        if finished.rowcount != 1:
            await db.rollback()
            return  # the claim was lost: someone else owns this judging now
        for t in result.tests:
            db.add(
                JudgingRun(
                    competition_id=judging.competition_id,
                    judging_id=judging.id,
                    test_index=t.index,
                    sample=t.sample,
                    verdict=t.verdict,
                    time_ms=t.time_ms,
                    wall_ms=t.wall_ms,
                    memory_kb=t.memory_kb,
                    exit_code=t.exit_code,
                    signal=t.signal,
                    output=t.output,
                )
            )

        recorded = None
        if judging.kind == "submit":
            recorded = await record_verdict(db, judging, result.verdict)
        await db.commit()

        await _emit_completed(judging, result.verdict)
        await emit_recorded(recorded, judging)


async def _is_latest_finished(db, judging: Judging) -> bool:
    """Whether this is the newest finished judging of its code submission —
    the one whose verdict counts. An older rejudge finishing after a newer one
    (or after a judge's override) must not overturn it."""
    newer = await db.scalar(
        select(func.count(Judging.id)).where(
            Judging.code_submission_id == judging.code_submission_id,
            Judging.status == "done",
            Judging.id != judging.id,
            or_(
                Judging.created_at > judging.created_at,
                and_(Judging.created_at == judging.created_at, Judging.id > judging.id),
            ),
        )
    )
    return not newer


async def record_verdict(db, judging: Judging, verdict: str):
    """Make a scored judging's verdict the code submission's score: the first
    time, through the shared award path (``record_grade``), backdated to the
    code's submission time; after a rejudge or override, by updating that same
    row and reconciling the award (``regrade``). Returns what to emit after the
    commit, or None when nothing changed (not the latest verdict, or nobody to
    credit). Doesn't commit.

    Serialised per challenge: recording a verdict reads the subject's rows and
    re-values every award on the challenge, so two at once (concurrent
    judgings, an override racing the worker) could deadlock, both promote an
    award, or both create the code submission's row. Everything below runs
    under a lock on the challenge row — ``FOR NO KEY UPDATE``, which doesn't
    conflict with the key-share locks inserts referencing the challenge take —
    and re-reads what it decides on, so a decision made by a session that
    committed while this one waited is seen, not overwritten from stale state.
    """
    await db.execute(
        select(Challenge.id)
        .where(Challenge.id == judging.challenge_id)
        .with_for_update(key_share=True)
    )
    if not await _is_latest_finished(db, judging):
        return None
    competition = await db.get(Competition, judging.competition_id)
    challenge = await db.get(Challenge, judging.challenge_id)
    code = await db.get(CodeSubmission, judging.code_submission_id, populate_existing=True)
    if competition is None or challenge is None or code is None:
        return None
    correct = verdict == "accepted"
    row = (
        await db.get(Submission, code.submission_id, populate_existing=True)
        if code.submission_id
        else None
    )
    if row is None:
        if competition.participation_mode == "team":
            if judging.team_id is None:
                return None  # the team was deleted: nobody left to credit
            subject = Subject(kind="team", id=judging.team_id, team_id=judging.team_id)
        else:
            subject = Subject(kind="user", id=judging.user_id, team_id=None)
        grade = await record_grade(
            db,
            competition=competition,
            challenge=challenge,
            subject=subject,
            user_id=judging.user_id,
            value=f"code:{code.id}",
            correct=correct,
            created_at=code.created_at,
        )
        await db.flush()
        code.submission_id = judging.submission_id = grade.submission.id
        moved = None
        if grade.submission.is_correct and grade.submission.is_duplicate:
            # Correct, but the subject already held the award — on a later
            # submission than this backdated one, possibly. The earliest
            # correct submission holds it, so reconcile.
            moved = await regrade(
                db, competition=competition, challenge=challenge, subject=subject,
                row=grade.submission, correct=True,
            )
        return ("graded", grade, moved)
    # Re-verdict: the subject is whoever the row credits — the key the
    # awarded-row index uses — not the competition's current mode, which an
    # organiser may have switched since.
    subject = (
        Subject(kind="team", id=row.team_id, team_id=row.team_id)
        if row.team_id
        else Subject(kind="user", id=row.user_id, team_id=None)
    )
    outcome = await regrade(
        db, competition=competition, challenge=challenge, subject=subject, row=row, correct=correct
    )
    judging.submission_id = row.id
    return ("regraded", outcome, None)


async def emit_recorded(recorded, judging: Judging) -> None:
    """The scoring events for a committed record_verdict."""
    if recorded is None:
        return
    kind, result, moved = recorded
    ids = dict(
        competition_id=judging.competition_id,
        challenge_id=judging.challenge_id,
        user_id=judging.user_id,
        team_id=judging.team_id,
    )
    if kind == "graded":
        await emit_grade(result, **ids)
        if moved is not None:
            await emit_regrade(moved, **ids)
    else:
        await emit_regrade(result, **ids)


async def _give_up_or_retry(db_factory, claim: Claim, error: str, *, retry: bool = True) -> None:
    """No verdict this time: back to the queue while attempts remain, otherwise
    failed. Fenced like _finish, so a lost claim changes nothing."""
    async with db_factory() as db:
        judging = await db.get(Judging, claim.judging_id)
        if judging is None:
            return
        if retry and claim.attempt < MAX_ATTEMPTS:
            values = {"status": "queued", "claimed_at": None, "deadline_at": None, "error": error[:2000]}
        else:
            values = {
                "status": "failed",
                "verdict": "internal_error",
                "finished_at": utcnow(),
                "error": error[:2000],
            }
        changed = await db.execute(update(Judging).where(*_fenced(claim)).values(**values))
        if changed.rowcount != 1:
            await db.rollback()
            return
        await db.commit()
        logger.warning(
            "judging %s attempt %d: %s (%s)",
            claim.judging_id, claim.attempt, error, values["status"],
        )
        if values["status"] == "failed":
            await _emit_completed(judging, "internal_error")
        else:
            await push_judging(
                competition_id=judging.competition_id, challenge_id=judging.challenge_id,
                judging_id=judging.id, user_id=judging.user_id, status="queued",
            )


async def _emit_completed(judging: Judging, verdict: str) -> None:
    await push_judging(
        competition_id=judging.competition_id,
        challenge_id=judging.challenge_id,
        judging_id=judging.id,
        user_id=judging.user_id,
        status="failed" if verdict == "internal_error" else "done",
        verdict=verdict,
    )
    await event_bus.emit(
        "judging.completed",
        {
            "competition_id": judging.competition_id,
            "challenge_id": judging.challenge_id,
            "judging_id": judging.id,
            "user_id": judging.user_id,
            "team_id": judging.team_id,
            "kind": judging.kind,
            "verdict": verdict,
        },
    )


# --- recovery -------------------------------------------------------------------------


async def _reclaim(db_factory, *, now: datetime) -> int:
    """Return judgings running past their deadline to the queue — or fail them,
    out of attempts. Only rows this pass actually changed count (and only those
    are reported failed): a worker can finish a judging between our read and
    our update, and then it isn't stuck at all."""
    reclaimed = 0
    while True:
        async with db_factory() as db:
            stuck = (
                await db.scalars(
                    select(Judging)
                    .where(Judging.status == "running", Judging.deadline_at < now)
                    .limit(REAP_BATCH)
                )
            ).all()
            failed: list[Judging] = []
            for judging in stuck:
                claim = Claim(judging.id, judging.attempts)
                give_up = judging.attempts >= MAX_ATTEMPTS
                values = (
                    {
                        "status": "failed",
                        "verdict": "internal_error",
                        "finished_at": now,
                        "error": "the judge stopped responding while judging this",
                    }
                    if give_up
                    else {"status": "queued", "claimed_at": None, "deadline_at": None}
                )
                changed = await db.execute(update(Judging).where(*_fenced(claim)).values(**values))
                if changed.rowcount == 1:
                    reclaimed += 1
                    if give_up:
                        failed.append(judging)
            await db.commit()
        for judging in failed:
            await _emit_completed(judging, "internal_error")
        if len(stuck) < REAP_BATCH:
            return reclaimed


async def _sweep_containers(db_factory, executor: JudgeExecutor | None, now: datetime) -> int:
    """Remove judge containers nobody is waiting on — left behind by a worker
    that died mid-judging. Every judging still running inside its deadline is
    kept, whichever process runs it."""
    async with db_factory() as db:
        settings = await _settings(db)
        if settings is None:
            return 0
        live = set(
            (
                await db.scalars(
                    select(Judging.id).where(
                        Judging.status == "running", Judging.deadline_at >= now
                    )
                )
            ).all()
        )
    try:
        return await (executor or executor_for(settings)).cleanup(keep=live)
    except JudgeExecutorError as exc:
        logger.warning("judge container cleanup failed: %s", exc)
        return 0


async def reap_judgings(
    db_factory, *, now: datetime | None = None, executor: JudgeExecutor | None = None
) -> int:
    """Scheduler-tick step: reclaim judgings stuck past their deadline — the
    worker died mid-judging, or the runtime hung — and remove containers left
    behind. A cheap no-op when nothing is running."""
    now = now or utcnow()
    reclaimed = await _reclaim(db_factory, now=now)
    await _sweep_containers(db_factory, executor, now)
    return reclaimed


async def recover(db_factory, *, executor: JudgeExecutor | None = None) -> None:
    """Worker start-up: the reaper's pass, at once rather than on the next
    tick. Deliberately only for judgings past their deadline: another process
    may still be judging the rest — during a rolling deploy, the old one — and
    deadline-based reclaiming is what keeps two workers from judging the same
    thing (fencing keeps the score right even if they do)."""
    reclaimed = await reap_judgings(db_factory, executor=executor)
    if reclaimed:
        logger.info("judge worker reclaimed %d interrupted judging(s)", reclaimed)
