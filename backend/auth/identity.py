"""Identity lookups: the display name is the primary login identifier (§7.7).

The display name is a **case-insensitive unique username**; email is an optional
secondary handle (unique when present). These helpers centralise the
case-insensitive matching so registration, admin user-management, and login all
agree on what "already taken" and "who is this" mean.
"""

from __future__ import annotations

import unicodedata

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User


def normalize_identifier(identifier: str) -> str:
    """A login identifier as the lookup matches it: surrounding whitespace
    stripped, case folded. Anything keyed on an identifier — the login throttle
    above all — uses this too, so every spelling the lookup treats as one
    account shares one budget (GHSA-vv68-w7qp-6cpf)."""
    return identifier.strip().lower()


# Code points a directory's matching rules map to nothing (RFC 3454 table B.1,
# which RFC 4518 applies) beyond the Cc/Cf categories: the combining grapheme
# joiner, the Mongolian soft hyphen and free variation selectors, and the
# variation selectors.
_MAPPED_TO_NOTHING = frozenset(
    [0x034F, 0x1806, 0x180B, 0x180C, 0x180D]
    + list(range(0xFE00, 0xFE10))
    + list(range(0xE0100, 0xE01F0))
)


def login_throttle_key(identifier: str) -> str:
    """The identifier as the login throttle buckets it — coarser than
    :func:`normalize_identifier`, on purpose. The local lookup only strips and
    case-folds, but a directory (LDAP, ADR-0022) resolves the identifier under
    its own matching rules: RFC 4518 compatibility-normalises, case-folds, drops
    formatting characters and collapses inner spaces, and Active Directory
    ignores character width. A key as narrow as the lookup's would give each
    fullwidth letter or zero-width space a fresh budget against a directory
    account. Merging look-alike spellings only makes them share a budget; it
    never resolves anyone to a different account (GHSA-vv68-w7qp-6cpf)."""
    folded = unicodedata.normalize(
        "NFKC", unicodedata.normalize("NFKC", identifier).casefold()
    )
    # Drop what maps to nothing, keeping whitespace (tabs and newlines are Cc
    # too, but count as a space), then collapse every run of it. Lowercased
    # last: the throttle lowercases every key it records, and case folding
    # isn't always lowercase (Cherokee folds to upper), so the reset after a
    # successful login must clear exactly what was recorded.
    kept = "".join(
        ch
        for ch in folded
        if ch.isspace()
        or (
            ord(ch) not in _MAPPED_TO_NOTHING
            and unicodedata.category(ch) not in ("Cc", "Cf")
        )
    )
    return " ".join(kept.split()).lower()


async def find_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    """Resolve a login identifier to a user: try email first, then display name,
    both case-insensitively. Two queries (not an OR) so the match is deterministic
    even in the unlikely case one user's email equals another's display name."""
    ident = normalize_identifier(identifier)
    user = await db.scalar(select(User).where(func.lower(User.email) == ident))
    if user is None:
        user = await db.scalar(
            select(User).where(func.lower(User.display_name) == ident)
        )
    return user


async def display_name_taken(
    db: AsyncSession, display_name: str, *, exclude_id: str | None = None
) -> bool:
    stmt = select(User.id).where(
        func.lower(User.display_name) == display_name.strip().lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return await db.scalar(stmt) is not None


async def email_taken(
    db: AsyncSession, email: str, *, exclude_id: str | None = None
) -> bool:
    stmt = select(User.id).where(func.lower(User.email) == email.strip().lower())
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return await db.scalar(stmt) is not None
