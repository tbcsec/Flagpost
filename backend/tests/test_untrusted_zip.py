"""Bounded reading of untrusted zips (GHSA-wvjv-56qv-9v42): the shared helper
every importer reads through. Its callers' own tests cover each path end to
end; these pin the helper's contract."""

import io
import tracemalloc
import zipfile

import pytest
import yaml

from utils.untrusted_zip import (
    ArchiveRefused,
    check_member_count,
    load_yaml,
    read_bounded,
    unique_name,
    yaml_too_large,
)


def _zip(members: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return zipfile.ZipFile(io.BytesIO(buf.getvalue()))


@pytest.mark.parametrize("compression", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_bzip2_and_lzma_members_are_refused_before_they_inflate(compression):
    # zipfile hands a bzip2/LZMA chunk to its decompressor with no output
    # limit, so even read(1) would inflate this whole 8 MiB member — from a
    # zip of a few hundred bytes. It's refused before it's opened.
    zf = _zip({"bomb.bin": b"\0" * (8 << 20)}, compression)
    with pytest.raises(ArchiveRefused, match="isn't accepted"):
        read_bounded(zf, "bomb.bin", 1024)
    with pytest.raises(ArchiveRefused):
        read_bounded(zf, zf.getinfo("bomb.bin"), 1024)


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_stored_and_deflate_members_are_read_up_to_the_limit(compression):
    zf = _zip({"a.bin": b"x" * 5000}, compression)
    assert read_bounded(zf, "a.bin", 1001) == b"x" * 1001
    assert read_bounded(zf, "a.bin", 10_000) == b"x" * 5000
    with pytest.raises(KeyError):
        read_bounded(zf, "missing", 10)


def test_the_member_count_is_checked_on_the_raw_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(6):
            zf.writestr(f"f{i}", b"")
    check_member_count(buf.getvalue(), 6)
    with pytest.raises(ArchiveRefused, match="too many files"):
        check_member_count(buf.getvalue(), 5)


def test_unique_name_numbers_a_repeat():
    used = {"challenge.yml"}
    assert [unique_name(n, used) for n in ("a.txt", "a.txt", "a.txt", "challenge.yml")] == [
        "a.txt", "a_2.txt", "a_3.txt", "challenge_2.yml",
    ]


# --- YAML expansion --------------------------------------------------------------

NODES, CHARS = 10_000, 4 * 1024 * 1024


def test_one_long_string_named_many_times_is_too_large():
    # Under the node budget by far, but str() of it is 40 MB of text — from a
    # document of a few KB. Keys count as well as values.
    doc = load_yaml("s: &s " + "a" * 100_000 + "\nl: [" + ", ".join(["*s"] * 400) + "]\n")
    assert yaml_too_large(doc, NODES, CHARS)
    assert yaml_too_large(load_yaml("? &k " + "k" * 100_000 + "\n: 1\nl: [" + ", ".join(["*k"] * 400) + "]\n"),
                          NODES, CHARS)
    # A document's own scalars, however long, are never too many characters.
    assert not yaml_too_large(load_yaml("s: " + "a" * 1_000_000 + "\n"), NODES, CHARS)


@pytest.mark.parametrize("container", ["!!set {? *s}", "!!omap [k: *s]", "!!pairs [k: *s]"])
def test_sets_and_pairs_are_counted_too(container):
    doc = load_yaml(f"s: &s {'a' * 100_000}\nt: &t {container}\nl: [" + ", ".join(["*t"] * 400) + "]\n")
    assert yaml_too_large(doc, NODES, CHARS)


def test_a_long_list_that_holds_itself_is_checked_in_bounded_memory():
    # Each visit to the list would stack all of it again: 10,000 visits of
    # 2,000 entries is 20 million references if the stack isn't bounded.
    doc = load_yaml("a: &a [" + ", ".join(["x"] * 2000) + ", *a]\n")
    tracemalloc.start()
    try:
        assert yaml_too_large(doc, NODES, CHARS)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024


def test_nesting_too_deep_to_parse_is_a_yaml_error():
    with pytest.raises(yaml.YAMLError, match="nested too deeply"):
        load_yaml("[" * 2000 + "]" * 2000)
