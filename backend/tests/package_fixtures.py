"""Problem packages, built in memory, for the package importer's tests (#451).

The ICPC/Kattis problem package format has enough variants — two format
versions, statement languages and file types, output-checker flags, test
groups, symlinks — that vendoring a real package per case would bury the suite
in binary fixtures nobody can review. So two real packages are vendored
(``fixtures/problem_packages/``, see its README) to prove the importer reads
what the outside world actually produces, and every other case is built here
from a few readable lines.

Every builder returns the zip as ``bytes`` and says what it exercises. They
share one tiny problem — read two integers, print their sum — so a test can
assert on known content (``SUM_NAME``, ``SUM_SAMPLE`` …) and only the variant's
own difference stands out. Output is byte-for-byte reproducible (fixed
timestamps, insertion order).

Zip details an importer must handle are produced on purpose: a symlink is a
Unix-mode entry (``external_attr = 0o120777 << 16``) whose content is the target
path, the same encoding ``zip --symlinks`` writes; and the hostile builders
(``oversized``, ``zip_bomb``) write repetitive bytes that compress to almost
nothing, so a case far past the size caps costs a fraction of a second and a
few hundred KB of zip.
"""

from __future__ import annotations

import io
import stat
import struct
import zipfile
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "problem_packages"
VENDORED = ("hello.zip", "outofsorts.zip")

MB = 1024 * 1024

# A fixed timestamp keeps every builder's output reproducible.
_DATE_TIME = (2026, 1, 1, 0, 0, 0)
_FILE_MODE = 0o100644
_SYMLINK_MODE = 0o120777

# --- the shared problem --------------------------------------------------------

SHORTNAME = "sumoftwo"
SUM_NAME = "Sum of Two"
SUM_UUID = "4b7a2f0e-3c1d-4e5f-8a9b-0c1d2e3f4a5b"
SUM_STATEMENT_TEX = r"""\problemname{Sum of Two}

Read two integers and print their sum.

\section*{Input}
One line with two integers $a$ and $b$ ($-10^9 \le a, b \le 10^9$).

\section*{Output}
Output $a + b$.
"""
SUM_STATEMENT_MD = """Read two integers and print their sum.

## Input

One line with two integers $a$ and $b$ ($-10^9 \\le a, b \\le 10^9$).

## Output

Output $a + b$.
"""
SUM_SOLUTION_PY = "a, b = map(int, input().split())\nprint(a + b)\n"
SUM_SAMPLE = [("3 4\n", "7\n")]
SUM_SECRET = [("10 20\n", "30\n"), ("-5 5\n", "0\n")]

# Float variants keep the same problem with fractional input: 0.1 + 0.2 prints
# 0.30000000000000004, so only a tolerance-aware checker accepts the solution.
FLOAT_SOLUTION_PY = "a, b = map(float, input().split())\nprint(a + b)\n"
FLOAT_SAMPLE = [("0.1 0.2\n", "0.3\n")]
FLOAT_SECRET = [("1.5 2.25\n", "3.75\n"), ("0.7 0.1\n", "0.8\n")]

_LEGACY_META = "source: Flagpost test suite\nlicense: public domain\n"

CC_BY_AUTHOR = "Ada Lovelace and Grace Hopper"
CC_BY_SOURCE = "Example Regional Contest 2025"
CC_BY_SOURCE_URL = "https://contest.example.org/2025"
CC_BY_RIGHTS_OWNER = "Example Contest Committee"

Case = tuple[str, str]


# --- zip plumbing ---------------------------------------------------------------


def _info(name: str, mode: int, compress_type: int = zipfile.ZIP_DEFLATED) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_DATE_TIME)
    info.create_system = 3  # Unix, so the mode bits in external_attr mean something
    info.external_attr = mode << 16
    info.compress_type = compress_type
    return info


def build_package(
    files: dict[str, bytes | str],
    *,
    root: str | None = "pkg",
    symlinks: dict[str, str] | None = None,
) -> bytes:
    """Zip ``files`` (path → content; ``str`` is UTF-8 encoded) into a package.

    ``root`` wraps every entry in one top-level directory, the usual shape of a
    package zip; ``None`` puts the entries at the zip root. ``symlinks`` maps an
    entry path (under ``root`` too) to its link target, stored as a Unix symlink
    entry whose content is the target. Entries are written in dict order, so a
    builder can control the order an importer sees them in.
    """
    prefix = f"{root}/" if root is not None else ""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            zf.writestr(_info(prefix + path, _FILE_MODE), data)
        for path, target in (symlinks or {}).items():
            zf.writestr(_info(prefix + path, _SYMLINK_MODE, zipfile.ZIP_STORED), target.encode())
    return buf.getvalue()


def is_symlink(info: zipfile.ZipInfo) -> bool:
    """Is this entry a Unix symlink (mode in the high 16 bits of external_attr)?"""
    return stat.S_ISLNK(info.external_attr >> 16)


def read_members(blob: bytes) -> dict[str, bytes]:
    """Every entry's content, by name. Small packages only — never a bomb."""
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        return {i.filename: zf.read(i) for i in zf.infolist() if not i.is_dir()}


def symlink_targets(blob: bytes) -> dict[str, str]:
    """The symlink entries of a package zip, as path → target."""
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        return {i.filename: zf.read(i).decode() for i in zf.infolist() if is_symlink(i)}


def vendored(name: str) -> bytes:
    """A vendored real-world package's bytes (see the fixtures README)."""
    return (FIXTURES_DIR / name).read_bytes()


# --- file sets --------------------------------------------------------------------


def _cases(group: str, cases: list[Case]) -> dict[str, str]:
    files: dict[str, str] = {}
    for i, (inp, ans) in enumerate(cases, start=1):
        files[f"data/{group}/{i}.in"] = inp
        files[f"data/{group}/{i}.ans"] = ans
    return files


def legacy_files(
    *,
    name: str | None = SUM_NAME,
    meta: str = _LEGACY_META,
    yaml_extra: str = "",
    sample: list[Case] = SUM_SAMPLE,
    secret: list[Case] = SUM_SECRET,
    solution: str = SUM_SOLUTION_PY,
) -> dict[str, bytes | str]:
    """The legacy-format sum problem as a path → content dict, for composing.

    ``meta`` replaces the source/licence lines; ``yaml_extra`` is appended to
    ``problem.yaml`` verbatim (top-level keys, one per line).
    """
    problem_yaml = (f"name: {name}\n" if name is not None else "") + meta
    problem_yaml += "limits:\n  memory: 512\n" + yaml_extra
    files: dict[str, bytes | str] = {
        "problem.yaml": problem_yaml,
        "problem_statement/problem.en.tex": SUM_STATEMENT_TEX,
    }
    files.update(_cases("sample", sample))
    files.update(_cases("secret", secret))
    files["submissions/accepted/sol.py"] = solution
    return files


def v2025_files() -> dict[str, bytes | str]:
    """The 2025-09-format sum problem as a path → content dict, for composing."""
    files: dict[str, bytes | str] = {
        "problem.yaml": (
            "problem_format_version: 2025-09\n"
            "type: pass-fail\n"
            "name:\n"
            f"  en: {SUM_NAME}\n"
            f"uuid: {SUM_UUID}\n"
            "credits:\n"
            "  authors: Flagpost test suite\n"
            "license: cc0\n"
            "rights_owner: Flagpost contributors\n"
            "limits:\n"
            "  time_limit: 2.5\n"
        ),
        "statement/problem.en.md": SUM_STATEMENT_MD,
    }
    files.update(_cases("sample", SUM_SAMPLE))
    files.update(_cases("secret", SUM_SECRET))
    files["data/secret/test_group.yaml"] = "output_validator_args: [case_sensitive]\n"
    files["submissions/accepted/sol.py"] = SUM_SOLUTION_PY
    return files


def _legacy(**kwargs) -> bytes:
    return build_package(legacy_files(**kwargs), root=SHORTNAME)


# --- well-formed packages ------------------------------------------------------------


def legacy_passfail() -> bytes:
    """The baseline: a legacy pass-fail package with nothing unusual.

    ``problem.yaml`` has a name, ``limits.memory: 512`` and no
    ``validator_flags`` (so the default case-insensitive checker applies); a
    ``\\problemname`` LaTeX statement; one sample and two secret cases; one
    accepted Python solution.
    """
    return _legacy()


def v2025_passfail() -> bytes:
    """The 2025-09 format: a ``name`` language map, a ``uuid``,
    ``limits.time_limit: 2.5`` (an explicit limit, not a multiplier), a
    Markdown statement under ``statement/``, and a ``data/secret/test_group.yaml``
    whose ``output_validator_args`` is a list asking for ``case_sensitive``.
    """
    return build_package(v2025_files(), root=SHORTNAME)


def with_timelimit_file(value: str = "3") -> bytes:
    """Legacy plus a root ``.timelimit`` file (``value`` and a newline) — the
    explicit time limit some judges' exports carry beside ``problem.yaml``."""
    files = legacy_files()
    files[".timelimit"] = f"{value}\n"
    return build_package(files, root=SHORTNAME)


def with_ini_timelimit(value: str = "4", *, filename: str = "judge-problem.ini") -> bytes:
    """Legacy plus a root ``<judge>-problem.ini`` holding ``timelimit = <value>``,
    the other place an exported package records its time limit. Pass
    ``value="'4'"`` for the quoted form some exports write."""
    files = legacy_files()
    files[filename] = f"timelimit = {value}\n"
    return build_package(files, root=SHORTNAME)


def float_tolerance(flags: str = "float_tolerance 1e-6") -> bytes:
    """``validator_flags: float_tolerance 1e-6`` (relative *and* absolute), with
    fractional data that only a tolerance-aware comparison accepts."""
    return _legacy(
        yaml_extra=f"validator_flags: {flags}\n",
        sample=FLOAT_SAMPLE,
        secret=FLOAT_SECRET,
        solution=FLOAT_SOLUTION_PY,
    )


def abs_only_tolerance(flags: str = "float_absolute_tolerance 1e-3") -> bytes:
    """``validator_flags: float_absolute_tolerance 1e-3`` alone — an absolute
    bound with no relative one, over the same fractional data."""
    return float_tolerance(flags)


def case_sensitive_flag(flags: str = "case_sensitive") -> bytes:
    """``validator_flags: case_sensitive`` — the package asks for exact letter
    case, so the import must not switch case-insensitive comparison on. Pass
    e.g. ``"case_sensitive space_change_sensitive"`` for a combined flag line."""
    return _legacy(yaml_extra=f"validator_flags: {flags}\n")


_CHECKER_CPP = """\
// Custom output checker: accepts any answer within 1 of the judge's.
// Invoked as: checker input_file answer_file feedback_dir < team_output
#include <cstdio>
#include <cstdlib>

int main(int argc, char **argv) {
    if (argc < 4) return 1;
    FILE *ans = std::fopen(argv[2], "r");
    long long want, got;
    if (!ans || std::fscanf(ans, "%lld", &want) != 1) return 1;
    if (std::scanf("%lld", &got) != 1) return 43;
    return std::llabs(got - want) <= 1 ? 42 : 43;
}
"""


def custom_validator() -> bytes:
    """``validation: custom`` with a C++ checker in ``output_validators/checker/``
    — a problem whose verdicts depend on code the importer can't run as-is."""
    files = legacy_files(yaml_extra="validation: custom\n")
    files["output_validators/checker/checker.cpp"] = _CHECKER_CPP
    return build_package(files, root=SHORTNAME)


# Not the upstream source: a short stand-in that carries the same flag names,
# which is what lets an importer recognise a bundled copy of the default checker.
_DEFAULT_VALIDATOR_CC = """\
// Default output validator: token-by-token comparison of the team output with
// the judge answer. Flags: case_sensitive, space_change_sensitive,
// float_absolute_tolerance <eps>, float_relative_tolerance <eps>,
// float_tolerance <eps> (sets both).
#include <cstdlib>
#include <cstring>

int main(int argc, char **argv) {
    bool case_sensitive = false, space_change_sensitive = false;
    double float_absolute_tolerance = -1, float_relative_tolerance = -1;
    for (int i = 4; i < argc; ++i) {
        if (!std::strcmp(argv[i], "case_sensitive")) case_sensitive = true;
        else if (!std::strcmp(argv[i], "space_change_sensitive")) space_change_sensitive = true;
        else if (!std::strcmp(argv[i], "float_absolute_tolerance") && i + 1 < argc)
            float_absolute_tolerance = std::atof(argv[++i]);
        else if (!std::strcmp(argv[i], "float_relative_tolerance") && i + 1 < argc)
            float_relative_tolerance = std::atof(argv[++i]);
        else if (!std::strcmp(argv[i], "float_tolerance") && i + 1 < argc)
            float_absolute_tolerance = float_relative_tolerance = std::atof(argv[++i]);
    }
    (void)case_sensitive; (void)space_change_sensitive;
    (void)float_absolute_tolerance; (void)float_relative_tolerance;
    // Comparison elided: a fixture to be recognised, never run.
    return 42;
}
"""


def bundled_default_validator(*, declared_custom: bool = False) -> bytes:
    """Default validation, but with a copy of the default checker bundled at
    ``output_validators/default_validator/default_validator.cc`` — common in
    exported packages, and *not* a custom checker. ``declared_custom=True`` also
    sets ``validation: custom``, as some exports do around the same copy."""
    files = legacy_files(yaml_extra="validation: custom\n" if declared_custom else "")
    files["output_validators/default_validator/default_validator.cc"] = _DEFAULT_VALIDATOR_CC
    return build_package(files, root=SHORTNAME)


_INTERACTOR_CPP = """\
// Interactor for Guess the Number: reads the secret from the input file,
// answers each guess with lower/higher/correct.
#include <cstdio>
#include <cstring>

int main(int argc, char **argv) {
    FILE *in = std::fopen(argv[1], "r");
    int secret, guess;
    if (!in || std::fscanf(in, "%d", &secret) != 1) return 1;
    for (int tries = 0; tries < 10; ++tries) {
        if (std::scanf("%d", &guess) != 1) return 43;
        if (guess == secret) { std::printf("correct\\n"); std::fflush(stdout); return 42; }
        std::printf(guess > secret ? "lower\\n" : "higher\\n");
        std::fflush(stdout);
    }
    return 43;
}
"""
_GUESS_SOLUTION_PY = """\
lo, hi = 1, 100
while True:
    mid = (lo + hi) // 2
    print(mid, flush=True)
    reply = input()
    if reply == "correct":
        break
    if reply == "lower":
        hi = mid - 1
    else:
        lo = mid + 1
"""
# ``<`` lines come from the judge, ``>`` lines from the submission.
_GUESS_INTERACTION = "> 50\n< lower\n> 25\n< higher\n> 37\n< higher\n> 43\n< lower\n> 40\n< correct\n"


def interactive(*, legacy: bool = False) -> bytes:
    """An interactive problem (guess the number), with an interactor and a
    ``.interaction`` sample transcript. 2025-09 by default (``type: interactive``,
    ``output_validator/``, and the ``.in.download``/``.ans.download`` pair that
    format requires beside an ``.interaction``); ``legacy=True`` declares it the
    legacy way (``validation: custom interactive``, ``output_validators/<name>/``)."""
    files: dict[str, bytes | str]
    if legacy:
        files = {
            "problem.yaml": (
                "name: Guess the Number\n" + _LEGACY_META + "validation: custom interactive\n"
            ),
            "problem_statement/problem.en.tex": (
                "\\problemname{Guess the Number}\n\nGuess a number from 1 to 100.\n"
            ),
            "output_validators/interactor/interactor.cpp": _INTERACTOR_CPP,
        }
    else:
        files = {
            "problem.yaml": (
                "problem_format_version: 2025-09\n"
                "type: interactive\n"
                "name: Guess the Number\n"
                "uuid: 9d1c6a52-7e0b-4f3a-b2c4-5e6f7a8b9c0d\n"
                "license: public domain\n"
                "limits:\n"
                "  time_limit: 2.0\n"
            ),
            "statement/problem.en.md": "Guess a number from 1 to 100.\n",
            "output_validator/interactor.cpp": _INTERACTOR_CPP,
            "data/sample/1.in.download": "40\n",
            "data/sample/1.ans.download": "40\n",
        }
    files.update({
        "data/sample/1.in": "40\n",
        "data/sample/1.ans": "40\n",
        "data/sample/1.interaction": _GUESS_INTERACTION,
        "data/secret/1.in": "7\n",
        "data/secret/1.ans": "7\n",
        "data/secret/2.in": "100\n",
        "data/secret/2.ans": "100\n",
        "submissions/accepted/sol.py": _GUESS_SOLUTION_PY,
    })
    return build_package(files, root="guess")


def scoring() -> bytes:
    """A 2025-09 ``type: scoring`` problem with two secret groups carrying
    ``max_score`` 30 and 70 in their ``test_group.yaml`` — partial credit per
    group, which a pass-fail judge has to refuse or flatten knowingly."""
    files: dict[str, bytes | str] = {
        "problem.yaml": (
            "problem_format_version: 2025-09\n"
            "type: scoring\n"
            f"name: {SUM_NAME}\n"
            "uuid: 1f2e3d4c-5b6a-4798-8a7b-6c5d4e3f2a1b\n"
            "license: public domain\n"
        ),
        "statement/problem.en.md": SUM_STATEMENT_MD,
        "data/secret/group1/test_group.yaml": "max_score: 30\n",
        "data/secret/group2/test_group.yaml": "max_score: 70\n",
    }
    files.update(_cases("sample", SUM_SAMPLE))
    files.update(_cases("secret/group1", [("1 1\n", "2\n")]))
    files.update(_cases("secret/group2", [("1000000000 1000000000\n", "2000000000\n")]))
    files["submissions/accepted/sol.py"] = SUM_SOLUTION_PY
    return build_package(files, root=SHORTNAME)


# Expected judging order of test_groups(), by answer: the sample, then the
# secret groups in lexicographic order, each group's cases in order.
TEST_GROUPS_ANSWER_ORDER = ["1\n", "2\n", "3\n", "4\n", "5\n"]


def test_groups() -> bytes:
    """Pass-fail with secret cases nested in ``data/secret/group1/`` and
    ``group2/`` — they must flatten into one ordered list
    (``TEST_GROUPS_ANSWER_ORDER``). The secret entries are written to the zip
    in *reverse* order, so an importer that trusts zip order fails."""
    files = legacy_files(sample=[("0 1\n", "1\n")], secret=[])
    nested: dict[str, str] = {}
    nested.update(_cases("secret/group1", [("1 1\n", "2\n"), ("1 2\n", "3\n")]))
    nested.update(_cases("secret/group2", [("2 2\n", "4\n"), ("2 3\n", "5\n")]))
    files.update(dict(reversed(list(nested.items()))))
    return build_package(files, root=SHORTNAME)


# Keep pytest from collecting the builder above as a test.
test_groups.__test__ = False  # type: ignore[attr-defined]


def symlinked_case() -> bytes:
    """A third secret case whose ``.in`` is a symlink to the sample's ``.in``
    (``../sample/1.in``) — legal, since it stays inside the package; its
    ``.ans`` is a regular file."""
    files = legacy_files()
    files["data/secret/3.ans"] = SUM_SAMPLE[0][1]
    return build_package(
        files, root=SHORTNAME, symlinks={"data/secret/3.in": "../sample/1.in"}
    )


def escaping_symlink(target: str = "../../../../etc/passwd") -> bytes:
    """A secret ``.in`` symlinked outside the package — the default climbs past
    the package root *and* the zip root. Pass ``"/etc/passwd"`` for an absolute
    target. The importer must refuse, never follow it."""
    files = legacy_files()
    files["data/secret/3.ans"] = "0\n"
    return build_package(files, root=SHORTNAME, symlinks={"data/secret/3.in": target})


def cross_package_symlink() -> bytes:
    """A contest zip (``alpha/``, ``beta/``) where ``beta``'s secret ``3.in``
    links to a *real* member of ``alpha`` (``../../../alpha/data/secret/1.in``).
    It escapes beta's package but not the zip, and the target exists — so only
    a check against the package root refuses it; one that merely keeps links
    inside the zip, or fails on a missing target, lets it through. ``alpha``
    itself is clean and should still import."""
    files = _contest_files()
    files["beta/data/secret/3.ans"] = SUM_SECRET[0][1]
    return build_package(
        files, root=None, symlinks={"beta/data/secret/3.in": "../../../alpha/data/secret/1.in"}
    )


def symlink_loop() -> bytes:
    """Secret ``3.in`` and ``4.in`` link to each other, each with a real
    ``.ans`` — following links without a hop limit never returns."""
    files = legacy_files()
    files["data/secret/3.ans"] = "0\n"
    files["data/secret/4.ans"] = "0\n"
    return build_package(
        files, root=SHORTNAME, symlinks={"data/secret/3.in": "4.in", "data/secret/4.in": "3.in"}
    )


def missing_answer() -> bytes:
    """A secret ``3.in`` with no ``3.ans`` beside it."""
    files = legacy_files()
    files["data/secret/3.in"] = "1 1\n"
    return build_package(files, root=SHORTNAME)


def oversized(total_mb: int = 65, *, file_mb: int | None = None) -> bytes:
    """Secret inputs totalling ``total_mb`` MiB (default just past the 64 MiB
    per-problem cap). Inputs are at most 8 MiB each — under the 16 MiB per-file
    cap, so only the total trips — unless ``file_mb`` sets their size, e.g.
    ``oversized(17, file_mb=17)`` for one file past the per-file cap. The bytes
    are a repeated line, so the zip stays tiny."""
    if total_mb < 1 or (file_mb is not None and file_mb < 1):
        raise ValueError("sizes are whole MiB, at least 1")
    if file_mb is not None and file_mb > total_mb:
        # Otherwise the one file silently shrinks to total_mb and trips nothing.
        raise ValueError("file_mb can't exceed total_mb")
    chunk_mb = file_mb if file_mb is not None else min(8, total_mb)
    sizes = [chunk_mb] * (total_mb // chunk_mb)
    if total_mb % chunk_mb:
        sizes.append(total_mb % chunk_mb)
    files = legacy_files(secret=[])
    blobs: dict[int, bytes] = {}
    for i, size in enumerate(sizes, start=1):
        if size not in blobs:
            blobs[size] = b"1 1\n" * (size * MB // 4)
        files[f"data/secret/{i}.in"] = blobs[size]
        files[f"data/secret/{i}.ans"] = "2\n"
    return build_package(files, root=SHORTNAME)


def zip_bomb(uncompressed_mb: int = 256, *, declared_size: int | None = None) -> bytes:
    """A secret ``.in`` of ``uncompressed_mb`` MiB of zeros, ~1000:1 deflated —
    far past every cap from a zip of a few hundred KB. Streamed, so building it
    never holds the member in memory.

    ``declared_size`` rewrites the member's uncompressed size in both the local
    and central headers, so the zip *claims* a small file: a reader that trusts
    ``ZipInfo.file_size`` is fooled, and ``zipfile`` stops at the claimed size
    then fails the CRC check (``BadZipFile``).
    """
    if uncompressed_mb >= 2048:
        raise ValueError("keep the bomb under 2 GiB: no ZIP64 headers to patch")
    files = legacy_files()
    files["data/secret/3.ans"] = "0\n"
    name = f"{SHORTNAME}/data/secret/3.in"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            zf.writestr(_info(f"{SHORTNAME}/{path}", _FILE_MODE), data)
        info = _info(name, _FILE_MODE)
        with zf.open(info, "w") as out:
            zeros = bytes(MB)
            for _ in range(uncompressed_mb):
                out.write(zeros)
    if declared_size is None:
        return buf.getvalue()
    return _patch_declared_size(bytearray(buf.getvalue()), name, info.header_offset, declared_size)


def _patch_declared_size(raw: bytearray, name: str, local_offset: int, size: int) -> bytes:
    # Local file header: uncompressed size at +22.
    if raw[local_offset:local_offset + 4] != b"PK\x03\x04":
        raise ValueError("local header not where zipfile said")
    struct.pack_into("<I", raw, local_offset + 22, size)
    # Central directory, located from the end record (no archive comment).
    eocd = len(raw) - 22
    if raw[eocd:eocd + 4] != b"PK\x05\x06":
        raise ValueError("end-of-central-directory record not found")
    count, _, cd_offset = struct.unpack_from("<HII", raw, eocd + 10)
    pos = cd_offset
    for _ in range(count):
        name_len, extra_len, comment_len = struct.unpack_from("<HHH", raw, pos + 28)
        if raw[pos + 46:pos + 46 + name_len].decode() == name:
            struct.pack_into("<I", raw, pos + 24, size)  # uncompressed size
            return bytes(raw)
        pos += 46 + name_len + extra_len + comment_len
    raise ValueError(f"{name} not in the central directory")


def _contest_files() -> dict[str, bytes | str]:
    """Two complete legacy packages, ``alpha/`` (Alpha) and ``beta/`` (Beta),
    for a zip with no single root."""
    files: dict[str, bytes | str] = {}
    for shortname, name in (("alpha", "Alpha"), ("beta", "Beta")):
        for path, content in legacy_files(name=name).items():
            files[f"{shortname}/{path}"] = content
    return files


def multi_problem() -> bytes:
    """A contest zip: two problem roots (``alpha/``, ``beta/``) side by side,
    each a complete package — not one problem, so a single-problem import must
    say so rather than pick one."""
    return build_package(_contest_files(), root=None)


# Enough of a PDF to pass a magic-byte sniff; not a renderable document.
_PDF_BYTES = (
    b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
)


def pdf_statement() -> bytes:
    """The statement only as ``problem_statement/problem.pdf`` — no LaTeX to
    convert, so the name comes from ``problem.yaml`` alone."""
    files = legacy_files()
    del files["problem_statement/problem.en.tex"]
    files["problem_statement/problem.pdf"] = _PDF_BYTES
    return build_package(files, root=SHORTNAME)


def no_name() -> bytes:
    """``problem.yaml`` with no ``name``: the title must come from the
    statement's ``\\problemname{Sum of Two}``."""
    return _legacy(name=None)


def unknown_key() -> bytes:
    """An unrecognised ``problem.yaml`` key (``sandbox-type: X``) — judge
    extensions are common; ignore with a warning, don't refuse."""
    return _legacy(yaml_extra="sandbox-type: X\n")


def license_unknown() -> bytes:
    """``license: unknown`` explicitly — redistribution rights unclear."""
    return _legacy(meta="source: Flagpost test suite\nlicense: unknown\n")


def cc_by() -> bytes:
    """``license: cc by`` with ``author``, ``source``, ``source_url`` and
    ``rights_owner`` — a licence that requires attribution, and the fields to
    attribute from (``CC_BY_*``)."""
    return _legacy(
        meta=(
            f"author: {CC_BY_AUTHOR}\n"
            f"source: {CC_BY_SOURCE}\n"
            f"source_url: {CC_BY_SOURCE_URL}\n"
            "license: cc by\n"
            f"rights_owner: {CC_BY_RIGHTS_OWNER}\n"
        )
    )


_TESTING_TOOL_PY = """\
#!/usr/bin/env python3
# Local testing tool: runs your program on one input and prints its output.
import subprocess
import sys

print(subprocess.run(sys.argv[1:], input=b"3 4\\n", capture_output=True).stdout.decode())
"""


def attachments() -> bytes:
    """A public ``attachments/testing_tool.py`` for competitors to download."""
    files = legacy_files()
    files["attachments/testing_tool.py"] = _TESTING_TOOL_PY
    return build_package(files, root=SHORTNAME)


def kotlin_and_python_accepted(*, python3: bool = True) -> bytes:
    """Accepted solutions in Kotlin (``sol.kt``), Python 3 (``sol.py``) and
    Python 2 (``sol2.py``, told apart only by its ``#!/usr/bin/python2``
    shebang) — language detection beyond the file extension.

    ``sol.py`` sorts before ``sol2.py``, so an importer that keeps the first
    solution per language never reads the Python 2 file here. ``python3=False``
    drops ``sol.py``, leaving the Python 2 file as the only ``.py`` — the case
    that shows whether the shebang is actually checked."""
    files = legacy_files()
    if not python3:
        del files["submissions/accepted/sol.py"]
    files["submissions/accepted/sol.kt"] = (
        "fun main() {\n"
        "    val (a, b) = readLine()!!.trim().split(\" \").map { it.toLong() }\n"
        "    println(a + b)\n"
        "}\n"
    )
    files["submissions/accepted/sol2.py"] = (
        "#!/usr/bin/python2\na, b = map(int, raw_input().split())\nprint a + b\n"
    )
    return build_package(files, root=SHORTNAME)
