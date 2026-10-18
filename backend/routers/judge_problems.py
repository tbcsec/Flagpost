"""Programming challenges — problem authoring (#447, ADR-0042).

Competition-scoped, under ``challenge_edit``, and only while the ``judge``
module is enabled for the competition. A programming challenge's statement is
its ordinary rich-text description; this router adds what's specific to it:
test cases (paste or upload) and the optional limits / comparison / language
overrides, every one of which defaults sensibly when left alone.

Test data lives in one zip per problem (``models/judge_problem.py``). Every
edit goes through ``_rewrite``: lock the problem row, load the zip, apply the
change, store the new zip under a fresh key, commit, *then* delete the old
object — so a failure at any point leaves the row pointing at a complete zip.

``GET /judge/status`` tells authors (and, in #449, competitors) whether
programming challenges are available here and in which languages.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from collections.abc import Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
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
from models.judging import ACTIVE_JUDGING_STATUSES, CodeSubmission, Judging
from models.user import User
from plugins.loader import is_module_enabled
from routers.challenges import _get_scoped_challenge
from routers.judge_submissions import (
    _out as judging_out,
    available_language,
    checked_source,
    queue_code,
)
from schemas.judge import (
    JudgeProblemOut,
    JudgeProblemUpdate,
    JudgeStatusOut,
    JudgeTestcaseContent,
    JudgeTestcaseCreate,
    JudgeTestcaseOut,
    JudgeTestcaseUpdate,
    PackageImportOut,
    ReferenceCheckOut,
    ReferenceCheckRequest,
)
from storage import get_storage
from storage.base import ObjectStorage
from utils import judge_testdata as td
from utils.event_bus import event_bus
from utils.judge_worker import problem_version
from utils.uploads import read_upload_capped

router = APIRouter(prefix="/api/competitions/{competition_id}", tags=["judge-problems"])

_PREVIEW_CHARS = 160
# Past this, a test case is listed and judged as normal but not offered for
# in-place editing (a textarea isn't the tool for megabytes of input).
_EDITABLE_BYTES = 256 * 1024


async def _guard(db: AsyncSession, competition_id: str) -> None:
    if await db.get(Competition, competition_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Competition not found")
    if not await is_module_enabled(db, "judge", competition_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "The code judge module is turned off for this competition",
        )


async def _programming_challenge(
    db: AsyncSession, competition_id: str, challenge_id: str
) -> Challenge:
    await _guard(db, competition_id)
    challenge = await _get_scoped_challenge(db, competition_id, challenge_id)
    if challenge.flag_type != "programming":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This isn't a programming challenge."
        )
    return challenge


async def _problem(db: AsyncSession, challenge: Challenge) -> JudgeProblem | None:
    return await db.scalar(
        select(JudgeProblem).where(
            JudgeProblem.challenge_id == challenge.id,
            JudgeProblem.competition_id == challenge.competition_id,
        )
    )


async def _problem_or_create(db: AsyncSession, challenge: Challenge) -> JudgeProblem:
    problem = await _problem(db, challenge)
    if problem is None:
        problem = JudgeProblem(
            competition_id=challenge.competition_id, challenge_id=challenge.id
        )
        db.add(problem)
        await db.commit()
        await db.refresh(problem)
    return problem


async def _site_defaults(db: AsyncSession) -> JudgeSettings:
    return await db.get(JudgeSettings, JUDGE_SETTINGS_ID) or JudgeSettings()


def _preview(blob: bytes) -> str:
    return blob[: _PREVIEW_CHARS * 4].decode("utf-8", errors="replace")[:_PREVIEW_CHARS]


async def _out(
    db: AsyncSession, storage: ObjectStorage, problem: JudgeProblem | None
) -> JudgeProblemOut:
    defaults = await _site_defaults(db)
    cases = (
        await asyncio.to_thread(td.load, storage, problem.object_key, problem.testcases)
        if problem is not None
        else []
    )
    return JudgeProblemOut(
        time_limit_ms=problem.time_limit_ms if problem else None,
        memory_limit_mb=problem.memory_limit_mb if problem else None,
        output_limit_kb=problem.output_limit_kb if problem else None,
        compare_mode=problem.compare_mode if problem else "token",
        float_tolerance=problem.float_tolerance if problem else None,
        case_insensitive=problem.case_insensitive if problem else False,
        allowed_languages=problem.allowed_languages if problem else None,
        testcases=[
            JudgeTestcaseOut(
                id=c.id,
                sample=c.sample,
                input_bytes=len(c.input),
                answer_bytes=len(c.answer),
                input_preview=_preview(c.input),
                answer_preview=_preview(c.answer),
            )
            for c in cases
        ],
        default_time_limit_ms=defaults.default_time_limit_ms or DEFAULT_TIME_LIMIT_MS,
        default_memory_limit_mb=defaults.default_memory_limit_mb or DEFAULT_MEMORY_LIMIT_MB,
        default_output_limit_kb=defaults.default_output_limit_kb or DEFAULT_OUTPUT_LIMIT_KB,
    )


async def _rewrite(
    db: AsyncSession,
    storage: ObjectStorage,
    challenge: Challenge,
    user: User,
    change: Callable[[list[td.Testcase]], list[td.Testcase]],
) -> JudgeProblem:
    problem = await _problem_or_create(db, challenge)
    # Serialise concurrent editors on this problem: without the lock, two edits
    # would each load the same zip and the second commit would silently drop
    # the first's change. Real on Postgres; SQLite serialises writers anyway.
    await db.execute(
        select(JudgeProblem.id).where(JudgeProblem.id == problem.id).with_for_update()
    )
    await db.refresh(problem)
    old_key = problem.object_key
    cases = await asyncio.to_thread(td.load, storage, old_key, problem.testcases)
    cases = change(cases)
    try:
        td.check_sizes(cases)
    except td.TestdataError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc

    if cases:
        key = td.new_key(challenge.competition_id, challenge.id)
        await asyncio.to_thread(storage.put, key, td.build_zip(cases), "application/zip")
        problem.object_key = key
    else:
        problem.object_key = None
    problem.testcases = td.manifest(cases)
    await db.commit()

    if old_key and old_key != problem.object_key:
        try:
            await asyncio.to_thread(storage.delete, old_key)
        except Exception:  # noqa: BLE001 — an orphaned old zip is harmless
            pass
    await event_bus.emit(
        "challenge.updated",
        {
            "competition_id": challenge.competition_id,
            "challenge_id": challenge.id,
            "user_id": user.id,
            "changed_fields": ["judge_testcases"],
        },
    )
    return problem


def _find(cases: list[td.Testcase], testcase_id: str) -> td.Testcase:
    for case in cases:
        if case.id == testcase_id:
            return case
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Test case not found")


# --- availability -------------------------------------------------------------


@router.get("/judge/status", response_model=JudgeStatusOut)
async def judge_status(
    competition_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> JudgeStatusOut:
    if await db.get(Competition, competition_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Competition not found")
    module_enabled = await is_module_enabled(db, "judge", competition_id)
    settings = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
    judge_enabled = bool(settings and settings.enabled)
    languages = (
        await db.execute(
            select(JudgeLanguage.key, JudgeLanguage.name)
            .where(JudgeLanguage.enabled.is_(True))
            .order_by(JudgeLanguage.name)
        )
    ).all()
    return JudgeStatusOut(
        module_enabled=module_enabled,
        judge_enabled=judge_enabled,
        ready=module_enabled and judge_enabled and bool(languages),
        # Key + display name only: images and commands are admin business.
        languages=[{"key": k, "name": n} for k, n in languages],
        default_time_limit_ms=(settings.default_time_limit_ms if settings else None)
        or DEFAULT_TIME_LIMIT_MS,
    )


# --- problem settings --------------------------------------------------------


@router.get("/challenges/{challenge_id}/judge", response_model=JudgeProblemOut)
async def get_problem(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> JudgeProblemOut:
    challenge = await _programming_challenge(db, competition_id, challenge_id)
    return await _out(db, storage, await _problem(db, challenge))


@router.put("/challenges/{challenge_id}/judge", response_model=JudgeProblemOut)
async def update_problem(
    competition_id: str,
    challenge_id: str,
    body: JudgeProblemUpdate,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> JudgeProblemOut:
    challenge = await _programming_challenge(db, competition_id, challenge_id)
    problem = await _problem_or_create(db, challenge)
    sent = body.model_fields_set
    # An explicit null resets to the default; an omitted field is left alone.
    for field in ("time_limit_ms", "memory_limit_mb", "output_limit_kb", "allowed_languages"):
        if field in sent:
            setattr(problem, field, getattr(body, field))
    if body.compare_mode is not None:
        problem.compare_mode = body.compare_mode
    if "float_tolerance" in sent:
        problem.float_tolerance = body.float_tolerance
    if body.case_insensitive is not None:
        problem.case_insensitive = body.case_insensitive
    if problem.compare_mode == "float" and problem.float_tolerance is None:
        problem.float_tolerance = DEFAULT_FLOAT_TOLERANCE
    if "allowed_languages" in sent and body.allowed_languages is not None:
        known = set(
            (await db.execute(select(JudgeLanguage.key))).scalars().all()
        )
        unknown = sorted(set(body.allowed_languages) - known)
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Unknown language(s): {', '.join(unknown)}.",
            )
        if not body.allowed_languages:
            # An empty allow-list would make the problem unsubmittable; treat
            # it as "every enabled language", the default.
            problem.allowed_languages = None
    await db.commit()
    await event_bus.emit(
        "challenge.updated",
        {
            "competition_id": competition_id,
            "challenge_id": challenge_id,
            "user_id": current_user.id,
            "changed_fields": ["judge_problem"],
        },
    )
    return await _out(db, storage, problem)


# --- test cases ---------------------------------------------------------------


def _text(value: str) -> bytes:
    # Text typed into a textarea: normalise line endings, and end with a newline
    # as every judge-produced output does, so "expected" and "actual" compare
    # cleanly under the exact mode too.
    data = value.replace("\r\n", "\n")
    if data and not data.endswith("\n"):
        data += "\n"
    return data.encode("utf-8")


@router.post(
    "/challenges/{challenge_id}/judge/testcases",
    response_model=JudgeProblemOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_testcase(
    competition_id: str,
    challenge_id: str,
    body: JudgeTestcaseCreate,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> JudgeProblemOut:
    challenge = await _programming_challenge(db, competition_id, challenge_id)
    new = td.Testcase(
        id=uuid4().hex, sample=body.sample, input=_text(body.input), answer=_text(body.answer)
    )
    problem = await _rewrite(db, storage, challenge, current_user, lambda cases: [*cases, new])
    return await _out(db, storage, problem)


@router.post(
    "/challenges/{challenge_id}/judge/testcases/upload",
    response_model=JudgeProblemOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_testcase(
    competition_id: str,
    challenge_id: str,
    input_file: UploadFile = File(...),
    answer_file: UploadFile = File(...),
    sample: bool = Form(False),
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> JudgeProblemOut:
    challenge = await _programming_challenge(db, competition_id, challenge_id)
    # Uploaded files are stored byte-for-byte: big or binary inputs are exactly
    # what the upload path is for.
    data_in = await read_upload_capped(input_file, td.MAX_FILE_BYTES)
    data_ans = await read_upload_capped(answer_file, td.MAX_FILE_BYTES)
    new = td.Testcase(id=uuid4().hex, sample=sample, input=data_in, answer=data_ans)
    problem = await _rewrite(db, storage, challenge, current_user, lambda cases: [*cases, new])
    return await _out(db, storage, problem)


@router.get(
    "/challenges/{challenge_id}/judge/testcases/{testcase_id}",
    response_model=JudgeTestcaseContent,
)
async def get_testcase(
    competition_id: str,
    challenge_id: str,
    testcase_id: str,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> JudgeTestcaseContent:
    challenge = await _programming_challenge(db, competition_id, challenge_id)
    problem = await _problem(db, challenge)
    cases = (
        await asyncio.to_thread(td.load, storage, problem.object_key, problem.testcases)
        if problem
        else []
    )
    case = _find(cases, testcase_id)
    if max(len(case.input), len(case.answer)) > _EDITABLE_BYTES:
        return JudgeTestcaseContent(id=case.id, sample=case.sample, editable=False)
    try:
        return JudgeTestcaseContent(
            id=case.id,
            sample=case.sample,
            input=case.input.decode("utf-8"),
            answer=case.answer.decode("utf-8"),
        )
    except UnicodeDecodeError:
        return JudgeTestcaseContent(id=case.id, sample=case.sample, editable=False)


@router.patch(
    "/challenges/{challenge_id}/judge/testcases/{testcase_id}",
    response_model=JudgeProblemOut,
)
async def update_testcase(
    competition_id: str,
    challenge_id: str,
    testcase_id: str,
    body: JudgeTestcaseUpdate,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> JudgeProblemOut:
    challenge = await _programming_challenge(db, competition_id, challenge_id)

    def change(cases: list[td.Testcase]) -> list[td.Testcase]:
        case = _find(cases, testcase_id)
        if body.input is not None:
            case.input = _text(body.input)
        if body.answer is not None:
            case.answer = _text(body.answer)
        if body.sample is not None:
            case.sample = body.sample
        return cases

    problem = await _rewrite(db, storage, challenge, current_user, change)
    return await _out(db, storage, problem)


@router.delete(
    "/challenges/{challenge_id}/judge/testcases/{testcase_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_testcase(
    competition_id: str,
    challenge_id: str,
    testcase_id: str,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    challenge = await _programming_challenge(db, competition_id, challenge_id)

    def change(cases: list[td.Testcase]) -> list[td.Testcase]:
        _find(cases, testcase_id)
        return [c for c in cases if c.id != testcase_id]

    await _rewrite(db, storage, challenge, current_user, change)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- reference-solution check (#450) ----------------------------------------------
#
# An author runs a solution they know is right through the real judge, against
# every test, to catch a wrong expected output or a too-tight limit before
# competitors do. Optional and never a gate on publishing. It's an ordinary
# judging of kind "reference": the same queue and worker (so it waits its turn
# behind live submissions and keeps the judge's concurrency limit), never
# scored, and kept out of competitors' history and the jury console.


async def _latest_reference(db: AsyncSession, challenge: Challenge) -> Judging | None:
    return await db.scalar(
        select(Judging)
        .where(
            Judging.competition_id == challenge.competition_id,
            Judging.challenge_id == challenge.id,
            Judging.kind == "reference",
        )
        .order_by(Judging.created_at.desc(), Judging.id.desc())
        .limit(1)
    )


async def _reference_out(
    db: AsyncSession, storage: ObjectStorage, challenge: Challenge, judging: Judging | None
) -> ReferenceCheckOut:
    if judging is None:
        # No check has run yet: offer an imported package's accepted solution
        # (#451), so the author's first check is one click.
        problem = await _problem(db, challenge)
        if problem is not None and problem.reference_source:
            return ReferenceCheckOut(
                language_key=problem.reference_language, source=problem.reference_source
            )
        return ReferenceCheckOut()
    code = await db.get(CodeSubmission, judging.code_submission_id)
    author = await db.get(User, judging.user_id)
    try:
        source = (await asyncio.to_thread(storage.get, code.source_object_key)).decode(
            "utf-8", "replace"
        )
    except Exception:  # noqa: BLE001 — the results stand without it
        source = None
    stale = False
    if judging.status == "done" and judging.problem_version:
        problem = await _problem(db, challenge)
        settings = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
        stale = (
            problem is None
            or settings is None
            or problem_version(problem, settings) != judging.problem_version
        )
    return ReferenceCheckOut(
        judging=await judging_out(db, judging, staff=True),
        run_by_name=author.display_name if author else None,
        language_key=code.language_key,
        source=source,
        stale=stale,
    )


@router.get("/challenges/{challenge_id}/judge/reference", response_model=ReferenceCheckOut)
async def get_reference_check(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> ReferenceCheckOut:
    """The problem's latest reference check, by any of its authors."""
    challenge = await _programming_challenge(db, competition_id, challenge_id)
    return await _reference_out(db, storage, challenge, await _latest_reference(db, challenge))


@router.post(
    "/challenges/{challenge_id}/judge/reference",
    response_model=ReferenceCheckOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_reference_check(
    competition_id: str,
    challenge_id: str,
    body: ReferenceCheckRequest,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> ReferenceCheckOut:
    # Drafts and competitions that haven't started are exactly when authors
    # check, so no playable/pause gate — but the judge must be on.
    challenge = await _programming_challenge(db, competition_id, challenge_id)
    settings = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
    if settings is None or not settings.enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The code judge isn't running right now — try again shortly",
        )
    problem = await _problem(db, challenge)
    if problem is None or not problem.testcases:
        raise HTTPException(status.HTTP_409_CONFLICT, "Add test cases first")
    language = await available_language(db, problem, body.language)
    source = checked_source(body.source)
    # One check at a time per problem: each runs every test and holds a slot
    # of the one site-wide judge queue. The problem row's lock (as _rewrite
    # takes) makes two simultaneous requests see each other's check.
    await db.execute(
        select(JudgeProblem.id).where(JudgeProblem.id == problem.id).with_for_update()
    )
    active = await db.scalar(
        select(func.count(Judging.id)).where(
            Judging.competition_id == competition_id,
            Judging.challenge_id == challenge.id,
            Judging.kind == "reference",
            Judging.status.in_(ACTIVE_JUDGING_STATUSES),
        )
    )
    if active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A reference check of this problem is already running"
        )
    judging = await queue_code(
        db, storage,
        competition_id=competition_id, challenge_id=challenge.id,
        user_id=current_user.id, team_id=None,
        kind="reference", language=language, source=source,
    )
    return await _reference_out(db, storage, challenge, judging)


# --- problem packages (#451) -------------------------------------------------------
#
# Import and export the open ICPC/Kattis problem package format
# (``utils/problem_package``). Import makes draft challenges in one transaction
# with no per-row events (atomic authoring, like the challenge importer);
# export writes 2025-09 packages.


@router.post("/judge/packages/import", response_model=PackageImportOut)
async def import_problem_packages(
    competition_id: str,
    file: UploadFile = File(...),
    default_time_limit_ms: int | None = Form(default=None, ge=100, le=60_000),
    current_user: User = Depends(require_permission("challenge_create")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> PackageImportOut:
    """Import one problem package, or a contest zip of several. Problems
    Flagpost can't judge faithfully are refused with the reason; the rest
    become draft programming challenges to review before publishing."""
    from utils import problem_package as pp

    await _guard(db, competition_id)
    data = await read_upload_capped(file, pp.MAX_UPLOAD_BYTES)
    languages = (await db.execute(select(JudgeLanguage.key, JudgeLanguage.enabled))).all()
    try:
        result = await asyncio.to_thread(
            pp.parse_package,
            data,
            default_time_limit_ms=default_time_limit_ms,
            language_keys={key for key, enabled in languages if enabled},
            defined_language_keys={key for key, _ in languages},
        )
    except pp.PackageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    report = await pp.create_problems(
        db, storage, competition_id=competition_id, parsed=result.problems
    )
    return PackageImportOut(
        created=report["created"], skipped=report["skipped"], refused=result.refused
    )


async def _export_problem(
    db: AsyncSession, storage: ObjectStorage, challenge: Challenge, settings: JudgeSettings
):
    from models.attachment import Attachment
    from utils import problem_package as pp
    from utils.judge_worker import effective_limits

    problem = await _problem(db, challenge)
    if problem is None:
        problem = JudgeProblem(competition_id=challenge.competition_id, challenge_id=challenge.id)
    limits = effective_limits(problem, settings)
    attachments = (
        await db.scalars(
            select(Attachment)
            .where(
                Attachment.competition_id == challenge.competition_id,
                Attachment.challenge_id == challenge.id,
            )
            .order_by(Attachment.filename, Attachment.id)
        )
    ).all()
    return pp.ExportProblem(
        name=challenge.title,
        uuid=problem.id or challenge.id,
        statement=challenge.description or {"type": "doc", "content": []},
        time_limit_ms=limits["time_limit_ms"],
        memory_limit_mb=limits["memory_limit_mb"],
        output_limit_kb=limits["output_limit_kb"],
        compare_mode=problem.compare_mode or "token",
        float_tolerance=problem.float_tolerance,
        case_insensitive=bool(problem.case_insensitive),
        allowed_languages=problem.allowed_languages,
        testdata_key=problem.object_key,
        testcases=problem.testcases or [],
        files=[(a.filename, a.object_key) for a in attachments],
        reference=await _export_reference(db, storage, challenge, problem),
    )


async def _export_reference(
    db: AsyncSession, storage: ObjectStorage, challenge: Challenge, problem: JudgeProblem
) -> tuple[str, str] | None:
    """The newest accepted reference check's source, else the kept package
    solution — named as the language saves it (Main.java, main.cpp…)."""
    latest = await db.scalar(
        select(Judging)
        .where(
            Judging.competition_id == challenge.competition_id,
            Judging.challenge_id == challenge.id,
            Judging.kind == "reference",
            Judging.verdict == "accepted",
        )
        .order_by(Judging.created_at.desc(), Judging.id.desc())
        .limit(1)
    )
    language_key = source = None
    if latest is not None:
        code = await db.get(CodeSubmission, latest.code_submission_id)
        try:
            source = (await asyncio.to_thread(storage.get, code.source_object_key)).decode("utf-8", "replace")
            language_key = code.language_key
        except Exception:  # noqa: BLE001
            source = None
    if source is None and problem.reference_source:
        language_key, source = problem.reference_language, problem.reference_source
    if source is None or language_key is None:
        return None
    language = await db.scalar(select(JudgeLanguage).where(JudgeLanguage.key == language_key))
    filename = language.source_filename if language else f"solution.{language_key}"
    return filename, source


class _TempFileResponse(FileResponse):
    """A FileResponse that deletes its file however the response ends — including
    the early 400/416 returns for a bad Range header, which skip ``background``."""

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.path)


async def _export_response(problems: list, storage: ObjectStorage, filename: str) -> FileResponse:
    """Build the export into a temporary file (fetching each problem's files as
    it's written) and stream it back; the file goes once it's sent."""
    from utils import problem_package as pp

    handle = tempfile.NamedTemporaryFile(prefix="flagpost-export-", suffix=".zip", delete=False)
    try:
        with handle:
            await asyncio.to_thread(pp.build_export, problems, storage, handle)
    except pp.ExportError as exc:
        os.unlink(handle.name)
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except BaseException:
        os.unlink(handle.name)
        raise
    return _TempFileResponse(handle.name, media_type="application/zip", filename=filename)


@router.get("/challenges/{challenge_id}/judge/package")
async def export_problem_package(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    """This problem as a 2025-09 problem package."""
    from utils import problem_package as pp

    challenge = await _programming_challenge(db, competition_id, challenge_id)
    settings = await _site_defaults(db)
    exported = await _export_problem(db, storage, challenge, settings)
    return await _export_response([exported], storage, f"{pp._slug(challenge.title, set())}.zip")


@router.get("/judge/packages/export")
async def export_problem_packages(
    competition_id: str,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    """Every programming problem in the competition, one package each."""
    await _guard(db, competition_id)
    challenges = (
        await db.scalars(
            select(Challenge)
            .where(Challenge.competition_id == competition_id, Challenge.flag_type == "programming")
            .order_by(Challenge.title)
        )
    ).all()
    if not challenges:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There are no programming problems to export")
    settings = await _site_defaults(db)
    exported = [await _export_problem(db, storage, c, settings) for c in challenges]
    return await _export_response(exported, storage, "problem-packages.zip")
