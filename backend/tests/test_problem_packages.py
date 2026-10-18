"""Problem packages (#451): importing the open ICPC/Kattis problem package
format as draft programming challenges — faithfully or not at all — and
exporting them back out. Packages are built in memory by ``package_fixtures``;
two real ones are vendored (``fixtures/problem_packages``)."""

import io
import struct
import time
import zipfile

import pytest
import yaml
from sqlalchemy import select

from db import SessionLocal
from models.attachment import Attachment
from models.challenge import Challenge
from models.judge_problem import JudgeProblem
from tests import package_fixtures as pf
from tests.test_judge_submissions import _auth, _player, _setup
from utils import judge_testdata as td
from utils import problem_package as pp

import main  # noqa: F401, E402

LANGS = {"python3", "cpp", "c", "java", "kotlin"}


def _parse(blob: bytes, *, default_ms: int | None = None, langs=LANGS) -> pp.ParseResult:
    return pp.parse_package(blob, default_time_limit_ms=default_ms, language_keys=set(langs))


def _one_with(blob: bytes, *, langs: set[str], defined: set[str]) -> pp.ParsedProblem:
    result = pp.parse_package(blob, default_time_limit_ms=None, language_keys=langs,
                              defined_language_keys=defined)
    assert result.refused == [], result.refused
    [problem] = result.problems
    return problem


def _one(blob: bytes, **kw) -> pp.ParsedProblem:
    result = _parse(blob, **kw)
    assert result.refused == [], result.refused
    [problem] = result.problems
    return problem


def _refused(blob: bytes) -> str:
    result = _parse(blob)
    assert result.problems == []
    [refused] = result.refused
    return refused["reason"]


def _text(doc: dict) -> str:
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                out.append(node.get("text", ""))
            for child in node.get("content", []) or []:
                walk(child)

    walk(doc)
    return " ".join(out)


# --- reading a package ----------------------------------------------------------------


def test_a_legacy_package():
    p = _one(pf.legacy_passfail())
    assert p.name == pf.SUM_NAME
    assert p.memory_limit_mb == 512
    # The standard checker ignores letter case unless asked not to.
    assert p.compare_mode == "token" and p.case_insensitive is True
    assert [c.sample for c in p.testcases] == [True, False, False]
    assert p.testcases[1].input == b"10 20\n" and p.testcases[1].answer == b"30\n"
    # The LaTeX statement is converted and the original kept.
    assert "Read two integers and print their sum" in _text(p.statement)
    assert any(f.filename == "problem.en.tex" for f in p.files)
    assert p.reference_language == "python3" and "print(a + b)" in p.reference_source
    assert any("time limit" in w for w in p.warnings)


def test_a_2025_package():
    p = _one(pf.v2025_passfail())
    assert p.name == pf.SUM_NAME and p.time_limit_ms == 2500
    # test_group.yaml asks for case-sensitive checking.
    assert p.case_insensitive is False
    assert "Read two integers" in _text(p.statement)


@pytest.mark.parametrize(
    "blob, expected",
    [(pf.with_timelimit_file("3"), 3000), (pf.with_ini_timelimit("4"), 4000)],
    ids=["timelimit-file", "ini-timelimit"],
)
def test_time_limit_files(blob, expected):
    assert _one(blob).time_limit_ms == expected


def test_no_time_limit_takes_the_form_answer():
    p = _one(pf.legacy_passfail(), default_ms=1500)
    assert p.time_limit_ms == 1500
    assert any("import form" in w for w in p.warnings)
    assert _one(pf.legacy_passfail()).time_limit_ms is None


def test_float_tolerances():
    p = _one(pf.float_tolerance())
    assert p.compare_mode == "float" and p.float_tolerance == pytest.approx(1e-6)
    lenient = _one(pf.abs_only_tolerance())
    assert lenient.compare_mode == "float" and lenient.float_tolerance == pytest.approx(1e-3)
    assert any("leniently" in w for w in lenient.warnings)


def test_case_sensitive_flag():
    assert _one(pf.case_sensitive_flag()).case_insensitive is False


def test_test_groups_flatten_in_order():
    # Written to the zip in reverse; judged in path order.
    p = _one(pf.test_groups())
    assert [c.answer.decode() for c in p.testcases] == pf.TEST_GROUPS_ANSWER_ORDER


def test_a_symlinked_case_is_followed_inside_the_package():
    p = _one(pf.symlinked_case())
    samples = [c for c in p.testcases if c.sample]
    secrets = [c for c in p.testcases if not c.sample]
    assert any(s.input == samples[0].input for s in secrets)


def test_a_link_into_another_problem_is_refused():
    result = _parse(pf.cross_package_symlink())
    assert [p.name for p in result.problems] == ["Alpha"]
    assert "outside the package" in result.refused[0]["reason"]


def test_contest_zip_with_several_problems():
    result = _parse(pf.multi_problem())
    assert sorted(p.name for p in result.problems) == ["Alpha", "Beta"]


def test_pdf_statement_is_attached():
    p = _one(pf.pdf_statement())
    assert any(f.content_type == "application/pdf" for f in p.files)
    assert "PDF" in _text(p.statement)


def test_name_from_the_statement():
    assert _one(pf.no_name()).name == pf.SUM_NAME


def test_unknown_keys_are_tolerated():
    assert _one(pf.unknown_key()).name == pf.SUM_NAME


def test_licences():
    assert any("licence is unknown" in w for w in _one(pf.license_unknown()).warnings)
    p = _one(pf.cc_by())
    assert pf.CC_BY_SOURCE in _text(p.statement)


def test_attachments_are_kept():
    p = _one(pf.attachments())
    assert any(f.filename == "testing_tool.py" for f in p.files)


def test_reference_solution_choice():
    p = _one(pf.kotlin_and_python_accepted())
    assert p.reference_language == "python3"
    # Without Python on the site, Kotlin is kept instead (Python 2 is covered
    # by test_reference_language_rules).
    p = _one(pf.kotlin_and_python_accepted(python3=False), langs={"kotlin"})
    assert p.reference_language == "kotlin"
    assert _one(pf.kotlin_and_python_accepted(), langs={"cpp"}).reference_language is None


def test_bundled_copy_of_the_standard_checker_is_accepted():
    for declared in (False, True):
        p = _one(pf.bundled_default_validator(declared_custom=declared))
        assert any("standard output checker" in w for w in p.warnings)


def _pkg(extra: dict | None = None, *, yaml_extra: str = "", **kw) -> bytes:
    """The legacy sum problem with files added (or replaced) and problem.yaml
    lines appended — ``"  time_limit: …"`` continues its ``limits:`` map."""
    files = pf.legacy_files(yaml_extra=yaml_extra, **kw)
    files.update(extra or {})
    return pf.build_package(files, root=pf.SHORTNAME)


def test_time_limit_precedence():
    both = {".timelimit": "3\n", "judge.ini": "timelimit = '4'\n"}
    # problem.yaml beats a .timelimit file, which beats a judge's .ini.
    assert _one(_pkg(both, yaml_extra="  time_limit: 1.5\n"), default_ms=9000).time_limit_ms == 1500
    assert _one(_pkg(both), default_ms=9000).time_limit_ms == 3000
    assert _one(_pkg({"judge.ini": "timelimit = '4'\n"}), default_ms=9000).time_limit_ms == 4000


def test_checker_flags_follow_the_inheritance_rules():
    # Set only on the samples: the secret tests keep the default (ignore case),
    # and that's the problem's setting — the samples' difference is noted.
    p = _one(_pkg({"data/sample/testdata.yaml": "output_validator_flags: case_sensitive\n"}))
    assert p.case_insensitive is True
    assert any("samples differently" in w for w in p.warnings)
    # A data/ level setting reaches every test, nested or not.
    p = _one(_pkg({"data/testdata.yaml": "output_validator_flags: case_sensitive\n"}))
    assert p.case_insensitive is False and not any("samples differently" in w for w in p.warnings)
    # Legacy problem.yaml flags are *added to* a group's, never replaced…
    p = _one(_pkg({"data/secret/testdata.yaml": "output_validator_flags: float_tolerance 1e-4\n"},
                  yaml_extra="validator_flags: case_sensitive\n"))
    assert p.compare_mode == "float" and p.float_tolerance == pytest.approx(1e-4)
    assert p.case_insensitive is False
    p = _one(_pkg({"data/secret/testdata.yaml": "output_validator_flags: case_sensitive\n"},
                  yaml_extra="validator_flags: float_tolerance 1e-6\n"))
    assert p.compare_mode == "float" and p.float_tolerance == pytest.approx(1e-6)
    assert p.case_insensitive is False
    # …and the checker reads them in order, so a later value wins.
    p = _one(_pkg({"data/testdata.yaml": "output_validator_flags: float_tolerance 1e-3\n"},
                  yaml_extra="validator_flags: float_tolerance 1e-6\n"))
    assert p.float_tolerance == pytest.approx(1e-3)
    # A per-case <case>.yaml (2025-09) applies to that case alone.
    refused = _refused(_pkg({"data/secret/1.yaml": "output_validator_args: [case_sensitive]\n"}))
    assert "checked differently" in refused


def test_flags_that_agree_at_several_levels_are_fine():
    p = _one(_pkg({
        "data/sample/testdata.yaml": "output_validator_flags: case_sensitive\n",
        "data/secret/testdata.yaml": "output_validator_flags: case_sensitive\n",
    }))
    assert p.case_insensitive is False


def test_an_empty_include_dir_is_fine():
    assert _one(_pkg({"include/.gitkeep": ""})).name == pf.SUM_NAME


def test_a_problem_yaml_nested_inside_a_problem_is_not_a_problem():
    # "examples/" sorts before "problem.yaml": outermost wins regardless.
    result = _parse(_pkg({"examples/inner/problem.yaml": "name: Inner\n"}))
    assert [p.name for p in result.problems] == [pf.SUM_NAME] and result.refused == []
    # …and a package at the zip root encloses everything in the zip.
    files = pf.legacy_files()
    files["examples/inner/problem.yaml"] = "name: Inner\n"
    result = _parse(pf.build_package(files, root=None))
    assert [p.name for p in result.problems] == [pf.SUM_NAME] and result.refused == []


def test_the_whole_zip_has_an_unpacked_size_cap(monkeypatch):
    # Each member under its own cap, the package as a whole over the aggregate:
    # that ends the import outright rather than refusing one problem.
    monkeypatch.setattr(pp, "MAX_TOTAL_DECOMPRESSED", 200)
    with pytest.raises(pp.PackageError, match="unpacked"):
        _parse(pf.legacy_passfail())


def test_too_many_members(monkeypatch):
    monkeypatch.setattr(pp, "MAX_MEMBERS", 5)
    with pytest.raises(pp.PackageError, match="too many files"):
        _parse(pf.legacy_passfail())


def test_reference_language_rules():
    java = "submissions/accepted/Sol.java"
    # Flagpost's Java preset runs class Main; any other entry class isn't kept.
    assert _one(_pkg({java: "public class Solution {}\n"}), langs={"java"}).reference_language is None
    assert _one(_pkg({java: "public class Main {}\n"}), langs={"java"}).reference_language == "java"
    # A Python 2 solution never stands in for Python 3.
    py2 = _one(_pkg(solution="#!/usr/bin/env python2\nprint 1\n"))
    assert py2.reference_language is None


def test_attachment_templates_and_dotfiles_stay_out():
    p = _one(_pkg({
        "attachments/tool.py": "x\n",
        "attachments/templates/t.py": "x\n",
        "attachments/.hidden": "x\n",
    }))
    names = {f.filename for f in p.files}
    assert "tool.py" in names and "t.py" not in names and ".hidden" not in names


def test_english_statement_first_with_a_note():
    p = _one(_pkg({"problem_statement/problem.de.tex": "\\problemname{Summe}\nDeutsch.\n"}))
    assert "Read two integers" in _text(p.statement) and "Deutsch" not in _text(p.statement)
    assert any("also in: de" in w for w in p.warnings)


def test_a_yaml_alias_bomb_is_refused_before_anything_expands_it():
    # Nine more levels of this would be gigabytes once a value is str()ed; six
    # (half a million nodes) already trip the cap and stay cheap if it's broken.
    levels = ["a0: &a0 [x, x, x, x, x, x, x, x, x]"]
    levels += [f"a{i}: &a{i} [" + ", ".join([f"*a{i - 1}"] * 9) + "]" for i in range(1, 7)]
    blob = _pkg(yaml_extra="\n".join(levels) + "\nlicense: *a6\n")
    started = time.perf_counter()
    assert "aliases" in _refused(blob)
    assert time.perf_counter() - started < 2


def test_one_long_string_aliased_many_times_is_refused():
    # A handful of nodes, but str(meta["validation"]) would be 5 MB of text.
    blob = _pkg(yaml_extra=f"pad: &s {'a' * 50_000}\nvalidation: [" + ", ".join(["*s"] * 100) + "]\n")
    assert "aliases" in _refused(blob)


def test_yaml_nested_too_deeply_is_invalid_yaml():
    files = pf.legacy_files()
    files["problem.yaml"] = "[" * 2000 + "]" * 2000
    assert "isn't valid YAML" in _refused(pf.build_package(files, root=pf.SHORTNAME))


def test_a_hostile_ini_is_linear():
    # A run of blank lines once made the time-limit search quadratic (~3 s
    # here, ~30 min at the 1 MB manifest cap); linear, it's milliseconds.
    started = time.perf_counter()
    p = _one(_pkg({"judge.ini": "\n" * 40_000, "other.ini": " \t\n" * 15_000}), default_ms=1000)
    assert p.time_limit_ms == 1000
    assert time.perf_counter() - started < 1


def test_constants_are_substituted_once():
    files = pf.v2025_files()
    files["statement/problem.en.md"] = "Up to {{n}} items; {{a}} {{missing}}.\n"
    files["problem.yaml"] += "constants:\n  n: 100\n  a: '{{b}}{{b}}'\n  b: '{{n}}'\n"
    p = _one(pf.build_package(files, root=pf.SHORTNAME))
    # A value is never itself expanded (chaining could double the text per step).
    assert "Up to 100 items; {{b}}{{b}} {{missing}}." in _text(p.statement)


def test_allowed_languages_keep_disabled_ones_and_say_when_none_are_left():
    blob = _pkg(yaml_extra="languages: c cpp\n")
    # C is defined here but switched off: the restriction keeps it.
    p = _one_with(blob, langs={"cpp", "python3"}, defined={"c", "cpp", "python3"})
    assert p.allowed_languages == ["c", "cpp"]
    # Nothing the package allows exists here: no restriction — said plainly.
    p = _one_with(_pkg(yaml_extra="languages: c\n"), langs={"python3"}, defined={"python3"})
    assert p.allowed_languages is None
    assert any("accepts every language" in w for w in p.warnings)


def test_the_reference_solution_is_one_the_problem_accepts():
    extra = {"submissions/accepted/Main.java": "public class Main {}\n"}
    langs = {"python3", "java", "cpp"}
    p = _one_with(_pkg(extra, yaml_extra="languages: [cpp, java]\n"), langs=langs, defined=langs)
    assert p.reference_language == "java"
    p = _one_with(_pkg(yaml_extra="languages: [cpp]\n"), langs=langs, defined=langs)
    assert p.reference_language is None  # only a Python solution, and Python isn't allowed


def test_only_the_images_the_statement_uses_are_attached():
    files = pf.v2025_files()
    files["statement/problem.en.md"] = (
        "See ![the tree](tree.png) and <img src='img/leaf.jpg'>. Print the solution.\n"
        "![escape](../data/secret/1.in)\n"
    )
    for name in ("tree.png", "img/leaf.jpg", "solution.png", "unused.png"):
        files[f"statement/{name}"] = b"\x89PNG fake"
    names = {f.filename for f in _one(pf.build_package(files, root=pf.SHORTNAME)).files}
    # Referenced ones, subfolders included; never one that merely shares a word
    # with the prose ("solution"), and never anything outside statement/.
    assert {"tree.png", "leaf.jpg"} <= names
    assert not names & {"solution.png", "unused.png", "1.in"}


def test_latex_image_references_may_leave_the_extension_off():
    files = pf.legacy_files()
    files["problem_statement/problem.en.tex"] = (
        "\\problemname{Sum of Two}\n\\illustration{0.3}{hello}{Credit}\n"
        "\\includegraphics[width=3cm]{figs/tree}\nRead two integers.\n"
    )
    files["problem_statement/hello.jpg"] = b"jpg"
    files["problem_statement/figs/tree.png"] = b"png"
    names = {f.filename for f in _one(pf.build_package(files, root=pf.SHORTNAME)).files}
    assert {"hello.jpg", "tree.png"} <= names


def test_an_attachment_named_like_the_statement_is_kept_once():
    # A Flagpost export: statement/ holds the regenerated Markdown, and
    # attachments/ the verbatim original — which is the one kept.
    files = pf.v2025_files()
    files["attachments/problem.en.md"] = "the verbatim original\n"
    p = _one(pf.build_package(files, root=pf.SHORTNAME))
    kept = [f for f in p.files if f.filename == "problem.en.md"]
    assert [f.data for f in kept] == [b"the verbatim original\n"]
    # The statement itself is still converted from statement/.
    assert "Read two integers" in _text(p.statement)
    assert any("1 file(s) from attachments/" in w for w in p.warnings)


def test_an_unexpected_error_refuses_that_problem_only(monkeypatch):
    real = pp._licence

    def boom(meta, statement, warnings):
        if "Beta" in str(meta.get("name")):
            raise TypeError("malformed")
        return real(meta, statement, warnings)

    monkeypatch.setattr(pp, "_licence", boom)
    result = _parse(pf.multi_problem())
    assert [p.name for p in result.problems] == ["Alpha"]
    assert "couldn't be read" in result.refused[0]["reason"]


def test_too_many_problems(monkeypatch):
    monkeypatch.setattr(pp, "MAX_PROBLEMS", 1)
    with pytest.raises(pp.PackageError, match="more than 1 problems"):
        _parse(pf.multi_problem())


def test_an_oversized_read_still_counts_toward_the_unpacked_cap(monkeypatch):
    # Each problem could otherwise inflate one over-cap member for free.
    monkeypatch.setattr(pp, "MAX_TOTAL_DECOMPRESSED", 1024 * 1024)
    with pytest.raises(pp.PackageError, match="unpacked"):
        _parse(pf.zip_bomb())


def test_non_finite_limits_fall_back_to_defaults():
    p = _one(_pkg(yaml_extra="  time_limit: .inf\n  output: .inf\n", ), default_ms=1500)
    assert p.time_limit_ms == 1500 and p.output_limit_kb is None
    assert any("output limit" in w for w in p.warnings)


def test_an_invalid_yaml_value_refuses_only_that_problem():
    # PyYAML raises ValueError (not YAMLError) for a date like this.
    reason = _refused(_pkg(yaml_extra="released: 2024-13-45\n"))
    assert reason


def test_an_end_record_that_lies_doesnt_get_a_directory_parsed(monkeypatch):
    # zipfile takes a trailing end record at its word without checking its
    # disk fields — so these say "PK\x05\x06", and the counts say 0. Entries
    # are counted by their own signatures instead, before zipfile runs.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for i in range(30):
            zf.writestr(f"x/{i}", b"")
    data = bytearray(buf.getvalue())
    end = data.rfind(b"PK\x05\x06")
    data[end + 4:end + 12] = b"PK\x05\x06" + struct.pack("<HH", 0, 0)
    monkeypatch.setattr(pp, "MAX_MEMBERS", 20)

    def parsed(*args, **kwargs):
        raise AssertionError("the directory was parsed")

    monkeypatch.setattr(zipfile, "ZipFile", parsed)
    with pytest.raises(pp.PackageError, match="too many files"):
        _parse(bytes(data))


def test_a_zip64_directory_cant_hide_behind_a_small_end_record(monkeypatch):
    # zipfile believes the zip64 end record over the classic one, so a zip that
    # states 10 entries classically but 70,000 in zip64 must still be refused —
    # before zipfile parses a single directory entry.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for i in range(70_000):
            zf.writestr(f"x/{i}", b"")
    data = bytearray(buf.getvalue())
    end = data.rfind(b"PK\x05\x06")
    data[end + 8:end + 16] = struct.pack("<HHI", 10, 10, 100)

    def parsed(*args, **kwargs):
        raise AssertionError("the directory was parsed")

    monkeypatch.setattr(zipfile, "ZipFile", parsed)
    with pytest.raises(pp.PackageError, match="too many files"):
        _parse(bytes(data))


def test_nul_characters_never_reach_the_database():
    files = pf.v2025_files()
    files["problem.yaml"] = files["problem.yaml"].replace(f"  en: {pf.SUM_NAME}", '  en: "Sum\\0 of Two"')
    files["statement/problem.en.md"] = "Read two\x00 integers.\n"
    files["submissions/accepted/sol.py"] = "print(1)  # \x00\n"
    p = _one(pf.build_package(files, root=pf.SHORTNAME))
    assert "\x00" not in p.name and "\x00" not in _text(p.statement) and "\x00" not in p.reference_source


# --- refusing what can't be judged faithfully ------------------------------------------


@pytest.mark.parametrize(
    "blob, phrase",
    [
        (pf.custom_validator(), "own output checker"),
        (pf.interactive(), "It's an interactive problem"),
        (pf.interactive(legacy=True), "It's an interactive problem"),
        (pf.scoring(), "scoring"),
        (pf.missing_answer(), "no matching .ans"),
        (pf.escaping_symlink(), "outside the package"),
        (pf.oversized(65), "64 MB"),
        (_pkg(yaml_extra="validation: score\n"), "scoring"),
        (_pkg({"include/python3/helper.py": "x = 1\n"}), "include/"),
        (_pkg(yaml_extra="allow_file_writing: true\n"), "write files"),
        (_pkg({"data/secret/testdata.yaml": "args: [--fast]\n"}), "arguments"),
        # Flags on one secret group only: the other group keeps the default.
        (_pkg(secret=[], extra={
            **{f"data/secret/g1/{k}": v for k, v in {"1.in": "1 1\n", "1.ans": "2\n"}.items()},
            **{f"data/secret/g2/{k}": v for k, v in {"1.in": "2 2\n", "1.ans": "4\n"}.items()},
            "data/secret/g2/testdata.yaml": "output_validator_flags: float_tolerance 1e-3\n",
        }), "checked differently"),
        (_pkg(yaml_extra="validator_flags: float_tolerance 5\n"), "outside what Flagpost supports"),
        (_pkg(yaml_extra="validator_flags: float_tolerance\n"), "no valid value"),
        (_pkg(yaml_extra="validator_flags: space_change_sensitive float_tolerance 1e-6\n"), "spacing exactly"),
        (_pkg({"data/secret/1.files/input.txt": "x\n"}), "files to read"),
        (_pkg({"data/secret/3.in": "1 1\n", "data/secret/3.ans": "2\n", "data/secret/3.interaction": "> 1\n"}),
         "interactive"),
        (_pkg(secret=[]), "no secret tests"),
        (pf.symlink_loop(), "too many links"),
    ],
    ids=[
        "custom", "interactive", "interactive-legacy", "scoring", "missing-ans", "escape", "oversized",
        "legacy-score", "include", "file-writing", "args", "disagreeing-flags", "tolerance-range",
        "tolerance-value", "space-and-float", "files", "interaction", "no-secret", "symlink-loop",
    ],
)
def test_refusals(blob, phrase):
    assert phrase in _refused(blob)


def test_a_zip_bomb_is_contained():
    reason = _refused(pf.zip_bomb())
    assert "larger than" in reason


@pytest.mark.parametrize("method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_a_bzip2_or_lzma_member_is_refused_before_it_inflates(method):
    # zipfile inflates a bzip2/LZMA chunk whole, whatever the read asks for:
    # here 20 MiB — past the 16 MB test-file cap — from a zip of a few KB.
    src = zipfile.ZipFile(io.BytesIO(pf.legacy_passfail()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for info in src.infolist():
            if info.filename.endswith("secret/1.in"):
                zf.writestr(info.filename, b"\0" * (20 << 20), compress_type=method)
            else:
                zf.writestr(info, src.read(info))
    assert len(out.getvalue()) < 64 * 1024
    assert "isn't accepted" in _refused(out.getvalue())


def _damage(blob: bytes, suffix: str, how: str) -> bytes:
    """Corrupt one member's compressed bytes, or mark it encrypted — both only
    surface when the member is read, not when the zip is opened."""
    info = next(i for i in zipfile.ZipFile(io.BytesIO(blob)).infolist() if i.filename.endswith(suffix))
    data = bytearray(blob)
    if how == "corrupt":
        name_len, extra_len = struct.unpack("<HH", data[info.header_offset + 26:info.header_offset + 30])
        start = info.header_offset + 30 + name_len + extra_len
        for k in range(start, start + info.compress_size):
            data[k] ^= 0xA5
    else:  # the "encrypted" flag bit, in the central directory entry
        pos = data.find(b"PK\x01\x02")
        while pos >= 0:
            (name_len,) = struct.unpack("<H", data[pos + 28:pos + 30])
            if bytes(data[pos + 46:pos + 46 + name_len]) == info.filename.encode():
                data[pos + 8] |= 0x01
                break
            pos = data.find(b"PK\x01\x02", pos + 1)
    return bytes(data)


@pytest.mark.parametrize("how", ["corrupt", "encrypted"])
@pytest.mark.parametrize("suffix", [".ans", "problem.yaml"])
def test_a_damaged_member_refuses_its_problem_not_the_request(suffix, how):
    damaged = _damage(pf.legacy_passfail(), suffix, how)
    assert "can't be read" in _refused(damaged)


def test_not_a_package():
    with pytest.raises(pp.PackageError):
        _parse(b"not a zip")
    with pytest.raises(pp.PackageError):
        _parse(pf.build_package({"readme.txt": "hi"}))


# --- the real packages ---------------------------------------------------------------


def test_vendored_hello():
    p = _one(pf.vendored("hello.zip"))
    assert p.name.lower().startswith("hello")
    assert p.testcases and all(not c.sample for c in p.testcases)
    assert p.reference_language in {"python3", "cpp", "c", "kotlin"}


def test_vendored_binary_botch():
    p = _one(pf.vendored("outofsorts.zip"))
    assert sum(c.sample for c in p.testcases) == 2
    assert sum(not c.sample for c in p.testcases) == 12
    assert p.reference_language == "cpp"


# --- the routes ------------------------------------------------------------------------


def _import(client, token, comp, blob, **form):
    return client.post(
        f"/api/competitions/{comp}/judge/packages/import",
        files={"file": ("pkg.zip", blob, "application/zip")},
        data={k: str(v) for k, v in form.items()},
        headers=_auth(token),
    )


async def test_import_makes_a_draft_challenge(client, object_storage):
    admin, comp, _ = await _setup(client)
    resp = await _import(client, admin, comp, pf.legacy_passfail(), default_time_limit_ms=1500)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    [created] = report["created"]
    assert created["name"] == pf.SUM_NAME and created["tests"] == 3 and created["warnings"]
    async with SessionLocal() as db:
        chal = await db.get(Challenge, created["challenge_id"])
        problem = await db.scalar(select(JudgeProblem).where(JudgeProblem.challenge_id == chal.id))
        files = (await db.scalars(select(Attachment).where(Attachment.challenge_id == chal.id))).all()
    assert chal.flag_type == "programming" and chal.state == "draft"
    assert problem.time_limit_ms == 1500 and problem.case_insensitive is True
    assert [c["sample"] for c in problem.testcases] == [True, False, False]
    assert {f.filename for f in files} == {"problem.en.tex"}
    # The tests are stored in Flagpost's own layout.
    cases = td.load(object_storage, problem.object_key, problem.testcases)
    assert cases[0].input == b"3 4\n"
    # The package's solution waits in the reference check.
    ref = (
        await client.get(f"/api/competitions/{comp}/challenges/{chal.id}/judge/reference", headers=_auth(admin))
    ).json()
    assert ref["judging"] is None and ref["language_key"] == "python3" and "print" in ref["source"]


async def test_import_reports_refusals_and_skips(client, object_storage):
    admin, comp, _ = await _setup(client)
    await _import(client, admin, comp, pf.legacy_passfail())
    # A contest zip: the same problem again (skipped) and one with its own
    # checker (refused).
    contest = pf.build_package(
        {**{f"again/{k}": v for k, v in pf.legacy_files().items()},
         **{f"checker/{k.split('/', 1)[1]}": v for k, v in pf.read_members(pf.custom_validator()).items()}},
        root=None,
    )
    report = (await _import(client, admin, comp, contest)).json()
    assert report["created"] == []
    assert [s["name"] for s in report["skipped"]] == [pf.SUM_NAME]
    [refused] = report["refused"]
    assert refused["name"] == "checker" and "checker" in refused["reason"]


async def test_only_authors_with_the_judge_on(client, object_storage):
    from tests.test_judge_problems import _set_module

    admin, comp, _ = await _setup(client)
    player = await _player(client, comp)
    assert (await _import(client, player, comp, pf.legacy_passfail())).status_code == 403
    bad = await _import(client, admin, comp, b"nope")
    assert bad.status_code == 400
    # With the judge module off for the competition, nothing gets in — or out.
    await _set_module(client, admin, comp, False)
    assert (await _import(client, admin, comp, pf.legacy_passfail())).status_code == 404
    export = await client.get(f"/api/competitions/{comp}/judge/packages/export", headers=_auth(admin))
    assert export.status_code == 404


async def test_a_failed_import_leaves_nothing_behind(client, object_storage, monkeypatch):
    admin, comp, _ = await _setup(client)
    calls = {"n": 0}
    real = td.build_zip

    def flaky(cases):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("storage hiccup")
        return real(cases)

    monkeypatch.setattr(td, "build_zip", flaky)
    stored: list[str] = []
    real_put = object_storage.put

    def recording_put(key, data, content_type):
        stored.append(key)
        real_put(key, data, content_type)

    monkeypatch.setattr(object_storage, "put", recording_put)
    before = set(object_storage._objects)
    with pytest.raises(RuntimeError):
        await _import(client, admin, comp, pf.multi_problem())
    async with SessionLocal() as db:
        titles = (await db.scalars(select(Challenge.title).where(Challenge.competition_id == comp))).all()
    assert "Alpha" not in titles and "Beta" not in titles
    # The first problem really was stored before the second failed — and was swept.
    assert calls["n"] == 2 and stored
    assert set(object_storage._objects) == before


# --- export ------------------------------------------------------------------------------


async def _export(client, admin, comp, chal):
    return await client.get(f"/api/competitions/{comp}/challenges/{chal}/judge/package", headers=_auth(admin))


async def _problem_and_cases(chal, object_storage):
    async with SessionLocal() as db:
        problem = await db.scalar(select(JudgeProblem).where(JudgeProblem.challenge_id == chal))
        challenge = await db.get(Challenge, chal)
        files = sorted((await db.scalars(select(Attachment.filename).where(Attachment.challenge_id == chal))).all())
    cases = td.load(object_storage, problem.object_key, problem.testcases)
    return problem, challenge, files, [(c.sample, c.input, c.answer) for c in cases]


async def test_export_round_trips(client, object_storage):
    admin, comp, _ = await _setup(client)
    blob = _pkg({"attachments/tool.py": "print('hi')\n"}, yaml_extra=(
        "  time_limit: 1.5\n  output: 2\nlanguages: [python3]\n"
        "validator_flags: float_tolerance 1e-5\n"
    ))
    created = (await _import(client, admin, comp, blob)).json()["created"]
    chal = created[0]["challenge_id"]
    resp = await _export(client, admin, comp, chal)
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/zip"
    assert 'filename="sumoftwo.zip"' in resp.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
        assert len(names) == len(set(names))
        [root] = {n.split("/")[0] for n in names}
        meta = yaml.safe_load(zf.read(f"{root}/problem.yaml"))
        assert meta["problem_format_version"] == "2025-09"
        assert meta["limits"] == {"time_limit": 1.5, "memory": 512, "output": 2, "time_resolution": 0.001}
        assert meta["languages"] == ["python3"]
        group = yaml.safe_load(zf.read(f"{root}/data/secret/test_group.yaml"))
        assert group["output_validator_args"] == ["float_tolerance", "1e-05"]
        assert "Read two integers" in zf.read(f"{root}/statement/problem.en.md").decode()
        # Named as this site's language saves it (here: solution.py).
        assert zf.read(f"{root}/submissions/accepted/solution.py").decode() == pf.SUM_SOLUTION_PY
        assert zf.read(f"{root}/attachments/tool.py") == b"print('hi')\n"

    # And back in, elsewhere: the same problem, test for test.
    other = await _setup_second_competition(client, admin)
    [made] = (await _import(client, admin, other, resp.content)).json()["created"]
    a, ca, files_a, cases_a = await _problem_and_cases(chal, object_storage)
    b, cb, files_b, cases_b = await _problem_and_cases(made["challenge_id"], object_storage)
    for field in (
        "time_limit_ms", "memory_limit_mb", "output_limit_kb", "compare_mode", "float_tolerance",
        "case_insensitive", "allowed_languages", "reference_language", "reference_source",
    ):
        assert getattr(a, field) == getattr(b, field), field
    assert cases_a == cases_b and len(cases_a) == 3
    assert ca.title == cb.title
    assert _text(ca.description).split("Author:")[0] in _text(cb.description)
    # The attachments come back once each, plus the Markdown statement the
    # import was given (every import keeps its statement's original).
    assert files_b == sorted([*files_a, "problem.en.md"])

    # Export → import → export: still one member per name.
    again = await _export(client, admin, other, made["challenge_id"])
    with zipfile.ZipFile(io.BytesIO(again.content)) as zf:
        assert len(zf.namelist()) == len(set(zf.namelist()))


async def test_export_without_its_stored_test_data_says_which_problem(client, object_storage):
    admin, comp, _ = await _setup(client)
    chal = (await _import(client, admin, comp, pf.legacy_passfail())).json()["created"][0]["challenge_id"]
    async with SessionLocal() as db:
        key = await db.scalar(select(JudgeProblem.object_key).where(JudgeProblem.challenge_id == chal))
    object_storage.delete(key)
    resp = await _export(client, admin, comp, chal)
    assert resp.status_code == 409 and "Sum of Two" in resp.json()["detail"]


async def test_an_export_never_leaves_its_temporary_file_behind(client, object_storage):
    import glob
    import tempfile

    admin, comp, _ = await _setup(client)
    chal = (await _import(client, admin, comp, pf.legacy_passfail())).json()["created"][0]["challenge_id"]
    pattern = f"{tempfile.gettempdir()}/flagpost-export-*.zip"
    before = set(glob.glob(pattern))
    url = f"/api/competitions/{comp}/challenges/{chal}/judge/package"
    # A bad or unsatisfiable Range ends the response early, before any
    # background task — the file must go anyway.
    for headers, code in (({}, 200), ({"Range": "bytes=abc"}, 400), ({"Range": "bytes=999999999-"}, 416)):
        resp = await client.get(url, headers={**_auth(admin), **headers})
        assert resp.status_code == code, (headers, resp.status_code)
    assert set(glob.glob(pattern)) == before


def test_export_numbers_tests_so_name_order_is_judging_order(object_storage):
    # 1001 secret cases: "1000" must not sort before "101" when imported again.
    cases = [td.Testcase(id=f"s{i}", sample=False, input=f"{i}\n".encode(), answer=b"x\n") for i in range(1001)]
    object_storage.put("k", td.build_zip(cases), "application/zip")
    problem = pp.ExportProblem(
        name="Many", uuid="u", statement={"type": "doc", "content": []}, time_limit_ms=1000,
        memory_limit_mb=256, output_limit_kb=1024, compare_mode="token", float_tolerance=None,
        case_insensitive=False, allowed_languages=None, testdata_key="k",
        testcases=td.manifest(cases), files=[("a b.txt", "f1"), ("a_b.txt", "f2")],
    )
    object_storage.put("f1", b"one", "text/plain")
    object_storage.put("f2", b"two", "text/plain")
    out = io.BytesIO()
    pp.build_export([problem], object_storage, out)
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as zf:
        names = zf.namelist()
        assert "many/data/secret/0001.in" in names and "many/data/secret/1001.in" in names
        # Two attachments that sanitise to one name both survive.
        assert {"many/attachments/a_b.txt", "many/attachments/a_b_2.txt"} <= set(names)
        assert len(names) == len(set(names))
    imported = _one(out.getvalue())
    assert [c.input for c in imported.testcases] == [c.input for c in cases]


def test_export_names_test_data_by_position_never_by_the_stored_zip(object_storage):
    # GHSA-wvjv-56qv-9v42: a restored backup decides the stored zip, so its
    # entry names never reach the export — each is made from its case's place.
    cases = [
        td.Testcase(id="a", sample=True, input=b"1\n", answer=b"1\n"),
        td.Testcase(id="b", sample=False, input=b"2\n", answer=b"2\n"),
    ]
    buf = io.BytesIO(td.build_zip(cases))
    with zipfile.ZipFile(buf, "a") as zf:
        zf.writestr("data/../../../evil.in", b"x")
        zf.writestr("data/..\\..\\evil.ans", b"x")
    object_storage.put("k", buf.getvalue(), "application/zip")
    problem = pp.ExportProblem(
        name="P", uuid="u", statement={"type": "doc", "content": []}, time_limit_ms=1000,
        memory_limit_mb=256, output_limit_kb=1024, compare_mode="token", float_tolerance=None,
        case_insensitive=False, allowed_languages=None, testdata_key="k",
        testcases=td.manifest(cases),
    )
    out = io.BytesIO()
    pp.build_export([problem], object_storage, out)
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as zf:
        names = zf.namelist()
    assert sorted(n for n in names if n.startswith("p/data/") and not n.endswith(".yaml")) == [
        "p/data/sample/001.ans", "p/data/sample/001.in", "p/data/secret/001.ans", "p/data/secret/001.in",
    ]
    assert all(".." not in n.split("/") and "\\" not in n for n in names)


async def _setup_second_competition(client, admin) -> str:
    comp = (
        await client.post(
            "/api/competitions", json={"name": "Second", "participation_mode": "individual"},
            headers=_auth(admin),
        )
    ).json()["id"]
    return comp


async def test_bulk_export_and_ctfcli_skips_programming(client, object_storage):
    admin, comp, chal = await _setup(client)
    resp = await client.get(f"/api/competitions/{comp}/judge/packages/export", headers=_auth(admin))
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert any(n.endswith("/problem.yaml") for n in zf.namelist())
    ctf = await client.get(f"/api/competitions/{comp}/challenges/export", headers=_auth(admin))
    with zipfile.ZipFile(io.BytesIO(ctf.content)) as zf:
        assert not any(n.endswith("challenge.yml") for n in zf.namelist())
