"""Custom page routes (#198, ADR-0034).

Two surfaces:

- **Public reads** (``/api/pages``) — the sidebar list and one page's content.
  Unauthenticated-reachable, because a page may be published ``public``. What a
  caller sees depends on who they are, and the filtering happens **in the query**
  rather than after it, so an invisible page is never loaded and then discarded.
- **Admin CRUD** (``/api/admin/pages``) — behind ``manage_pages``.

The visibility rules (ADR-0034) fail closed to **404, never 403**: a page that a
caller may not read must be indistinguishable from one that doesn't exist, or
the error code itself confirms that a draft named ``/p/acquisition-faq`` is
being written.

|              | anonymous | authenticated | ``manage_pages`` |
|--------------|-----------|---------------|------------------|
| draft        | 404       | 404           | visible          |
| public       | visible   | visible       | visible          |
| authenticated| 404       | visible       | visible          |
"""

from __future__ import annotations

import logging

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission, user_has_permission
from auth.security import decode_access_token
from db import get_db
from models.page import Page
from models.user import User
from schemas.page import (
    PageAdminOut,
    PageCreate,
    PageNavOut,
    PageOut,
    PageReorder,
    PageUpdate,
)
from utils.event_bus import event_bus

logger = logging.getLogger("pages")

router = APIRouter(prefix="/api/pages", tags=["pages"])
admin_router = APIRouter(prefix="/api/admin/pages", tags=["pages-admin"])

_optional_bearer = HTTPBearer(auto_error=False)


async def _viewer(
    creds: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """The current user, or ``None`` — never a 401.

    Deliberately not ``get_current_user``: these routes serve logged-out
    visitors, so a missing or stale token means "anonymous", not an error. A
    *malformed* token is likewise treated as anonymous rather than surfaced,
    because the caller's alternative — being told their token is bad while
    fetching a public page — is noise they can't act on.

    Note this is the one place a banned user is treated as merely anonymous
    instead of rejected; that's correct here, since the content they'd see is
    exactly what a logged-out visitor sees anyway.
    """
    if creds is None:
        return None
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        return None
    user = await db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        return None
    return user


async def _can_author(db: AsyncSession, user: User | None) -> bool:
    """Does this user hold ``manage_pages``?

    ``competition_id=None`` because pages are site-level (ADR-0034): the grant
    is global-scoped, so only a site-wide role assignment satisfies it — a Judge
    on one competition doesn't inherit authoring rights over install-wide
    content.
    """
    if user is None:
        return False
    return await user_has_permission(db, user.id, "manage_pages", None)


def _readable_filter(*, authenticated: bool):
    """SQL conditions restricting a query to pages this caller may read.

    Applied to the query rather than to its results: a draft or
    members-only page should never be fetched at all on a public path.
    """
    conditions = [Page.draft.is_(False)]
    if not authenticated:
        conditions.append(Page.visibility == "public")
    return conditions


@router.get("", response_model=list[PageNavOut])
async def list_pages(
    viewer: User | None = Depends(_viewer),
    db: AsyncSession = Depends(get_db),
) -> list[PageNavOut]:
    """Nav entries the caller may see, in sidebar order.

    Body-less by design (``PageNavOut``): this runs on every shell render, and
    the sidebar needs a title and an icon, not every page's full document.
    Drafts are excluded for *everyone*, authors included — an author previews a
    draft by opening it, and having unpublished pages appear in the live sidebar
    would make "draft" mean something different in the nav than on the page.
    """
    rows = await db.scalars(
        select(Page)
        .where(*_readable_filter(authenticated=viewer is not None))
        # Title breaks ties so a duplicated nav_order (a hand-edited row, an
        # import) still renders in a stable order rather than by insertion luck.
        .order_by(Page.nav_order, Page.title)
    )
    return [PageNavOut.model_validate(row) for row in rows]


@router.get("/{slug}", response_model=PageOut)
async def get_page(
    slug: str,
    viewer: User | None = Depends(_viewer),
    db: AsyncSession = Depends(get_db),
) -> PageOut:
    normalized = slug.lower()
    # Filtered in the query, not after it. Loading the row first and then
    # deciding leaks existence through *timing*: fetching a hidden page's body
    # costs measurably more than missing the index entirely, and the delta grows
    # with the stored document — enough to distinguish "this draft exists" from
    # "no such slug" on an endpoint that is unauthenticated and unthrottled.
    page = await db.scalar(
        select(Page).where(
            Page.slug == normalized,
            *_readable_filter(authenticated=viewer is not None),
        )
    )
    if page is not None:
        return PageOut.model_validate(page)

    # Only now, having established the page isn't publicly readable, is it worth
    # the extra round trip to check whether this caller may preview drafts.
    # Everyone else gets the same 404 they'd get for a slug that was never used.
    if await _can_author(db, viewer):
        authored = await db.scalar(select(Page).where(Page.slug == normalized))
        if authored is not None:
            return PageOut.model_validate(authored)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


# --- authoring ---------------------------------------------------------------


async def _page_or_404(db: AsyncSession, page_id: str) -> Page:
    page = await db.get(Page, page_id)
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return page


async def _slug_is_free(db: AsyncSession, slug: str, *, exclude_id: str | None) -> bool:
    query = select(Page.id).where(Page.slug == slug)
    if exclude_id is not None:
        query = query.where(Page.id != exclude_id)
    return await db.scalar(query) is None


@admin_router.get("", response_model=list[PageAdminOut])
async def admin_list_pages(
    _: User = Depends(require_permission("manage_pages")),
    db: AsyncSession = Depends(get_db),
) -> list[PageAdminOut]:
    rows = await db.scalars(select(Page).order_by(Page.nav_order, Page.title))
    return [PageAdminOut.model_validate(row) for row in rows]


@admin_router.post("", response_model=PageAdminOut, status_code=status.HTTP_201_CREATED)
async def create_page(
    body: PageCreate,
    request: Request,
    current_user: User = Depends(require_permission("manage_pages")),
    db: AsyncSession = Depends(get_db),
) -> PageAdminOut:
    if not await _slug_is_free(db, body.slug, exclude_id=None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That slug is already in use"
        )
    page = Page(**body.model_dump())
    db.add(page)
    # Commit *before* emitting: the audit consumer opens its own session, so
    # emitting mid-transaction both blocks on the writer lock and risks
    # recording something that never durably happened.
    await db.commit()
    await event_bus.emit(
        "page.created",
        {"page_id": page.id, "slug": page.slug, "actor_user_id": current_user.id},
    )
    return PageAdminOut.model_validate(page)


@admin_router.patch("/{page_id}", response_model=PageAdminOut)
async def update_page(
    page_id: str,
    body: PageUpdate,
    current_user: User = Depends(require_permission("manage_pages")),
    db: AsyncSession = Depends(get_db),
) -> PageAdminOut:
    page = await _page_or_404(db, page_id)
    # `model_fields_set`, not a None check: `content: null` is a meaningful
    # "clear the body" for this field, so omission and explicit null must stay
    # distinguishable.
    changes = body.model_dump(exclude_unset=True)
    if "slug" in changes and not await _slug_is_free(
        db, changes["slug"], exclude_id=page.id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That slug is already in use"
        )
    for field, value in changes.items():
        setattr(page, field, value)
    await db.commit()
    await event_bus.emit(
        "page.updated",
        {
            "page_id": page.id,
            "slug": page.slug,
            "actor_user_id": current_user.id,
            # Which fields moved, never the document body — the audit log is a
            # trail, not a content store.
            "fields": sorted(changes),
        },
    )
    return PageAdminOut.model_validate(page)


@admin_router.delete("/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_page(
    page_id: str,
    current_user: User = Depends(require_permission("manage_pages")),
    db: AsyncSession = Depends(get_db),
) -> None:
    page = await _page_or_404(db, page_id)
    slug = page.slug
    await db.delete(page)
    await db.commit()
    await event_bus.emit(
        "page.deleted",
        {"page_id": page_id, "slug": slug, "actor_user_id": current_user.id},
    )


@admin_router.post("/reorder", response_model=list[PageAdminOut])
async def reorder_pages(
    body: PageReorder,
    current_user: User = Depends(require_permission("manage_pages")),
    db: AsyncSession = Depends(get_db),
) -> list[PageAdminOut]:
    """Set ``nav_order`` from the supplied id order.

    Whole-list replace: a drag reorders everything relative to everything else,
    so applying it as one write avoids the half-applied state a sequence of
    per-row nudges can leave behind. Ids that don't exist are ignored rather
    than 404ing — a stale tab reordering a list someone else edited should
    settle, not error.
    """
    rows = {row.id: row for row in await db.scalars(select(Page))}
    for position, page_id in enumerate(body.page_ids):
        page = rows.get(page_id)
        if page is not None:
            page.nav_order = position
    await db.commit()
    await event_bus.emit(
        "page.updated",
        {
            "page_id": None,
            "slug": None,
            "actor_user_id": current_user.id,
            "fields": ["nav_order"],
        },
    )
    refreshed = await db.scalars(select(Page).order_by(Page.nav_order, Page.title))
    return [PageAdminOut.model_validate(row) for row in refreshed]
