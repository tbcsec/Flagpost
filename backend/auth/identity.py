"""Identity lookups: the display name is the primary login identifier (§7.7).

The display name is a **case-insensitive unique username**; email is an optional
secondary handle (unique when present). These helpers centralise the
case-insensitive matching so registration, admin user-management, and login all
agree on what "already taken" and "who is this" mean.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User


async def find_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    """Resolve a login identifier to a user: try email first, then display name,
    both case-insensitively. Two queries (not an OR) so the match is deterministic
    even in the unlikely case one user's email equals another's display name."""
    ident = identifier.strip().lower()
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
