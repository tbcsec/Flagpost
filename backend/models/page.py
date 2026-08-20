"""Custom page model (#198, ADR-0034).

An administrator-authored, **site-level** content page — About, Sponsors,
Contact — that appears in the sidebar and renders at ``/p/{slug}``. Site-level
rather than competition-scoped (ADR-0034): pages describe the *install*, so they
deliberately carry no ``competition_id`` and are **not** subject to the §6.2
tenancy filter. Adding a nullable one "for later" would imply a tenancy story
that isn't implemented.

``content`` is **ProseMirror JSON**, the same shape the sign-in notice uses, and
is only ever rendered through the read-only TipTap view — never as an HTML
string (ADR-0034). The server validates its *shape* on write and otherwise never
interprets it.

Two independent controls decide who sees a page, and both fail closed to a 404
rather than a 403, so a page's existence doesn't leak to someone who may not
read it:

- ``draft`` — hidden from everyone except a holder of ``manage_pages``;
- ``visibility`` — ``public`` (reachable logged-out) or ``authenticated``.
"""

from uuid import uuid4

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from db import Base, TimestampMixin

# Who may read a published page. Deliberately two values, not a role list: page
# access is a publishing decision, not an RBAC one — anything finer belongs in
# the permission catalog rather than in content settings.
VISIBILITIES: tuple[str, ...] = ("public", "authenticated")
DEFAULT_VISIBILITY = "authenticated"

# Sidebar glyph, stored as a name from a curated set drawn in the frontend's
# inline-SVG style. A *name*, never markup: an SVG upload surface would be the
# same stored-XSS hazard ADR-0034 exists to avoid.
#
# The names are mirrored from ``components/app/page-icons.tsx``, which owns the
# actual geometry. Validating against this list at write time is what stops an
# author storing an arbitrary string: a name like ``__proto__`` or
# ``constructor`` is inherited from ``Object.prototype`` in JS, so a naive
# client-side lookup returns a non-element and crashes the sidebar on *every*
# authenticated page. The renderer defends itself with an own-property check
# too (belt and braces — backup import writes rows without passing through
# these schemas), so drift between the two lists costs a default glyph rather
# than an error.
DEFAULT_ICON = "document"
ICON_NAMES: frozenset[str] = frozenset(
    {
        "document", "info", "book", "star", "heart", "trophy", "users", "mail",
        "chat", "link", "calendar", "clock", "shield", "lock", "flag", "gift",
        "megaphone", "help", "map", "code",
    }
)

# Belt-and-braces cap alongside the schema's own validation, so a hand-written
# row can't hold an unbounded document.
MAX_TITLE_LENGTH = 120


class Page(Base, TimestampMixin):
    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # URL-safe and unique — it *is* the address (``/p/{slug}``). Indexed because
    # the by-slug read is the hot path for every page view.
    slug: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    # ProseMirror document. Generic JSON for SQLite/Postgres portability
    # (ADR-0006), like every other JSON column here.
    content: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    icon: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ICON, server_default=DEFAULT_ICON
    )
    # Sidebar position. Not unique: ties are broken by title so a duplicated
    # order from an import still renders deterministically.
    nav_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    visibility: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_VISIBILITY,
        server_default=DEFAULT_VISIBILITY,
    )
    # Authored but not published. Defaults **true** so a half-written page can
    # never appear the instant it's created — publishing is an explicit act.
    draft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
