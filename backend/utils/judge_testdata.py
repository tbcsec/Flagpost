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
