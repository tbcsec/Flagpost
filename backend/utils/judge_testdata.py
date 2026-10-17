"""Reading and writing a programming problem's test-data zip (#447, ADR-0042).

The zip uses the ICPC/Kattis layout — ``data/sample/NNN.in|.ans`` and
``data/secret/NNN.in|.ans`` — with names derived from position on every write,
so they always sort in judging order (samples first, then the hidden cases).
The problem row's ``testcases`` manifest carries each case's stable ``id``.

Object storage is synchronous and whole-object (``storage/base.py``), so these
helpers are plain functions; async callers run them via ``asyncio.to_thread``.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from uuid import uuid4

from storage.base import ObjectStorage
from utils.untrusted_zip import MAX_MEMBERS, ArchiveRefused, check_member_count, read_bounded

# Per-file and per-problem caps. Generous for contest test data (large
# performance inputs run to a few MB), bounded so a single problem can't
# swallow the object store or a backup.
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
# Two zip entries a case, so the shared entry cap allows this many — the most a
# problem package can bring in, and so the most the editor accepts too.
MAX_CASES = MAX_MEMBERS // 2


@dataclass
class Testcase:
    id: str
    sample: bool
    input: bytes
    answer: bytes


class TestdataError(ValueError):
    """A size cap or format problem, with a message fit for the author."""


def new_key(competition_id: str, challenge_id: str) -> str:
    # A fresh key per write: the new zip is stored before the row points at it,
    # and the old one deleted only after commit, so a failure part-way never
    # leaves the row pointing at a half-written or missing object.
    return f"{competition_id}/judge/{challenge_id}/{uuid4().hex}.zip"


def _entry_names(cases: list[Testcase]) -> list[tuple[Testcase, str]]:
    samples = [c for c in cases if c.sample]
    secrets = [c for c in cases if not c.sample]
    named: list[tuple[Testcase, str]] = []
    for group, folder in ((samples, "sample"), (secrets, "secret")):
        for i, case in enumerate(group, start=1):
            named.append((case, f"data/{folder}/{i:03d}"))
    return named


def ordered(cases: list[Testcase]) -> list[Testcase]:
    """Judging order: samples first, then hidden cases, each in insertion order."""
    return [c for c, _ in _entry_names(cases)]


def check_sizes(cases: list[Testcase]) -> None:
    if len(cases) > MAX_CASES:
        raise TestdataError(f"A problem can have at most {MAX_CASES:,} test cases.")
    total = 0
    for case in cases:
        for label, blob in (("input", case.input), ("expected output", case.answer)):
            if len(blob) > MAX_FILE_BYTES:
                raise TestdataError(
                    f"A test case's {label} is larger than "
                    f"{MAX_FILE_BYTES // (1024 * 1024)} MB."
                )
            total += len(blob)
    if total > MAX_TOTAL_BYTES:
        raise TestdataError(
            f"This problem's test data would exceed {MAX_TOTAL_BYTES // (1024 * 1024)} MB."
        )


def build_zip(cases: list[Testcase]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for case, stem in _entry_names(cases):
            zf.writestr(f"{stem}.in", case.input)
            zf.writestr(f"{stem}.ans", case.answer)
    return buf.getvalue()


def manifest(cases: list[Testcase]) -> list[dict]:
    return [
        {
            "id": case.id,
            "sample": case.sample,
            "input_bytes": len(case.input),
            "answer_bytes": len(case.answer),
        }
        for case in ordered(cases)
    ]


def load(storage: ObjectStorage, key: str | None, rows: list[dict]) -> list[Testcase]:
    """The problem's test cases, in manifest order. Our own zips only — the
    names are derived from manifest position, so they line up 1:1. Read within
    the caps all the same (GHSA-wvjv-56qv-9v42): a restored backup decides the
    stored bytes, and this runs on every judging and problem view."""
    if not key or not rows:
        return []
    if len(rows) > MAX_CASES:  # a manifest no write path could have made
        raise TestdataError("The stored test data is malformed.")
    blob = storage.get(key)
    try:
        check_member_count(blob, MAX_MEMBERS)
    except ArchiveRefused as exc:
        raise TestdataError("The stored test data is malformed.") from exc
    total = 0

    def read(zf: zipfile.ZipFile, name: str) -> bytes:
        nonlocal total
        try:
            data = read_bounded(zf, name, MAX_FILE_BYTES + 1)
        except ArchiveRefused as exc:
            raise TestdataError("The stored test data is malformed.") from exc
        total += len(data)
        if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise TestdataError("The stored test data is larger than a problem allows.")
        return data

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
        stub = [Testcase(id=r["id"], sample=bool(r["sample"]), input=b"", answer=b"") for r in rows]
        cases: list[Testcase] = []
        for case, stem in _entry_names(stub):
            if f"{stem}.in" not in names or f"{stem}.ans" not in names:
                raise TestdataError("The stored test data is incomplete.")
            cases.append(
                Testcase(
                    id=case.id,
                    sample=case.sample,
                    input=read(zf, f"{stem}.in"),
                    answer=read(zf, f"{stem}.ans"),
                )
            )
    return cases


def rebuild(blob: bytes, rows: list[dict]) -> tuple[bytes, list[dict]]:
    """Re-derive test data that arrived from outside — a backup's object
    side-car — rather than storing the archive as sent (GHSA-4wrj). It must hold
    exactly the members its manifest names, within the caps an upload is held
    to; what's stored is then a fresh :func:`build_zip` of what was read, with
    the manifest rewritten to match. ``rows`` is the shape-checked manifest.
    Raises :class:`TestdataError`."""
    stub = [Testcase(id=r["id"], sample=r["sample"], input=b"", answer=b"") for r in rows]
    named = _entry_names(stub)
    expected = sorted(f"{stem}{ext}" for _, stem in named for ext in (".in", ".ans"))
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            infos = zf.infolist()
            if sorted(info.filename for info in infos) != expected:
                raise TestdataError("The test data doesn't match its test-case list.")
            # Judged from the headers before anything inflates: zipfile never
            # returns more of a stored or deflated member than its header
            # declares (it inflates those in bounded steps — not so a bzip2 or
            # LZMA chunk, which our own zips never use), so this also bounds
            # the reads below.
            if any(
                info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                for info in infos
            ):
                raise TestdataError("The test data uses an unsupported compression.")
            if any(info.file_size > MAX_FILE_BYTES for info in infos) or (
                sum(info.file_size for info in infos) > MAX_TOTAL_BYTES
            ):
                raise TestdataError("The test data is larger than a problem allows.")
            cases = [
                Testcase(
                    id=case.id,
                    sample=case.sample,
                    input=zf.read(f"{stem}.in"),
                    answer=zf.read(f"{stem}.ans"),
                )
                for case, stem in named
            ]
    except TestdataError:
        raise
    except Exception as exc:  # noqa: BLE001 — a corrupt, truncated or lying archive
        raise TestdataError("The test data isn't a readable zip.") from exc
    check_sizes(cases)
    return build_zip(cases), manifest(cases)
