"""Bounded reading of untrusted zip archives (GHSA-wvjv-56qv-9v42).

Every importer that unpacks an uploaded or stored zip — ctfcli challenge
bundles, problem packages, content packs, a programming problem's test data —
reads through these helpers, so the containment is the same everywhere:

- **Member count**, checked on the raw bytes before ``zipfile`` parses them:
  it builds an object per central-directory entry up front, so a cheap upload
  of a million empty entries costs far more memory than any member cap allows.
- **Compression**, stored or deflate only. ``read(n)`` bounds what a deflate
  member inflates per call, but CPython hands a bzip2 or LZMA chunk to the
  decompressor with no output limit, so one tiny member inflates in full
  before any cap is checked.
- **Size**, never trusted from the header: a member is read up to a limit, and
  whatever was inflated to find out it's too big is the caller's to count.
"""

from __future__ import annotations

import lzma
import posixpath
import zipfile
import zlib

# Members in one zip — generous for a contest's worth of problems or a ctfcli
# bundle, and about 11 MB of directory objects at most.
MAX_MEMBERS = 20_000

ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})

# What a corrupt, truncated or encrypted member raises from zipfile — a lying
# header surfaces only once it's read. (``ArchiveRefused`` is a ValueError too:
# catch it first.)
READ_ERRORS = (
    zipfile.BadZipFile, zlib.error, lzma.LZMAError, EOFError, NotImplementedError,
    RuntimeError, OSError, ValueError,
)


class ArchiveRefused(ValueError):
    """An archive, or one member of it, that won't be unpacked — the message
    is fit to show whoever uploaded it."""


def check_member_count(data: bytes, limit: int = MAX_MEMBERS) -> None:
    """Refuse a zip with more than ``limit`` entries before ``zipfile`` parses
    it. Every entry it can build starts with this signature, so counting them
    bounds it however the directory is located — the end records can lie."""
    if data.count(b"PK\x01\x02") > limit:
        raise ArchiveRefused(f"The zip has too many files (more than {limit:,})")


def check_compression(info: zipfile.ZipInfo) -> None:
    if info.compress_type not in ALLOWED_COMPRESSION:
        method = zipfile.compressor_names.get(info.compress_type, f"method {info.compress_type}")
        raise ArchiveRefused(
            f"{info.filename} is compressed with {method}, which isn't accepted — "
            "zip it again with standard (deflate) compression"
        )


def read_bounded(zf: zipfile.ZipFile, member: str | zipfile.ZipInfo, limit: int) -> bytes:
    """At most ``limit`` bytes of ``member``, its compression checked before
    it's opened. ``KeyError`` (no such member) and ``zipfile``'s own errors for
    a damaged one propagate. Pass ``cap + 1`` to tell "exactly the cap" from
    "over it"."""
    # Resolve to one ZipInfo, so the entry checked is the entry opened even when
    # a name appears twice in the directory.
    info = member if isinstance(member, zipfile.ZipInfo) else zf.getinfo(member)
    check_compression(info)
    with zf.open(info) as handle:
        return handle.read(limit)


def unique_name(name: str, used: set[str]) -> str:
    """``name``, or ``name_2``/``name_3``… if one before it took it."""
    stem, ext = posixpath.splitext(name)
    candidate, n = name, 2
    while candidate in used:
        candidate, n = f"{stem}_{n}{ext}", n + 1
    used.add(candidate)
    return candidate


def yaml_too_large(tree: object, limit: int) -> bool:
    """Whether a parsed YAML document has more than ``limit`` nodes once its
    aliases are expanded. Aliases share nodes, so a few hundred bytes can
    become gigabytes the moment anything ``str()``s a value."""
    stack: list = [tree]
    seen = 0
    while stack:
        node = stack.pop()
        seen += 1
        if seen > limit:
            return True
        if isinstance(node, dict):
            stack.extend(node.keys())
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False
