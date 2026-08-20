"""Schemas for custom pages (#198, ADR-0034).

Three output shapes, because a page is read by three different audiences and
each should see the least that serves it:

- :class:`PageNavOut` — the sidebar/nav entry. No body, so building the nav
  doesn't ship every page's full document to every client on every load.
- :class:`PageOut` — one page's content, for rendering ``/p/{slug}``.
- :class:`PageAdminOut` — adds the authoring state (``draft``, timestamps) that
  only a ``manage_pages`` holder has any use for.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.page import DEFAULT_ICON, ICON_NAMES, MAX_TITLE_LENGTH
from utils.rich_text import validate_rich_text_doc

# Serialized-size cap for a page document. Larger than the sign-in notice (20 KB)
# because a page is a destination someone chose to open rather than something
# every login pays for, but still bounded: the body is served as JSON and
# rendered client-side, so an unbounded document is a slow page for the reader
# and a large row for every backup.
MAX_PAGE_CONTENT_BYTES = 200_000

# Same shape as the identity-provider slug (routers/auth_providers_admin.py):
# lowercase, digits and inner hyphens, 2-60 chars. It *is* the URL, so keeping
# one pattern across the codebase means one thing to reason about.
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,58}[a-z0-9]$"
_SLUG_RE = re.compile(SLUG_PATTERN)

# Slugs a page may not take. Pages live under `/p/{slug}`, so none of these
# actually collide today — `/p/login` is not `/login`. They're reserved anyway,
# cheaply, so that moving pages to top-level paths later doesn't require a data
# migration to dig out rows that have since become ambiguous. `api`, `p` and
# `_next` are included for the same reason.
RESERVED_SLUGS: frozenset[str] = frozenset(
    {
        "admin", "ai-transcripts", "analytics", "api", "auth", "automations",
        "challenges", "feedback", "forgot-password", "lobby", "login", "new",
        "_next", "p", "participants", "profile", "public", "register",
        "reset-password", "scoreboard", "settings", "setup", "support",
        "verify-email",
    }
)


def validate_icon(raw: str) -> str:
    """Only a name from the curated catalog (models.page.ICON_NAMES).

    An allowlist rather than a pattern: names like ``constructor`` and
    ``toString`` are perfectly ordinary-looking strings but are inherited
    ``Object.prototype`` keys in the browser, so a lookup on them returns
    something non-nullish and the renderer's fallback never fires. A regex
    permissive enough to accept real names cannot exclude those.
    """
    icon = raw.strip().lower()
    if icon not in ICON_NAMES:
        raise ValueError(f"{raw!r} is not a known page icon")
    return icon


def validate_slug(raw: str) -> str:
    """Normalize and check a page slug, or raise ``ValueError``."""
    slug = raw.strip().lower()
    if not _SLUG_RE.match(slug):
        raise ValueError(
            "slug must be 2-60 characters of lowercase letters, numbers and "
            "hyphens, and may not start or end with a hyphen"
        )
    if slug in RESERVED_SLUGS:
        raise ValueError(f"{slug!r} is a reserved slug")
    return slug


class PageNavOut(BaseModel):
    """A sidebar entry. Deliberately body-less — see the module docstring."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    title: str
    icon: str
    nav_order: int


class PageOut(PageNavOut):
    """One page's renderable content."""

    content: dict | None = None


class PageAdminOut(PageOut):
    """Authoring view — adds the state only an author needs."""

    id: str
    visibility: str
    draft: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=2, max_length=60)
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    content: dict | None = None
    icon: str = Field(default=DEFAULT_ICON, max_length=40)
    nav_order: int = Field(default=0, ge=0, le=9999)
    visibility: Literal["public", "authenticated"] = "authenticated"
    # Created unpublished unless the author says otherwise, so a page is never
    # live before it has been looked at.
    draft: bool = True

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return validate_slug(v)

    @field_validator("icon")
    @classmethod
    def _icon(cls, v: str) -> str:
        return validate_icon(v)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        title = v.strip()
        if not title:
            raise ValueError("title must not be blank")
        return title

    @field_validator("content")
    @classmethod
    def _content(cls, v: dict | None) -> dict | None:
        return validate_rich_text_doc(
            v,
            max_bytes=MAX_PAGE_CONTENT_BYTES,
            field_label="page content",
            too_large_hint=" — split a very long page into several",
        )


class PageUpdate(BaseModel):
    """Partial update. Every field optional; omitted means "leave unchanged",
    which is why the router consults ``model_fields_set`` rather than treating
    ``None`` as "clear" for fields where null is also a real value."""

    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(default=None, min_length=2, max_length=60)
    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LENGTH)
    content: dict | None = None
    icon: str | None = Field(default=None, max_length=40)
    nav_order: int | None = Field(default=None, ge=0, le=9999)
    visibility: Literal["public", "authenticated"] | None = None
    draft: bool | None = None

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str | None) -> str | None:
        return validate_slug(v) if v is not None else None

    @field_validator("content")
    @classmethod
    def _content(cls, v: dict | None) -> dict | None:
        return validate_rich_text_doc(
            v,
            max_bytes=MAX_PAGE_CONTENT_BYTES,
            field_label="page content",
            too_large_hint=" — split a very long page into several",
        )

    @field_validator("icon")
    @classmethod
    def _icon(cls, v: str | None) -> str | None:
        return validate_icon(v) if v is not None else None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        title = v.strip()
        if not title:
            raise ValueError("title must not be blank")
        return title


class PageReorder(BaseModel):
    """Bulk reorder: the full list of page ids in their new order.

    A whole-list replace rather than per-row nudges, so a drag that moves one
    page can't leave the rest inconsistent if a request is lost partway.
    """

    model_config = ConfigDict(extra="forbid")

    page_ids: list[str] = Field(min_length=0, max_length=500)
