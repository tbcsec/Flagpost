"""Sanity checks for the problem-package fixtures (#451).

The importer's tests trust these builders to produce what their docstrings
promise; a fixture that silently stopped carrying its quirk (a symlink stored
as a plain file, a bomb that no longer exceeds the caps) would turn a security
test into a pass that proves nothing. These pin the shape, not the importer.
"""

from __future__ import annotations

import io
import zipfile

import pytest
import yaml

from tests import package_fixtures as pf

# Every cheap builder, with the problem roots it should produce.
CHEAP_BUILDERS = [
    (pf.legacy_passfail, [pf.SHORTNAME]),
    (pf.v2025_passfail, [pf.SHORTNAME]),
    (pf.with_timelimit_file, [pf.SHORTNAME]),
    (pf.with_ini_timelimit, [pf.SHORTNAME]),
    (pf.float_tolerance, [pf.SHORTNAME]),
    (pf.abs_only_tolerance, [pf.SHORTNAME]),
    (pf.case_sensitive_flag, [pf.SHORTNAME]),
    (pf.custom_validator, [pf.SHORTNAME]),
    (pf.bundled_default_validator, [pf.SHORTNAME]),
    (pf.interactive, ["guess"]),
    (pf.scoring, [pf.SHORTNAME]),
    (pf.test_groups, [pf.SHORTNAME]),
    (pf.symlinked_case, [pf.SHORTNAME]),
    (pf.escaping_symlink, [pf.SHORTNAME]),
    (pf.missing_answer, [pf.SHORTNAME]),
    (pf.multi_problem, ["alpha", "beta"]),
    (pf.pdf_statement, [pf.SHORTNAME]),
    (pf.no_name, [pf.SHORTNAME]),
    (pf.unknown_key, [pf.SHORTNAME]),
    (pf.license_unknown, [pf.SHORTNAME]),
    (pf.cc_by, [pf.SHORTNAME]),
    (pf.attachments, [pf.SHORTNAME]),
    (pf.kotlin_and_python_accepted, [pf.SHORTNAME]),
]


def _zip(blob: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(blob))


def _yaml(blob: bytes, root: str = pf.SHORTNAME) -> dict:
    return yaml.safe_load(pf.read_members(blob)[f"{root}/problem.yaml"])


def test_every_builder_makes_a_valid_package():
    # One test, not a parametrized one: each case would pay the suite's
    # per-test database setup for a few milliseconds of zip work.
    for builder, roots in CHEAP_BUILDERS:
        label = builder.__name__
        blob = builder()
        with _zip(blob) as zf:
            assert zf.testzip() is None, label
            names = zf.namelist()
        assert {n.split("/", 1)[0] for n in names} == set(roots), label
        for root in roots:
            assert isinstance(_yaml(blob, root), dict), label
        # Reproducible: the same builder yields the same bytes.
        assert builder() == blob, label


def test_build_package_root_and_encoding():
    wrapped = pf.build_package({"a.txt": "é", "b.bin": b"\x00"})
    assert pf.read_members(wrapped) == {"pkg/a.txt": "é".encode(), "pkg/b.bin": b"\x00"}
    bare = pf.build_package({"a.txt": "x"}, root=None)
    assert pf.read_members(bare) == {"a.txt": b"x"}


def test_symlink_entries_are_unix_symlinks():
    blob = pf.symlinked_case()
    with _zip(blob) as zf:
        link = zf.getinfo(f"{pf.SHORTNAME}/data/secret/3.in")
        regular = zf.getinfo(f"{pf.SHORTNAME}/data/secret/3.ans")
    assert link.external_attr >> 16 == 0o120777
    assert pf.is_symlink(link) and not pf.is_symlink(regular)
    assert pf.symlink_targets(blob) == {f"{pf.SHORTNAME}/data/secret/3.in": "../sample/1.in"}
    assert pf.symlink_targets(pf.escaping_symlink()) == {
        f"{pf.SHORTNAME}/data/secret/3.in": "../../../../etc/passwd"
    }
    assert pf.symlink_targets(pf.legacy_passfail()) == {}


def test_variants_carry_their_difference():
    assert _yaml(pf.float_tolerance())["validator_flags"] == "float_tolerance 1e-6"
    assert _yaml(pf.abs_only_tolerance())["validator_flags"] == "float_absolute_tolerance 1e-3"
    assert _yaml(pf.case_sensitive_flag())["validator_flags"] == "case_sensitive"
    assert "validator_flags" not in _yaml(pf.legacy_passfail())
    assert "name" not in _yaml(pf.no_name())
    assert _yaml(pf.unknown_key())["sandbox-type"] == "X"
    assert _yaml(pf.license_unknown())["license"] == "unknown"
    assert _yaml(pf.cc_by())["author"] == pf.CC_BY_AUTHOR
    assert _yaml(pf.interactive(legacy=True), "guess")["validation"] == "custom interactive"

    v2025 = pf.read_members(pf.v2025_passfail())
    meta = yaml.safe_load(v2025[f"{pf.SHORTNAME}/problem.yaml"])
    assert meta["problem_format_version"] == "2025-09"
    assert meta["name"] == {"en": pf.SUM_NAME}
    assert meta["limits"]["time_limit"] == 2.5
    group = yaml.safe_load(v2025[f"{pf.SHORTNAME}/data/secret/test_group.yaml"])
    assert group["output_validator_args"] == ["case_sensitive"]

    assert pf.read_members(pf.with_timelimit_file())[f"{pf.SHORTNAME}/.timelimit"] == b"3\n"
    ini = pf.read_members(pf.with_ini_timelimit())[f"{pf.SHORTNAME}/judge-problem.ini"]
    assert ini == b"timelimit = 4\n"

    pdf = pf.read_members(pf.pdf_statement())
    assert pdf[f"{pf.SHORTNAME}/problem_statement/problem.pdf"].startswith(b"%PDF-")
    assert not any(n.endswith(".tex") for n in pdf)

    bundled = pf.read_members(pf.bundled_default_validator())
    source = bundled[
        f"{pf.SHORTNAME}/output_validators/default_validator/default_validator.cc"
    ].decode()
    for flag in (
        "case_sensitive",
        "space_change_sensitive",
        "float_absolute_tolerance",
        "float_relative_tolerance",
    ):
        assert flag in source

    interactive = pf.read_members(pf.interactive())
    transcript = interactive["guess/data/sample/1.interaction"].decode().splitlines()
    assert all(line[:2] in ("< ", "> ") for line in transcript)

    sols = pf.read_members(pf.kotlin_and_python_accepted())
    accepted = f"{pf.SHORTNAME}/submissions/accepted"
    assert {f"{accepted}/sol.kt", f"{accepted}/sol.py", f"{accepted}/sol2.py"} <= set(sols)
    assert sols[f"{accepted}/sol2.py"].startswith(b"#!/usr/bin/python2\n")

    assert f"{pf.SHORTNAME}/attachments/testing_tool.py" in pf.read_members(pf.attachments())
    missing = pf.read_members(pf.missing_answer())
    assert f"{pf.SHORTNAME}/data/secret/3.in" in missing
    assert f"{pf.SHORTNAME}/data/secret/3.ans" not in missing


def test_test_groups_are_written_out_of_order():
    with _zip(pf.test_groups()) as zf:
        secret = [n for n in zf.namelist() if "/data/secret/" in n and n.endswith(".ans")]
        answers = [zf.read(n).decode() for n in sorted(secret)]
    assert secret != sorted(secret)  # the zip order is deliberately not judging order
    sample = pf.read_members(pf.test_groups())[f"{pf.SHORTNAME}/data/sample/1.ans"].decode()
    assert [sample, *answers] == pf.TEST_GROUPS_ANSWER_ORDER


def test_oversized_exceeds_the_total_cap_only_by_default():
    with _zip(pf.oversized()) as zf:
        sizes = [i.file_size for i in zf.infolist()]
    assert sum(sizes) > 64 * pf.MB
    assert max(sizes) <= 16 * pf.MB

    blob = pf.oversized(17, file_mb=17)
    with _zip(blob) as zf:
        assert max(i.file_size for i in zf.infolist()) > 16 * pf.MB
    assert len(blob) < pf.MB  # repetitive bytes: the zip itself stays tiny


def test_zip_bomb_is_compact_and_can_lie_about_its_size():
    name = f"{pf.SHORTNAME}/data/secret/3.in"
    blob = pf.zip_bomb(64)
    with _zip(blob) as zf:
        info = zf.getinfo(name)
    assert info.file_size == 64 * pf.MB
    assert info.compress_size * 500 < info.file_size

    liar = pf.zip_bomb(64, declared_size=100)
    with _zip(liar) as zf:
        assert zf.getinfo(name).file_size == 100
        with pytest.raises(zipfile.BadZipFile):
            zf.read(name)


def test_vendored_packages_are_present_and_licensed():
    readme = (pf.FIXTURES_DIR / "README.md").read_text()
    for name in pf.VENDORED:
        assert f"`{name}`" in readme

    hello = pf.vendored("hello.zip")
    with _zip(hello) as zf:
        assert zf.testzip() is None
        names = set(zf.namelist())
    assert {
        "hello/problem.yaml",
        "hello/problem_statement/problem.en.tex",
        "hello/data/secret/hello.in",
        "hello/data/secret/hello.ans",
        "hello/submissions/accepted/hello.py",
    } <= names
    assert _yaml(hello, "hello")["license"] == "public domain"

    ecna = pf.vendored("outofsorts.zip")
    with _zip(ecna) as zf:
        assert zf.testzip() is None
        assert not any(pf.is_symlink(i) for i in zf.infolist())
    meta = _yaml(ecna, "outofsorts")
    assert meta["license"] == "cc0"
    assert meta["name"] == "Binary Botch"
