"""Bounded reading of untrusted zips (GHSA-wvjv-56qv-9v42): the shared helper
every importer reads through. Its callers' own tests cover each path end to
end; these pin the helper's contract."""

import io
import zipfile

import pytest

from utils.untrusted_zip import (
    ArchiveRefused,
    check_member_count,
    read_bounded,
    unique_name,
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
