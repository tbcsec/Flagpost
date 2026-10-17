"""Problem packages — import and export the open ICPC/Kattis problem package
format for programming challenges (#451, ARCHITECTURE §17.7).

A package is a directory (or a zip of one) holding ``problem.yaml``, a
statement, ``data/sample`` + ``data/secret`` test cases (``.in``/``.ans``
pairs) and reference submissions. Adopting the standard format is what makes
the large body of public problem sets usable in Flagpost. Both live versions
are read — "legacy" (the default, still what most archives ship) and "2025-09"
— and, because real archives mislabel versions, directory names are looked up
in both spellings whatever the package declares.

**A faithful subset.** Flagpost judges pass/fail problems with the standard
output check, reading stdin and writing stdout. A package that needs more —
a custom output checker, an interactive or scoring problem, files or include
directories, per-test arguments — is *refused* with the reason, never judged
with the standard check by mistake. Things that don't affect verdicts (hints,
validators, generators, visualisers…) are ignored with a note. Real packages
often bundle a verbatim copy of the standard checker as a "custom" one; that
copy is recognised and treated as the standard check.

**Same containment as the challenge importer** (``utils/challenge_yaml``,
GHSA-wvjv, both through ``utils/untrusted_zip``): every member is read through
a bounded reader that never trusts a declared size and accepts stored or
deflate members only, the whole import is held under an aggregate ceiling, and
the member count is capped. Test data must also fit the judge's own caps (16 MB a
file, 64 MB a problem — owner decision: refuse rather than raise them, since
every judging copies all of a problem's tests). Symlinks — which the format
allows — are followed only inside the package.

Parsing here is pure (no database, no storage) so it runs in a thread; the
importer (``routers/judge_problems``) turns the result into draft challenges
in one transaction, with no per-row events — atomic authoring, like the
challenge importer.
"""

from __future__ import annotations

import bisect
import io
import logging
import math
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from typing import IO
from uuid import uuid4

import yaml

from utils import judge_testdata as td
from utils.untrusted_zip import (
    READ_ERRORS,
    ArchiveRefused,
    check_member_count,
    read_bounded,
    unique_name,
    yaml_too_large,
)

logger = logging.getLogger(__name__)

# --- caps ------------------------------------------------------------------------

MAX_UPLOAD_BYTES = 128 * 1024 * 1024  # the compressed upload
MAX_MEMBERS = 20_000  # members in one zip
MAX_PROBLEMS = 200  # problems in one contest zip
_MAX_YAML_NODES = 10_000  # a manifest's size once its aliases are expanded
MAX_TOTAL_DECOMPRESSED = 512 * 1024 * 1024  # everything read, across the import
MAX_MANIFEST_BYTES = 1 * 1024 * 1024  # problem.yaml, test_group.yaml, …
MAX_STATEMENT_BYTES = 1 * 1024 * 1024  # a statement's source
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024  # a statement PDF, image or attachment
MAX_SOURCE_BYTES = 128 * 1024  # a reference solution (the submission cap)
_MAX_SYMLINK_HOPS = 8

# Problem types and checking Flagpost can't judge faithfully.
_UNSUPPORTED_TYPES = {"scoring", "interactive", "multi-pass", "submit-answer"}

STATEMENT_KINDS = ("md", "tex", "pdf")  # preference order for the text

# Reference-solution language by file extension (the format's codes, which are
# also Flagpost's preset keys), and the order to pick one in: compiled and
# quick to judge first. Java comes late because packages name their class
# after the problem, and Flagpost's Java preset expects ``Main``.
_EXT_LANG = {
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".c++": "cpp", ".C": "cpp",
    ".c": "c", ".rs": "rust", ".py": "python3", ".py3": "python3", ".go": "go",
    ".java": "java", ".cs": "csharp", ".js": "javascript", ".kt": "kotlin",
}
_REFERENCE_ORDER = ("cpp", "c", "rust", "python3", "go", "csharp", "javascript", "kotlin", "java")

_IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml", ".gif": "image/gif",
}


class PackageError(Exception):
    """A whole import that can't proceed (not a zip, no problems, too big)."""


class Refused(Exception):
    """One problem in the package that Flagpost can't import faithfully."""


@dataclass
class PackageFile:
    filename: str
    data: bytes
    content_type: str


@dataclass
class ParsedProblem:
    """Everything the importer needs to create one draft programming challenge."""

    root: str
    name: str
    statement: dict  # TipTap doc
    files: list[PackageFile] = field(default_factory=list)
    time_limit_ms: int | None = None
    memory_limit_mb: int | None = None
    output_limit_kb: int | None = None
    compare_mode: str = "token"
    float_tolerance: float | None = None
    case_insensitive: bool = True
    allowed_languages: list[str] | None = None
    testcases: list[td.Testcase] = field(default_factory=list)
    reference_language: str | None = None
    reference_source: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParseResult:
    problems: list[ParsedProblem] = field(default_factory=list)
    refused: list[dict] = field(default_factory=list)  # {"name", "reason"}


# --- reading the zip --------------------------------------------------------------


def _check_directory(data: bytes) -> None:
    """Refuse a zip with too many entries before zipfile parses it (see
    ``utils.untrusted_zip``)."""
    try:
        check_member_count(data, MAX_MEMBERS)
    except ArchiveRefused as exc:
        raise PackageError(str(exc)) from exc


class _Zip:
    """Bounded, symlink-aware reads over an untrusted zip."""

    def __init__(self, data: bytes) -> None:
        _check_directory(data)
        try:
            self.zf = zipfile.ZipFile(io.BytesIO(data))
        except READ_ERRORS as exc:
            raise PackageError("That isn't a valid zip file") from exc
        infos = self.zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise PackageError(f"The zip has too many files (more than {MAX_MEMBERS:,})")
        self.infos = {i.filename.rstrip("/"): i for i in infos if not i.is_dir()}
        self.sorted = sorted(self.infos)
        self.children: dict[str, list[str]] = {}  # directory → its files
        for name in self.sorted:
            self.children.setdefault(posixpath.dirname(name), []).append(name)
        self.total = 0

    def names(self) -> list[str]:
        return self.sorted

    def under(self, prefix: str) -> list[str]:
        """Members whose path starts with ``prefix`` — a slice of the sorted
        names, so a contest zip's many problems don't each rescan the whole zip."""
        start = bisect.bisect_left(self.sorted, prefix)
        end = bisect.bisect_left(self.sorted, prefix + "\U0010ffff")
        return self.sorted[start:end]

    def _is_symlink(self, info: zipfile.ZipInfo) -> bool:
        return (info.external_attr >> 16) & 0o170000 == 0o120000

    def resolve(self, name: str, root: str) -> str:
        """Follow symlinks (stored as members whose content is the target) to a
        real member inside ``root``; refuse anything that escapes or loops."""
        current = name
        for _ in range(_MAX_SYMLINK_HOPS):
            info = self.infos.get(current)
            if info is None:
                raise Refused(f"{current} is missing")
            if not self._is_symlink(info):
                return current
            target = self._read(info, current, root, 4097).decode("utf-8", "replace")
            joined = posixpath.normpath(posixpath.join(posixpath.dirname(current), target))
            outside = (
                target.startswith("/")
                or joined == ".."
                or joined.startswith("../")
                or (root and joined != root and not joined.startswith(root + "/"))
            )
            if outside:
                raise Refused(f"{_short(current, root)} links outside the package")
            current = joined
        raise Refused(f"{name}: too many links")

    def _read(self, info: zipfile.ZipInfo, name: str, root: str, limit: int) -> bytes:
        try:
            blob = read_bounded(self.zf, info, limit)
        except ArchiveRefused as exc:  # bzip2/LZMA: would inflate whole, past any limit
            raise Refused(str(exc)) from exc
        except READ_ERRORS as exc:
            raise Refused(f"{_short(name, root)} can't be read (the zip is damaged or encrypted)") from exc
        # Every byte inflated counts — an over-cap read too, or many problems
        # could each inflate one oversized member for free.
        self.total += len(blob)
        if self.total > MAX_TOTAL_DECOMPRESSED:
            raise PackageError(f"The package is larger than {_mb(MAX_TOTAL_DECOMPRESSED)} unpacked")
        return blob

    def read(self, name: str, root: str, cap: int) -> bytes:
        real = self.resolve(name, root)
        blob = self._read(self.infos[real], name, root, cap + 1)
        if len(blob) > cap:
            raise Refused(f"{_short(name, root)} is larger than {_mb(cap)}")
        return blob


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB"


def _short(name: str, root: str) -> str:
    return name[len(root) + 1:] if root and name.startswith(root + "/") else name


def _roots(z: _Zip) -> list[str]:
    """The problem directories: wherever a problem.yaml sits (a contest zip
    holds several; a single package may or may not be wrapped in a folder)."""
    found = {posixpath.dirname(n) for n in z.names() if posixpath.basename(n) == "problem.yaml"}
    roots: list[str] = []
    # A directory sorts before everything inside it, so the outermost problem
    # comes first and a problem.yaml nested inside it (a bundled example, say)
    # is skipped; a package at the zip root encloses everything.
    for root in sorted(found):
        if not any(r == "" or root.startswith(r + "/") for r in roots):
            roots.append(root)
    return roots


def _under(z: _Zip, root: str, *dirs: str) -> list[str]:
    """Members under any of ``dirs`` (relative to ``root``), sorted."""
    prefixes = [posixpath.join(root, d) + "/" if root else d + "/" for d in dirs]
    return sorted({n for p in prefixes for n in z.under(p)})


def _yaml(z: _Zip, name: str, root: str) -> dict:
    try:
        loaded = yaml.safe_load(z.read(name, root, MAX_MANIFEST_BYTES)) or {}
    except yaml.YAMLError as exc:
        raise Refused(f"{_short(name, root)} isn't valid YAML") from exc
    if not isinstance(loaded, dict):
        raise Refused(f"{_short(name, root)} isn't a YAML mapping")
    if yaml_too_large(loaded, _MAX_YAML_NODES):
        raise Refused(f"{_short(name, root)} is too large once its aliases are expanded")
    return loaded


# --- the problem -----------------------------------------------------------------


def parse_package(
    data: bytes,
    *,
    default_time_limit_ms: int | None,
    language_keys: set[str],
    defined_language_keys: set[str] | None = None,
) -> ParseResult:
    """Parse every problem in a package zip. ``default_time_limit_ms`` is the
    import form's answer for packages that don't state one; ``language_keys``
    are the languages competitors can use now (for the reference solution),
    ``defined_language_keys`` every language this site defines, enabled or not
    (for a problem's allowed-language list — the same rule the editor applies)."""
    z = _Zip(data)
    roots = _roots(z)
    if not roots:
        raise PackageError("No problem.yaml in the zip — is this a problem package?")
    if len(roots) > MAX_PROBLEMS:
        raise PackageError(f"The zip holds more than {MAX_PROBLEMS} problems — import it in parts")
    defined = defined_language_keys if defined_language_keys is not None else language_keys
    result = ParseResult()
    for root in roots:
        label = posixpath.basename(root) or "package"
        try:
            result.problems.append(
                _parse_problem(z, root, default_time_limit_ms=default_time_limit_ms,
                               language_keys=language_keys, defined_language_keys=defined)
            )
        except Refused as exc:
            result.refused.append({"name": label, "reason": str(exc)})
        except PackageError:
            raise
        except Exception:  # noqa: BLE001 — one malformed problem mustn't sink the rest
            logger.exception("problem package: %s couldn't be read", label)
            result.refused.append({
                "name": label,
                "reason": "Its files couldn't be read — a value in problem.yaml or a test "
                          "group may be malformed",
            })
    return result


def _parse_problem(
    z: _Zip, root: str, *, default_time_limit_ms: int | None, language_keys: set[str],
    defined_language_keys: set[str],
) -> ParsedProblem:
    meta = _yaml(z, posixpath.join(root, "problem.yaml"), root)
    warnings: list[str] = []
    _check_type(z, root, meta, warnings)

    flags = _validator_flags(z, root, meta, warnings)
    compare_mode, tolerance, case_insensitive = _compare_settings(flags, warnings)

    statement, files, tex_name = _statement(z, root, meta, warnings)
    name = _name(meta) or tex_name or posixpath.basename(root) or "Imported problem"

    limits = meta.get("limits") if isinstance(meta.get("limits"), dict) else {}
    time_limit_ms = _time_limit(z, root, limits, default_time_limit_ms, warnings)
    memory_mb = _int_limit(limits.get("memory"), 16, 8192, "memory", "MB", warnings)
    output_mb = _int_limit(limits.get("output"), 1, 256, "output", "MB", warnings)

    testcases = _testcases(z, root)
    attached = _attachments(z, root)
    # One file per name. A statement source that attachments/ also carries is
    # taken from attachments/: in a Flagpost export that's the verbatim
    # original, and statement/ holds the regenerated Markdown.
    sources = {f.filename for f in files if f.content_type.startswith("text/plain")}
    originals = {f.filename for f in attached if f.filename in sources}
    names: set[str] = set()
    files = [
        f for f in [*(f for f in files if f.filename not in originals), *attached]
        if not (f.filename in names or names.add(f.filename))
    ]
    kept = sum(1 for f in files if any(f is a for a in attached))
    if kept:
        warnings.append(f"{kept} file(s) from attachments/ were attached for competitors.")
    allowed = _languages(meta, defined_language_keys, warnings)
    # The reference must be one the problem accepts, or the check can't run it.
    reference = _reference(
        z, root, language_keys & set(allowed) if allowed else language_keys, warnings
    )
    _licence(meta, statement, warnings)
    _ignored_extras(z, root, warnings)

    return ParsedProblem(
        root=root,
        name=name.replace("\x00", "")[:200],
        statement=statement,
        files=files,
        time_limit_ms=time_limit_ms,
        memory_limit_mb=memory_mb,
        output_limit_kb=output_mb * 1024 if output_mb else None,
        compare_mode=compare_mode,
        float_tolerance=tolerance,
        case_insensitive=case_insensitive,
        allowed_languages=allowed,
        testcases=testcases,
        reference_language=reference[0] if reference else None,
        reference_source=reference[1].replace("\x00", "") if reference else None,
        warnings=warnings,
    )


def _types(meta: dict) -> set[str]:
    raw = meta.get("type")
    values = raw if isinstance(raw, list) else str(raw or "pass-fail").split()
    return {str(v).strip().lower() for v in values}


def _check_type(z: _Zip, root: str, meta: dict, warnings: list[str]) -> None:
    unsupported = _types(meta) & _UNSUPPORTED_TYPES
    validation = str(meta.get("validation") or "default").lower().split()
    if "interactive" in validation:
        unsupported.add("interactive")
    if "score" in validation:
        unsupported.add("scoring")
    if unsupported:
        kinds = ", ".join(sorted(unsupported))
        article = "an" if kinds[0] in "aeiou" else "a"
        raise Refused(f"It's {article} {kinds} problem — Flagpost judges pass/fail problems only")
    checker = _under(z, root, "output_validator", "output_validators")
    custom = "custom" in validation or bool(checker)
    if custom:
        if checker and _is_bundled_standard_checker(z, root, checker):
            warnings.append(
                "The package bundles a copy of the standard output checker; "
                "Flagpost's standard checking is used instead."
            )
        else:
            raise Refused(
                "It uses its own output checker — Flagpost can only judge with the standard checks"
            )
    for name in _under(z, root, "include"):
        if not name.endswith(".gitkeep"):
            raise Refused("It adds code to every submission (include/) — not supported")
    if meta.get("allow_file_writing"):
        raise Refused("It lets submissions write files — not supported")


def _is_bundled_standard_checker(z: _Zip, root: str, files: list[str]) -> bool:
    """A verbatim copy of the standard checker, which real packages ship as a
    'custom' one: a single default_validator source (plus build scripts) whose
    text handles the standard flags."""
    sources = [f for f in files if not f.endswith((".gitkeep", "build", "run", "Makefile"))]
    if not sources or not all("default_validator" in posixpath.basename(f) for f in sources):
        return False
    try:
        text = b"".join(z.read(f, root, MAX_MANIFEST_BYTES) for f in sources).decode("utf-8", "replace")
    except Refused:
        return False
    return all(flag in text for flag in ("case_sensitive", "space_change_sensitive", "float_tolerance"))


# --- output checking ------------------------------------------------------------


def _validator_flags(z: _Zip, root: str, meta: dict, warnings: list[str]) -> list[str]:
    """The standard checker's flags, as each test gets them: a testdata.yaml /
    test_group.yaml applies to its directory and everything under it (the
    nearest one wins), a per-case <case>.yaml (2025-09) to that case alone —
    and legacy problem.yaml ``validator_flags`` always come first, *added to*
    those (the checker reads its arguments in order, so a later value wins). Flagpost has one setting per problem, so every secret
    test must end up with the same flags; samples that differ are judged with
    the secret tests' setting, with a note."""
    base: tuple[str, ...] = tuple(str(meta.get("validator_flags") or "").split())
    by_dir: dict[str, tuple[str, ...]] = {}
    by_case: dict[str, tuple[str, ...]] = {}
    for name in _under(z, root, "data"):
        base_name = posixpath.basename(name)
        group_file = base_name in ("testdata.yaml", "test_group.yaml")
        if not group_file and not (base_name.endswith(".yaml") and _is_case_yaml(z, name)):
            continue
        group = _yaml(z, name, root)
        if group.get("args"):
            raise Refused("Its tests pass arguments to the program — not supported")
        tokens = None
        for key in ("output_validator_flags", "output_validator_args"):
            value = group.get(key)
            if value is not None:
                tokens = tuple(str(v) for v in value) if isinstance(value, list) else tuple(str(value).split())
        if tokens is None:
            continue
        if group_file:
            by_dir[posixpath.dirname(name)] = tokens
        else:
            by_case[name[: -len(".yaml")]] = tokens

    data_dir = posixpath.join(root, "data") if root else "data"

    def effective(case_in: str) -> tuple[str, ...]:
        stem = case_in[: -len(".in")]
        if stem in by_case:
            return base + by_case[stem]
        directory = posixpath.dirname(case_in)
        while True:  # up to data/ itself; the nearest group's setting wins
            if directory in by_dir:
                return base + by_dir[directory]
            if not directory.startswith(data_dir + "/"):
                return base
            directory = posixpath.dirname(directory)

    secret = {effective(n) for n in _under(z, root, "data/secret") if n.endswith(".in")}
    if len(secret) > 1:
        raise Refused("Different tests are checked differently — Flagpost has one setting per problem")
    flags = next(iter(secret)) if secret else base
    samples = {effective(n) for n in _under(z, root, "data/sample") if n.endswith(".in")}
    if samples - {flags}:
        warnings.append(
            "The package checks its samples differently from its secret tests; "
            "Flagpost checks them all the same way, like the secret tests."
        )
    return list(flags)


def _is_case_yaml(z: _Zip, name: str) -> bool:
    """A per-case <case>.yaml (2025-09) — one that sits beside an .in."""
    stem = name[: -len(".yaml")]
    return stem + ".in" in z.infos


def _compare_settings(flags: list[str], warnings: list[str]) -> tuple[str, float | None, bool]:
    case_insensitive = "case_sensitive" not in flags
    space_sensitive = "space_change_sensitive" in flags
    values: dict[str, float] = {}
    for key in ("float_tolerance", "float_absolute_tolerance", "float_relative_tolerance"):
        if key in flags:
            i = len(flags) - 1 - flags[::-1].index(key)  # the last one given wins
            try:
                values[key] = float(flags[i + 1])
            except (IndexError, ValueError) as exc:
                raise Refused(f"Its checker flag {key} has no valid value") from exc
    if not values:
        return ("exact" if space_sensitive else "token"), None, case_insensitive
    if space_sensitive:
        raise Refused("It checks spacing exactly and numbers approximately — not supported together")
    if "float_tolerance" in values:
        tolerance = values["float_tolerance"]
    else:
        absolute = values.get("float_absolute_tolerance")
        relative = values.get("float_relative_tolerance")
        tolerance = max(v for v in (absolute, relative) if v is not None)
        if absolute != relative:
            warnings.append(
                f"Numbers are checked a little more leniently than the package asks: "
                f"within {tolerance:g}, absolutely or relatively."
            )
    if not 0 < tolerance <= 1:
        raise Refused(f"Its number tolerance ({tolerance:g}) is outside what Flagpost supports (0–1)")
    return "float", tolerance, case_insensitive


# --- limits ---------------------------------------------------------------------

# [ \t], not \s: under MULTILINE, \s* at each line start would also eat the
# newlines after it and backtrack through them — quadratic on a run of blank
# lines, and the regex engine holds the GIL while it runs.
_INI_TIMELIMIT = re.compile(rb"^[ \t]*timelimit[ \t]*=[ \t]*['\"]?([0-9.]+)", re.IGNORECASE | re.MULTILINE)


def _time_limit(
    z: _Zip, root: str, limits: dict, default_ms: int | None, warnings: list[str]
) -> int | None:
    """The package's own time limit if it has one: problem.yaml (2025-09), a
    root .timelimit file, or a judge's .ini ``timelimit =`` key — the format
    itself derives limits from reference run times, so most packages carry
    none. Otherwise the import form's answer (owner decision)."""
    seconds: float | None = None
    source = ""
    if limits.get("time_limit") is not None:
        seconds, source = _seconds(limits["time_limit"]), "problem.yaml"
    if seconds is None:
        path = posixpath.join(root, ".timelimit")
        if path in z.infos:
            seconds, source = _seconds(z.read(path, root, 64).decode("utf-8", "replace").strip()), ".timelimit"
    if seconds is None:
        for name in z.children.get(root, []):
            if name.endswith(".ini"):
                match = _INI_TIMELIMIT.search(z.read(name, root, MAX_MANIFEST_BYTES))
                if match:
                    seconds, source = _seconds(match.group(1).decode()), posixpath.basename(name)
                    break
    if seconds is None:
        if default_ms is not None:
            warnings.append(
                f"The package doesn't set a time limit; using {default_ms / 1000:g} s from the "
                "import form. Run the reference check to confirm it suits the problem."
            )
            return default_ms
        warnings.append(
            "The package doesn't set a time limit, so the site default applies. "
            "Run the reference check to confirm it suits the problem."
        )
        return None
    ms = round(seconds * 1000)
    clamped = min(max(ms, 100), 60_000)
    if clamped != ms:
        warnings.append(f"Its time limit ({seconds:g} s, from {source}) was adjusted to {clamped / 1000:g} s.")
    return clamped


def _seconds(value: object) -> float | None:
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def _int_limit(value: object, low: int, high: int, what: str, unit: str, warnings: list[str]) -> int | None:
    if value is None:
        return None
    try:
        number = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        warnings.append(f"Its {what} limit ({str(value)[:40]!r}) isn't a number; the site default applies.")
        return None
    clamped = min(max(number, low), high)
    if clamped != number:
        warnings.append(f"Its {what} limit ({number} {unit}) was adjusted to {clamped} {unit}.")
    return clamped


def _languages(meta: dict, language_keys: set[str], warnings: list[str]) -> list[str] | None:
    raw = meta.get("languages")
    if raw is None or raw == "all":
        return None
    codes = [str(c) for c in (raw if isinstance(raw, list) else str(raw).split())]
    known = [c for c in codes if c in language_keys]
    if not known:
        # Nothing to restrict to: say plainly that the restriction is gone.
        warnings.append(
            f"It only allows {', '.join(codes)}, which this site doesn't have, so for now it "
            "accepts every language. Set its allowed languages before publishing."
        )
        return None
    if len(known) != len(codes):
        missing = sorted(set(codes) - set(known))
        warnings.append(f"Languages this site doesn't have were left out: {', '.join(missing)}.")
    return known


# --- statement ------------------------------------------------------------------


def _name(meta: dict) -> str | None:
    raw = meta.get("name")
    if isinstance(raw, dict):
        raw = raw.get("en") or next(iter(raw.values()), None)
    return str(raw).strip() or None if raw else None


def _statement(z: _Zip, root: str, meta: dict, warnings: list[str]) -> tuple[dict, list[PackageFile], str | None]:
    """Convert the statement to rich text (best effort, owner decision) and
    keep the original file — plus a PDF and images — as attachments."""
    from utils.statement_convert import latex_problem_name, latex_to_doc, markdown_to_doc

    members = _under(z, root, "statement", "problem_statement")
    # problem.<lang>.<kind> or problem.<kind>, by language: English (or none)
    # first, else the first language listed.
    by_lang: dict[str, dict[str, str]] = {}
    for name in members:
        base = posixpath.basename(name)
        parts = base.split(".")
        if parts[0] != "problem" or len(parts) not in (2, 3) or parts[-1] not in STATEMENT_KINDS:
            continue
        lang = parts[1] if len(parts) == 3 else ""
        by_lang.setdefault(lang, {})[parts[-1]] = name
    files: list[PackageFile] = []
    if not by_lang:
        warnings.append("The package has no statement; add one before publishing.")
        return _note_doc("No statement was included in the package."), files, None
    langs = sorted(by_lang, key=lambda lang: (lang not in ("", "en"), lang))
    chosen = langs[0]
    if len(langs) > 1:
        warnings.append(
            f"Only the {chosen or 'default'} statement was imported "
            f"(also in: {', '.join(lang or 'default' for lang in langs[1:])})."
        )
    kinds = by_lang[chosen]
    tex_name: str | None = None
    doc: dict | None = None
    statement_text: str | None = None
    for kind in ("md", "tex"):
        if kind not in kinds:
            continue
        raw = z.read(kinds[kind], root, MAX_STATEMENT_BYTES)
        text = statement_text = raw.decode("utf-8", "replace").replace("\x00", "")
        if kind == "md":
            text = _substitute_constants(text, meta)
            doc = markdown_to_doc(_strip_sample_markers(text))
        else:
            tex_name = latex_problem_name(text)
            doc = latex_to_doc(_strip_sample_markers(text))
        files.append(PackageFile(posixpath.basename(kinds[kind]), raw, "text/plain; charset=utf-8"))
        warnings.append(
            "The statement was converted from "
            + ("Markdown" if kind == "md" else "LaTeX")
            + "; maths appears as written. Review it before publishing — the original is attached."
        )
        break
    if "pdf" in kinds:
        files.append(PackageFile(posixpath.basename(kinds["pdf"]), z.read(kinds["pdf"], root, MAX_ATTACHMENT_BYTES), "application/pdf"))
        if doc is None:
            doc = _note_doc("The problem statement is attached as a PDF.")
            warnings.append("The statement is a PDF; it's attached, and the description just points to it.")
    # The images the statement's source actually references, resolved as paths
    # inside the statement directory (subfolders included; LaTeX may leave the
    # extension off). Anything else there — a jury solution's figures, drafts —
    # stays out of competitors' reach.
    statement_dir = posixpath.dirname(next(iter(kinds.values())))
    seen: set[str] = set()
    for ref in _image_refs(statement_text or ""):
        target = posixpath.normpath(posixpath.join(statement_dir, ref))
        if "://" in ref or ref.startswith("/") or not target.startswith(statement_dir + "/"):
            continue
        ext = posixpath.splitext(target)[1].lower()
        for candidate in [target] if ext in _IMAGE_TYPES else [target + e for e in _IMAGE_TYPES]:
            if candidate in z.infos and candidate not in seen:
                seen.add(candidate)
                kind = _IMAGE_TYPES[posixpath.splitext(candidate)[1].lower()]
                files.append(PackageFile(posixpath.basename(candidate), z.read(candidate, root, MAX_ATTACHMENT_BYTES), kind))
                break
    return doc or _note_doc(""), files, tex_name


# Image references in a statement's source. Possessive/bounded throughout:
# these run over untrusted text with the GIL held.
_IMAGE_REF_PATTERNS = (
    re.compile(r"\\includegraphics\s*+(?:\[[^\]]{0,500}+\])?\s*+\{([^}]{1,500}+)\}"),
    re.compile(r"\\illustration\s*+\{[^}]{0,100}+\}\s*+\{([^}]{1,500}+)\}"),
    re.compile(r"!\[[^\]]{0,500}+\]\(\s*+<?([^)\s>]{1,500}+)"),
    re.compile(r"<img\b[^>]{0,500}?\bsrc\s*+=\s*+[\"']([^\"']{1,500}+)", re.IGNORECASE),
)


def _image_refs(source: str) -> list[str]:
    return [m.group(1).strip() for pattern in _IMAGE_REF_PATTERNS for m in pattern.finditer(source)]


def _note_doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}] if text else []}]}


def _substitute_constants(text: str, meta: dict) -> str:
    """``{{name}}`` → the constant's value, in one pass: a value is never
    itself expanded (chained replacement could double the text per constant)."""
    constants = meta.get("constants")
    if not isinstance(constants, dict):
        return text
    values = {str(k): str(v)[:200] for k, v in constants.items()}
    return re.sub(r"\{\{(\w{1,64})\}\}", lambda m: values.get(m.group(1), m.group(0)), text)


def _strip_sample_markers(text: str) -> str:
    # Where a judge would splice in the examples; Flagpost shows them itself.
    for marker in ("{{nextsample}}", "{{remainingsamples}}", "\\nextsample", "\\remainingsamples"):
        text = text.replace(marker, "")
    return text


def _licence(meta: dict, statement: dict, warnings: list[str]) -> None:
    """Credit the authors where the licence asks for it (CC BY / BY-SA)."""
    licence = str(meta.get("license") or "unknown").lower()
    if licence == "unknown":
        warnings.append("The package's licence is unknown — make sure you may use it.")
        return
    credits = meta.get("author") or meta.get("credits")
    if isinstance(credits, dict):
        authors = credits.get("authors")
        credits = ", ".join(map(str, authors)) if isinstance(authors, list) else authors
    source = meta.get("source")
    if isinstance(source, dict):
        source = source.get("name")
    elif isinstance(source, list):
        source = ", ".join(str(s.get("name") if isinstance(s, dict) else s) for s in source)
    if licence.startswith("cc by") or credits or source:
        parts = [p for p in (
            f"Author: {credits}" if credits else "",
            f"Source: {source}" if source else "",
            f"Licence: {licence.upper() if licence.startswith('cc') else licence}",
        ) if p]
        statement.setdefault("content", []).append(
            {"type": "paragraph", "content": [{"type": "text", "text": " · ".join(parts), "marks": [{"type": "italic"}]}]}
        )


# --- tests and files --------------------------------------------------------------


def _testcases(z: _Zip, root: str) -> list[td.Testcase]:
    cases: list[td.Testcase] = []
    total = 0
    for group, sample in (("sample", True), ("secret", False)):
        names = _under(z, root, f"data/{group}")
        if any(n.endswith(".interaction") for n in names):
            raise Refused("Its tests are interactive — not supported")
        if any(re.search(r"\.files(/|$)", n) for n in names):  # <case>.files/
            raise Refused("Its tests give the program files to read — not supported")
        ins = sorted(n for n in names if n.endswith(".in"))
        for name in ins:
            answer = name[: -len(".in")] + ".ans"
            if answer not in z.infos:
                raise Refused(f"{_short(name, root)} has no matching .ans")
            data_in = z.read(name, root, td.MAX_FILE_BYTES)
            data_ans = z.read(answer, root, td.MAX_FILE_BYTES)
            total += len(data_in) + len(data_ans)
            if total > td.MAX_TOTAL_BYTES:
                raise Refused(
                    f"Its test data is over {_mb(td.MAX_TOTAL_BYTES)} — "
                    "Flagpost's limit per problem. Trim the tests and import it again."
                )
            cases.append(td.Testcase(id=uuid4().hex, sample=sample, input=data_in, answer=data_ans))
    if not any(not c.sample for c in cases):
        raise Refused("It has no secret tests (data/secret)")
    return cases


def _attachments(z: _Zip, root: str) -> list[PackageFile]:
    files = []
    for name in _under(z, root, "attachments"):
        rel = _short(name, root)
        if rel.count("/") != 1 or posixpath.basename(name).startswith("."):
            continue  # templates/ and dotfiles aren't for competitors
        files.append(PackageFile(posixpath.basename(name), z.read(name, root, MAX_ATTACHMENT_BYTES), "application/octet-stream"))
    return files


def _reference(z: _Zip, root: str, language_keys: set[str], warnings: list[str]) -> tuple[str, str] | None:
    """An accepted solution in a language this site has, kept so the author
    can run the reference check (Python 2 skipped; Java only with a ``Main``
    class, which Flagpost's Java preset expects)."""
    candidates: dict[str, tuple[str, str]] = {}
    for name in _under(z, root, "submissions/accepted"):
        if name.count("/") - (root.count("/") + 1 if root else 0) != 2:
            continue  # multi-file submissions live in a directory
        ext = posixpath.splitext(name)[1]
        lang = _EXT_LANG.get(ext) or _EXT_LANG.get(ext.lower())
        if lang is None or lang in candidates:
            continue
        if lang == "python3" and "python3" not in language_keys and "pypy3" in language_keys:
            lang = "pypy3"
        if lang not in language_keys:
            continue
        try:
            source = z.read(name, root, MAX_SOURCE_BYTES).decode("utf-8")
        except (Refused, UnicodeDecodeError):
            continue
        if lang in ("python3", "pypy3") and (source.startswith("#!") and "python2" in source.split("\n", 1)[0]):
            continue
        if lang == "java" and not re.search(r"\bclass\s+Main\b", source):
            continue
        candidates[lang] = (lang, source)
    for lang in (*_REFERENCE_ORDER, "pypy3"):
        if lang in candidates:
            warnings.append(f"Its accepted {lang} solution is kept for the reference check.")
            return candidates[lang]
    return None


def _ignored_extras(z: _Zip, root: str, warnings: list[str]) -> None:
    ignored = []
    names = z.names()
    for marker, label in (
        (".hint", "hints"), (".desc", "test descriptions"), (".out", "alternative outputs"),
        (".statement", "statement-only examples"), (".download", "download-only examples"),
    ):
        if any(n.startswith(root) and n.endswith(marker) and "/data/" in n for n in names):
            ignored.append(label)
    for directory, label in (
        ("input_validators", "input validators"), ("input_format_validators", "input validators"),
        ("generators", "generators"), ("data/invalid_input", "invalid-input tests"),
        ("data/invalid_output", "invalid-output tests"), ("data/valid_output", "valid-output tests"),
    ):
        if _under(z, root, directory) and label not in ignored:
            ignored.append(label)
    if ignored:
        warnings.append(f"Not used by Flagpost, so left out: {', '.join(ignored)}.")


# --- creating the draft challenges -----------------------------------------------


async def create_problems(db, storage, *, competition_id: str, parsed: list[ParsedProblem]) -> dict:
    """Turn parsed problems into **draft** programming challenges — the publish
    gate wants a review of the converted statement and the time limit first —
    in one transaction, emitting no per-row events (atomic authoring, like the
    challenge importer). A problem whose title already exists is skipped.
    Objects stored before a failure are deleted again, so an aborted import
    leaves nothing behind."""
    import asyncio

    from sqlalchemy import select

    from models.attachment import Attachment
    from models.challenge import Challenge
    from models.judge_problem import JudgeProblem
    from utils.uploads import safe_filename

    existing = set(
        (await db.scalars(select(Challenge.title).where(Challenge.competition_id == competition_id))).all()
    )
    created: list[dict] = []
    skipped: list[dict] = []
    stored: list[str] = []
    try:
        for p in parsed:
            if p.name in existing:
                skipped.append({"name": p.name, "reason": "A challenge with this title already exists"})
                continue
            existing.add(p.name)
            challenge = Challenge(
                competition_id=competition_id,
                title=p.name,
                description=p.statement,
                points=100,
                flag_type="programming",
                state="draft",
            )
            db.add(challenge)
            await db.flush()
            key = td.new_key(competition_id, challenge.id)
            blob = await asyncio.to_thread(td.build_zip, p.testcases)
            await asyncio.to_thread(storage.put, key, blob, "application/zip")
            stored.append(key)
            db.add(
                JudgeProblem(
                    competition_id=competition_id,
                    challenge_id=challenge.id,
                    time_limit_ms=p.time_limit_ms,
                    memory_limit_mb=p.memory_limit_mb,
                    output_limit_kb=p.output_limit_kb,
                    compare_mode=p.compare_mode,
                    float_tolerance=p.float_tolerance,
                    case_insensitive=p.case_insensitive,
                    allowed_languages=p.allowed_languages,
                    reference_language=p.reference_language,
                    reference_source=p.reference_source,
                    object_key=key,
                    testcases=td.manifest(p.testcases),
                )
            )
            for f in p.files:
                name = safe_filename(f.filename.replace("\x00", ""))[-200:]
                file_key = f"{competition_id}/{challenge.id}/{uuid4().hex}_{name}"
                await asyncio.to_thread(storage.put, file_key, f.data, f.content_type)
                stored.append(file_key)
                db.add(
                    Attachment(
                        competition_id=competition_id,
                        challenge_id=challenge.id,
                        filename=name,
                        object_key=file_key,
                        content_type=f.content_type,
                        size_bytes=len(f.data),
                    )
                )
            created.append({
                "name": p.name,
                "challenge_id": challenge.id,
                "tests": len(p.testcases),
                "warnings": p.warnings,
            })
        await db.commit()
    except BaseException:
        await db.rollback()
        for key in stored:
            try:
                await asyncio.shield(asyncio.to_thread(storage.delete, key))
            except Exception:  # noqa: BLE001 — never mask the original failure
                pass
        raise
    return {"created": created, "skipped": skipped}


# --- export -------------------------------------------------------------------------


class ExportError(Exception):
    """An export that can't be made faithfully (the message names the problem)."""


@dataclass
class ExportProblem:
    name: str
    uuid: str
    statement: dict
    time_limit_ms: int
    memory_limit_mb: int
    output_limit_kb: int
    compare_mode: str
    float_tolerance: float | None
    case_insensitive: bool
    allowed_languages: list[str] | None
    testdata_key: str | None  # the stored zip (data/sample|secret/NNN.in|.ans)
    testcases: list[dict] = field(default_factory=list)  # its manifest (judge_testdata)
    files: list[tuple[str, str]] = field(default_factory=list)  # (filename, object key)
    reference: tuple[str, str] | None = None  # (filename, source)


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "", name.lower())[:40] or "problem"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}{n}", n + 1
    taken.add(slug)
    return slug


def checker_args(compare_mode: str, float_tolerance: float | None, case_insensitive: bool) -> list[str]:
    """Flagpost's comparison as the standard checker's arguments."""
    args: list[str] = []
    if not case_insensitive:
        args.append("case_sensitive")
    if compare_mode == "exact":
        args.append("space_change_sensitive")
    elif compare_mode == "float":
        args += ["float_tolerance", repr(float(float_tolerance or 1e-6))]
    return args


def build_export(problems: list[ExportProblem], storage, out: IO[bytes]) -> None:
    """Write a zip of 2025-09 problem packages to ``out``, one directory each:
    problem.yaml (name, uuid, the effective limits), a Markdown statement, the
    test data, the checker settings, the attachments, and the kept reference
    solution as an accepted submission. Each problem's files are fetched from
    ``storage`` as it's written, so a contest's worth of test data is never in
    memory at once. Flagpost has no input validators, so a strict verifier may
    flag that; other judges import it as is."""
    from utils.statement_convert import doc_to_markdown

    taken: set[str] = set()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in problems:
            slug = _slug(p.name, taken)
            seconds = p.time_limit_ms / 1000
            limits: dict = {
                "time_limit": int(seconds) if seconds == int(seconds) else seconds,
                "memory": p.memory_limit_mb,
                # MiB in the format; round up so nothing that passes here fails there.
                "output": max(1, -(-p.output_limit_kb // 1024)),
            }
            if seconds != int(seconds):
                limits["time_resolution"] = 0.001
            meta: dict = {
                "problem_format_version": "2025-09",
                "name": p.name,
                "uuid": p.uuid,
                "limits": limits,
            }
            if p.allowed_languages:
                meta["languages"] = list(p.allowed_languages)
            zf.writestr(f"{slug}/problem.yaml", yaml.safe_dump(meta, sort_keys=False, allow_unicode=True))
            zf.writestr(f"{slug}/statement/problem.en.md", doc_to_markdown(p.statement))
            if p.testdata_key:
                _export_testdata(zf, slug, p, storage)
            args = checker_args(p.compare_mode, p.float_tolerance, p.case_insensitive)
            if args:
                group = yaml.safe_dump({"output_validator_args": args}, sort_keys=False)
                for folder in ("sample", "secret"):
                    zf.writestr(f"{slug}/data/{folder}/test_group.yaml", group)
            used: set[str] = set()
            for filename, key in p.files:
                try:
                    blob = storage.get(key)
                except Exception:  # noqa: BLE001 — a missing attachment shouldn't sink the export
                    logger.warning("problem export: attachment %s of %s is missing", filename, p.name)
                    continue
                zf.writestr(f"{slug}/attachments/{_unique_member(filename, used)}", blob)
            if p.reference:
                filename, source = p.reference
                zf.writestr(f"{slug}/submissions/accepted/{_safe_member(filename)}", source)


def _export_testdata(zf: zipfile.ZipFile, slug: str, p: ExportProblem, storage) -> None:
    """The stored test data in judging order, read through the judge's own
    bounded loader. Every name is made here from the case's position, never
    taken from the stored zip — a restored backup decides those
    (GHSA-wvjv-56qv-9v42) — and numbered so name order is judging order however
    many tests there are (``1000.in`` would sort before ``101.in``)."""
    try:
        cases = td.load(storage, p.testdata_key, p.testcases)
    except Exception as exc:  # noqa: BLE001
        raise ExportError(
            f"The test data for “{p.name}” couldn't be read from storage — "
            "upload it again, then export."
        ) from exc
    for sample, folder in ((True, "sample"), (False, "secret")):
        group = [c for c in cases if c.sample == sample]
        width = max(3, len(str(len(group))))
        for k, case in enumerate(group, start=1):
            stem = f"{slug}/data/{folder}/{k:0{width}d}"
            zf.writestr(f"{stem}.in", case.input)
            zf.writestr(f"{stem}.ans", case.answer)


def _unique_member(filename: str, used: set[str]) -> str:
    return unique_name(_safe_member(filename), used)


def _safe_member(filename: str) -> str:
    """A flat, format-legal file name (letters, digits, _ . -)."""
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", posixpath.basename(filename)).lstrip(".-")
    return name[:255] or "file"
