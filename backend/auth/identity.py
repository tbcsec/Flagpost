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


# Code points a directory's matching rules map to nothing (RFC 3454 table B.1
# and RFC 4518 §2.2) beyond the Cc/Cf categories: the combining grapheme joiner,
# the Mongolian soft hyphen and free variation selectors, the variation
# selectors, and the object replacement character.
_MAPPED_TO_NOTHING = frozenset(
    [0x034F, 0x1806, 0x180B, 0x180C, 0x180D, 0xFFFC]
    + list(range(0xFE00, 0xFE10))
    + list(range(0xE0100, 0xE01F0))
)


def directory_match_key(identifier: str) -> str:
    """The identifier folded at least as far as a directory folds it when
    matching (LDAP, ADR-0022): RFC 4518 compatibility-normalises, case-folds and
    drops formatting characters, and Active Directory ignores character width.
    Whitespace is dropped outright — coarser than RFC 4518's insignificant-space
    handling, which only merges more spellings. Keys the directory leg's login
    throttle, so no spelling the directory resolves to one entry gets its own
    budget (GHSA-vv68-w7qp-6cpf). Not for the local lookup: locally these are
    distinct accounts."""
    folded = unicodedata.normalize(
        "NFKC", unicodedata.normalize("NFKC", identifier).casefold()
    )
    return "".join(
        ch
        for ch in folded
        if not ch.isspace()
        and ord(ch) not in _MAPPED_TO_NOTHING
        and unicodedata.category(ch) not in ("Cc", "Cf")
    ).lower()


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
