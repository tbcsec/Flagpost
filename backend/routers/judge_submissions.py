"""Submitting code and reading judgings (#448, ADR-0042).

``POST …/submit-code`` is the code judge's counterpart to the flag submit
route, and runs the same gates in the same order — visibility,
``require_playable``, pause, the scoring subject, prerequisites, the shared
per-subject rate limiter — plus what code needs: the judge must be on, the
language allowed, the source within ``MAX_SOURCE_BYTES``, and the subject under
``MAX_IN_FLIGHT`` unfinished judgings (judging is the expensive part, so one
competitor can't fill the queue). It stores the source in object storage,
queues a judging, commits, then emits ``judging.queued`` — it never runs code:
the worker (``utils/judge_worker``) does.

Reads are by ownership: a competitor sees their own judgings — or, in team
mode, their team's — with per-test detail for the examples only. Staff with
``judging_view`` see every judging, the internal error included.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission, user_has_permission
from config import settings as app_settings
from db import get_db
from models.competition import Competition
from models.judge import (
    DEFAULT_MEMORY_LIMIT_MB,
    DEFAULT_OUTPUT_LIMIT_KB,
    DEFAULT_TIME_LIMIT_MS,
    JUDGE_SETTINGS_ID,
    JudgeLanguage,
    JudgeSettings,
)
from models.judge_problem import JudgeProblem
from models.judging import ACTIVE_JUDGING_STATUSES, CodeSubmission, Judging, JudgingRun
from models.user import User
from plugins.loader import is_module_enabled
from ratelimit import get_rate_limiter
from ratelimit.base import RateLimiter
from routers.challenges import load_visible_challenge
from schemas.judge import (
    CodeSourceOut,
    CodeSubmitRequest,
    JudgingOut,
    JudgingRunOut,
    ProblemExampleOut,
    ProblemLanguageOut,
    ProblemOut,
)
from storage import get_storage
from storage.base import ObjectStorage
from utils import judge_testdata as td
from utils import judge_worker
from utils.competition_status import require_playable
from utils.event_bus import event_bus
from utils.grading import lock_subject
from utils.judge_live import push_judging
from utils.scoring import resolve_subject, solved_challenge_ids

router = APIRouter(prefix="/api/competitions/{competition_id}", tags=["judgings"])

# Generous for contest code (a long C++ template library is ~50 KB), bounded so
# a submission can't be used to store files.
MAX_SOURCE_BYTES = 128 * 1024
# Unfinished judgings per subject.
MAX_IN_FLIGHT = 3
HISTORY_LIMIT = 50


async def _competition_with_judge(db: AsyncSession, competition_id: str) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Competition not found")
    if not await is_module_enabled(db, "judge", competition_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "The code judge module is turned off for this competition",
        )
    return competition


def _source_key(competition_id: str, challenge_id: str) -> str:
    return f"{competition_id}/judge-src/{challenge_id}/{uuid4().hex}"


async def _queue_position(db: AsyncSession, judging: Judging) -> int | None:
    if judging.status != "queued":
        return None
    # Deliberately NOT scoped to the competition (§6.2's one exception here):
    # the judge is one site-wide queue, so a judging's place depends on every
    # competition's queued judgings. Only a count leaves this query.
    ahead = await db.scalar(
        select(func.count(Judging.id)).where(
            Judging.status == "queued",
            or_(
                Judging.created_at < judging.created_at,
                and_(Judging.created_at == judging.created_at, Judging.id < judging.id),
            ),
        )
    )
    return (ahead or 0) + 1


async def _out(db: AsyncSession, judging: Judging, *, staff: bool) -> JudgingOut:
    code = await db.get(CodeSubmission, judging.code_submission_id)
    runs = (
        await db.scalars(
            select(JudgingRun)
            .where(JudgingRun.judging_id == judging.id)
            .order_by(JudgingRun.test_index)
        )
    ).all()
    # A competitor sees time and memory for examples only — per test *and* in
    # the judging's maxima, or the maxima would carry what the hidden tests
    # took (and so what the program saw in them).
    shown = runs if staff else [r for r in runs if r.sample]
    tests = [
        JudgingRunOut(
            index=r.test_index,
            sample=r.sample,
            verdict=r.verdict,
            time_ms=r.time_ms if (staff or r.sample) else None,
            memory_kb=r.memory_kb if (staff or r.sample) else None,
            output=r.output if r.sample else None,
        )
        for r in runs
    ]
    return JudgingOut(
        id=judging.id,
        challenge_id=judging.challenge_id,
        user_id=judging.user_id,
        team_id=judging.team_id,
        kind=judging.kind,
        language_key=code.language_key,
        language_name=code.language_name,
        status=judging.status,
        verdict=judging.verdict,
        queue_position=await _queue_position(db, judging),
        created_at=judging.created_at,
        finished_at=judging.finished_at,
        compile_output=judging.compile_output,
        max_time_ms=(
            judging.max_time_ms if staff else max((r.time_ms for r in shown), default=None)
        ),
        max_memory_kb=(
            judging.max_memory_kb if staff else max((r.memory_kb for r in shown), default=None)
        ),
        tests_passed=judging.tests_passed,
        tests_total=judging.tests_total,
        tests=tests,
        error=judging.error if staff else None,
    )


async def _visible_judging(
    db: AsyncSession, competition: Competition, judging_id: str, user: User
) -> tuple[Judging, bool]:
    """The judging if this user may read it, and whether they read it as staff.
    Anything else is the same 404, so ids can't be probed."""
    judging = await db.scalar(
        select(Judging).where(
            Judging.id == judging_id, Judging.competition_id == competition.id
        )
    )
    if judging is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Judging not found")
    if await user_has_permission(db, user.id, "judging_view", competition.id):
        return judging, True
    if judging.user_id == user.id:
        return judging, False
    subject = await resolve_subject(db, competition, user)
    if subject is not None and subject.team_id and judging.team_id == subject.team_id:
        return judging, False
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Judging not found")


# --- submit ----------------------------------------------------------------------------


@router.post(
    "/challenges/{challenge_id}/submit-code",
    response_model=JudgingOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_code(
    competition_id: str,
    challenge_id: str,
    body: CodeSubmitRequest,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> JudgingOut:
    competition = await _competition_with_judge(db, competition_id)
    challenge = await load_visible_challenge(db, competition_id, challenge_id, current_user)
    if challenge.flag_type != "programming":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This challenge is solved with a flag, not code"
        )
    judge = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
    if judge is None or not judge.enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The code judge isn't running right now — try again shortly",
        )

    # Competition status gate (#221), then pause (staff bypass) — the flag
    # route's order, so the clearer "hasn't started / has ended" wins.
    await require_playable(db, competition, current_user.id)
    if competition.paused and not await user_has_permission(
        db, current_user.id, "challenge_edit", competition_id
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The competition is paused — submissions are closed",
        )

    subject = await resolve_subject(db, competition, current_user)
    if subject is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Join a team before submitting code")

    prereqs = list(challenge.prerequisites or [])
    if prereqs:
        solved = await solved_challenge_ids(db, competition_id, subject)
        if any(pid not in solved for pid in prereqs):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Solve this challenge's prerequisites first"
            )

    problem = await db.scalar(
        select(JudgeProblem).where(
            JudgeProblem.challenge_id == challenge_id,
            JudgeProblem.competition_id == competition_id,
        )
    )
    if problem is None or not problem.testcases:
        raise HTTPException(status.HTTP_409_CONFLICT, "This problem has no test cases yet")
    if body.kind == "run" and not any(t.get("sample") for t in problem.testcases):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This problem has no examples to run against"
        )

    language = await db.scalar(
        select(JudgeLanguage).where(
            JudgeLanguage.key == body.language, JudgeLanguage.enabled.is_(True)
        )
    )
    if language is None or (
        problem.allowed_languages is not None and body.language not in problem.allowed_languages
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That language isn't available for this problem"
        )

    source = body.source.encode("utf-8")
    if not source.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The source is empty")
    if len(source) > MAX_SOURCE_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Source code is limited to {MAX_SOURCE_BYTES // 1024} KB",
        )

    # The same per-subject throttle as flags, so alternating between the two
    # doesn't double the allowance.
    allowed = await rate_limiter.hit(
        f"submit:{competition_id}:{subject.kind}:{subject.id}",
        limit=app_settings.submission_rate_limit,
        window_seconds=app_settings.submission_rate_window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many submissions — slow down and try again shortly",
        )
    subject_filter = (
        Judging.team_id == subject.team_id if subject.kind == "team" else Judging.user_id == subject.id
    )
    # Serialise this subject's submissions so a burst can't all read the same
    # count and all pass the cap (the flag route's guess-cap lock).
    await lock_subject(db, subject)
    in_flight = await db.scalar(
        select(func.count(Judging.id)).where(
            Judging.competition_id == competition_id,
            Judging.status.in_(ACTIVE_JUDGING_STATUSES),
            subject_filter,
        )
    )
    if (in_flight or 0) >= MAX_IN_FLIGHT:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"You already have {MAX_IN_FLIGHT} submissions waiting to be judged — "
            "wait for a verdict first",
        )

    key = _source_key(competition_id, challenge_id)
    await asyncio.to_thread(storage.put, key, source, "text/plain; charset=utf-8")
    try:
        code = CodeSubmission(
            competition_id=competition_id,
            challenge_id=challenge_id,
            user_id=current_user.id,
            team_id=subject.team_id,
            kind=body.kind,
            language_key=language.key,
            language_name=language.name,
            source_object_key=key,
            source_bytes=len(source),
        )
        db.add(code)
        await db.flush()
        judging = Judging(
            competition_id=competition_id,
            code_submission_id=code.id,
            challenge_id=challenge_id,
            user_id=current_user.id,
            team_id=subject.team_id,
            kind=body.kind,
            status="queued",
        )
        db.add(judging)
        await db.commit()
    except BaseException:
        try:
            await asyncio.shield(asyncio.to_thread(storage.delete, key))
        except Exception:  # noqa: BLE001 — never mask the original failure
            pass
        raise

    await event_bus.emit(
        "judging.queued",
        {
            "competition_id": competition_id,
            "challenge_id": challenge_id,
            "judging_id": judging.id,
            "user_id": current_user.id,
            "team_id": subject.team_id,
            "kind": body.kind,
        },
    )
    await push_judging(
        competition_id=competition_id, challenge_id=challenge_id,
        judging_id=judging.id, user_id=current_user.id, status="queued",
    )
    judge_worker.wake()
    return await _out(db, judging, staff=False)


# --- the problem, as a competitor sees it -------------------------------------------------

# Example text shown on the problem page; larger examples are cut (their full
# data is still what judging uses).
EXAMPLE_DISPLAY_BYTES = 16 * 1024


def _display_text(blob: bytes) -> tuple[str, bool]:
    cut = len(blob) > EXAMPLE_DISPLAY_BYTES
    text = blob[:EXAMPLE_DISPLAY_BYTES].decode("utf-8", errors="replace")
    return text, cut or "\ufffd" in text


@router.get("/challenges/{challenge_id}/problem", response_model=ProblemOut)
async def get_problem_view(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> ProblemOut:
    competition = await _competition_with_judge(db, competition_id)
    challenge = await load_visible_challenge(db, competition_id, challenge_id, current_user)
    if challenge.flag_type != "programming":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This isn't a programming challenge")
    # Same gate as reading a challenge (get_challenge): competitors see
    # problems only while the competition is running.
    await require_playable(db, competition, current_user.id)

    judge = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
    problem = await db.scalar(
        select(JudgeProblem).where(
            JudgeProblem.challenge_id == challenge_id,
            JudgeProblem.competition_id == competition_id,
        )
    )
    defaults = judge or JudgeSettings()
    time_limit = (problem and problem.time_limit_ms) or defaults.default_time_limit_ms or DEFAULT_TIME_LIMIT_MS
    languages = (
        await db.scalars(
            select(JudgeLanguage).where(JudgeLanguage.enabled.is_(True)).order_by(JudgeLanguage.name)
        )
    ).all()
    allowed = problem.allowed_languages if problem else None
    examples: list[ProblemExampleOut] = []
    if problem is not None and any(t.get("sample") for t in problem.testcases or []):
        cases = await asyncio.to_thread(td.load, storage, problem.object_key, problem.testcases)
        for i, case in enumerate(c for c in cases if c.sample):
            shown_in, cut_in = _display_text(case.input)
            shown_ans, cut_ans = _display_text(case.answer)
            examples.append(
                ProblemExampleOut(index=i, input=shown_in, answer=shown_ans, truncated=cut_in or cut_ans)
            )
    return ProblemOut(
        time_limit_ms=time_limit,
        memory_limit_mb=(problem and problem.memory_limit_mb) or defaults.default_memory_limit_mb or DEFAULT_MEMORY_LIMIT_MB,
        output_limit_kb=(problem and problem.output_limit_kb) or defaults.default_output_limit_kb or DEFAULT_OUTPUT_LIMIT_KB,
        compare_mode=problem.compare_mode if problem else "token",
        float_tolerance=problem.float_tolerance if problem else None,
        languages=[
            ProblemLanguageOut(
                key=lang.key,
                name=lang.name,
                extension=PurePosixPath(lang.source_filename).suffix.lower(),
                time_limit_ms=max(1, math.ceil(time_limit * lang.time_multiplier)),
            )
            for lang in languages
            if allowed is None or lang.key in allowed
        ],
        examples=examples,
        judge_ready=bool(judge and judge.enabled),
    )


# --- read ------------------------------------------------------------------------------


@router.get("/judgings/{judging_id}", response_model=JudgingOut)
async def get_judging(
    competition_id: str,
    judging_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> JudgingOut:
    competition = await _competition_with_judge(db, competition_id)
    judging, staff = await _visible_judging(db, competition, judging_id, current_user)
    return await _out(db, judging, staff=staff)


@router.get("/judgings/{judging_id}/source", response_model=CodeSourceOut)
async def get_judging_source(
    competition_id: str,
    judging_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> CodeSourceOut:
    competition = await _competition_with_judge(db, competition_id)
    judging, _staff = await _visible_judging(db, competition, judging_id, current_user)
    code = await db.get(CodeSubmission, judging.code_submission_id)
    if code.kind == "run":
        # Examples-only runs are scratch: their source is dropped once judged.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The source of a run isn't kept")
    data = await asyncio.to_thread(storage.get, code.source_object_key)
    return CodeSourceOut(
        language_key=code.language_key, source=data.decode("utf-8", "replace")
    )


@router.get("/challenges/{challenge_id}/judgings", response_model=list[JudgingOut])
async def list_my_judgings(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[JudgingOut]:
    """This subject's judgings of a challenge, newest first — the competitor's
    submission history (a team sees the team's)."""
    competition = await _competition_with_judge(db, competition_id)
    await load_visible_challenge(db, competition_id, challenge_id, current_user)
    subject = await resolve_subject(db, competition, current_user)
    owner = (
        Judging.team_id == subject.team_id
        if subject is not None and subject.kind == "team"
        else Judging.user_id == current_user.id
    )
    judgings = (
        await db.scalars(
            select(Judging)
            .where(
                Judging.competition_id == competition_id,
                Judging.challenge_id == challenge_id,
                owner,
            )
            .order_by(Judging.created_at.desc(), Judging.id.desc())
            .limit(HISTORY_LIMIT)
        )
    ).all()
    staff = await user_has_permission(db, current_user.id, "judging_view", competition_id)
    return [await _out(db, j, staff=staff) for j in judgings]
