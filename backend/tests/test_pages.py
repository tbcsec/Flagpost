"""Custom pages (#198, ADR-0034).

The load-bearing cases here are the **visibility matrix** and the fact that a
page a caller may not read is a 404 rather than a 403 — an error code that
distinguishes "forbidden" from "absent" confirms a draft's existence to anyone
who guesses its slug.

The rendering-safety property (page content can never execute) is structural
rather than testable from here: the server stores the document verbatim and the
frontend renders it as a React tree under ProseMirror's schema (ADR-0034). What
*is* tested here is that the server never transforms it — a body containing
script-shaped text must round-trip unchanged, so the safety argument rests on
the renderer and not on backend sanitising that could silently regress.
"""

import pytest
from sqlalchemy import select

from db import SessionLocal
from models.page import Page
from schemas.page import RESERVED_SLUGS
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _doc(text: str = "Hello") -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


async def _participant_token(client, name="pleb") -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"display_name": name, "password": "password123"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["access_token"]


async def _create(client, admin, **overrides) -> dict:
    body = {
        "slug": "about",
        "title": "About",
        "content": _doc(),
        "icon": "document",
        "visibility": "authenticated",
        "draft": False,
        **overrides,
    }
    resp = await client.post("/api/admin/pages", json=body, headers=_auth(admin))
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- authoring permission ----------------------------------------------------


async def test_creating_a_page_requires_the_permission(client):
    token = await _participant_token(client)
    resp = await client.post(
        "/api/admin/pages",
        json={"slug": "about", "title": "About"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_admin_listing_requires_the_permission(client):
    token = await _participant_token(client)
    assert (await client.get("/api/admin/pages", headers=_auth(token))).status_code == 403


async def test_authoring_is_unreachable_anonymously(client):
    assert (await client.get("/api/admin/pages")).status_code == 401


# --- slugs -------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug",
    ["has space", "-leading", "trailing-", "a", "x" * 61, "under_score", "slash/es"],
)
async def test_invalid_slugs_are_rejected(client, slug):
    admin = await admin_token(client)
    resp = await client.post(
        "/api/admin/pages",
        json={"slug": slug, "title": "T"},
        headers=_auth(admin),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("slug", ["login", "admin", "api", "p", "setup"])
async def test_reserved_slugs_are_rejected(client, slug):
    """Pages live under /p/, so these don't collide *today* — they're reserved
    so that moving pages to top-level paths later can't strand existing rows."""
    admin = await admin_token(client)
    resp = await client.post(
        "/api/admin/pages",
        json={"slug": slug, "title": "T"},
        headers=_auth(admin),
    )
    assert resp.status_code == 422, resp.text


async def test_reserved_list_covers_every_real_top_level_route():
    """Guards the list against drift: if a route is added to the app without
    being reserved here, a page could later shadow it."""
    for path in ("login", "register", "setup", "admin", "challenges", "scoreboard"):
        assert path in RESERVED_SLUGS


async def test_uppercase_slug_is_normalized_not_rejected(client):
    """Matches the identity-provider precedent, which lowercases before
    validating — a pasted "About" becomes /p/about rather than a 422."""
    admin = await admin_token(client)
    page = await _create(client, admin, slug="About-Us")
    assert page["slug"] == "about-us"
    assert (await client.get("/api/pages/about-us", headers=_auth(admin))).status_code == 200


async def test_duplicate_slug_is_a_conflict(client):
    admin = await admin_token(client)
    await _create(client, admin)
    resp = await client.post(
        "/api/admin/pages",
        json={"slug": "about", "title": "Another"},
        headers=_auth(admin),
    )
    assert resp.status_code == 409


async def test_renaming_onto_another_slug_is_a_conflict(client):
    admin = await admin_token(client)
    await _create(client, admin, slug="about")
    other = await _create(client, admin, slug="sponsors", title="Sponsors")
    resp = await client.patch(
        f"/api/admin/pages/{other['id']}",
        json={"slug": "about"},
        headers=_auth(admin),
    )
    assert resp.status_code == 409


async def test_a_page_can_keep_its_own_slug_on_update(client):
    """The uniqueness check must exclude the row being edited, or every save
    without a slug change would 409."""
    admin = await admin_token(client)
    page = await _create(client, admin)
    resp = await client.patch(
        f"/api/admin/pages/{page['id']}",
        json={"slug": "about", "title": "About us"},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "About us"


# --- the visibility matrix (ADR-0034) ----------------------------------------


async def test_public_page_is_readable_anonymously(client):
    admin = await admin_token(client)
    await _create(client, admin, visibility="public", draft=False)
    resp = await client.get("/api/pages/about")
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "About"


async def test_authenticated_page_is_404_anonymously(client):
    """404, not 403 — the code must not confirm the page exists."""
    admin = await admin_token(client)
    await _create(client, admin, visibility="authenticated", draft=False)
    assert (await client.get("/api/pages/about")).status_code == 404


async def test_authenticated_page_is_readable_when_logged_in(client):
    admin = await admin_token(client)
    await _create(client, admin, visibility="authenticated", draft=False)
    token = await _participant_token(client)
    resp = await client.get("/api/pages/about", headers=_auth(token))
    assert resp.status_code == 200, resp.text


async def test_draft_is_404_for_anonymous_and_for_ordinary_users(client):
    admin = await admin_token(client)
    await _create(client, admin, visibility="public", draft=True)
    assert (await client.get("/api/pages/about")).status_code == 404
    token = await _participant_token(client)
    assert (
        await client.get("/api/pages/about", headers=_auth(token))
    ).status_code == 404


async def test_draft_is_previewable_by_an_author(client):
    admin = await admin_token(client)
    await _create(client, admin, draft=True)
    resp = await client.get("/api/pages/about", headers=_auth(admin))
    assert resp.status_code == 200, resp.text


async def test_unknown_slug_is_404(client):
    assert (await client.get("/api/pages/nope")).status_code == 404


# --- the nav list ------------------------------------------------------------


async def test_nav_list_hides_drafts_and_respects_visibility(client):
    admin = await admin_token(client)
    await _create(client, admin, slug="public-page", title="Public", visibility="public", draft=False)
    await _create(client, admin, slug="members", title="Members", visibility="authenticated", draft=False)
    await _create(client, admin, slug="wip", title="WIP", visibility="public", draft=True)

    anon = (await client.get("/api/pages")).json()
    assert [p["slug"] for p in anon] == ["public-page"]

    token = await _participant_token(client)
    seen = (await client.get("/api/pages", headers=_auth(token))).json()
    assert sorted(p["slug"] for p in seen) == ["members", "public-page"]


async def test_nav_list_hides_drafts_even_from_authors(client):
    """A draft in the live sidebar would make "draft" mean something different
    in the nav than on the page itself."""
    admin = await admin_token(client)
    await _create(client, admin, slug="wip", draft=True)
    assert (await client.get("/api/pages", headers=_auth(admin))).json() == []


async def test_nav_list_carries_no_body(client):
    """The shell fetches this on every render; it needs a title and an icon."""
    admin = await admin_token(client)
    await _create(client, admin, visibility="public", draft=False)
    entry = (await client.get("/api/pages")).json()[0]
    assert set(entry) == {"slug", "title", "icon", "nav_order"}


async def test_nav_list_is_ordered(client):
    admin = await admin_token(client)
    await _create(client, admin, slug="third", title="Third", nav_order=2, visibility="public", draft=False)
    await _create(client, admin, slug="first", title="First", nav_order=0, visibility="public", draft=False)
    await _create(client, admin, slug="second", title="Second", nav_order=1, visibility="public", draft=False)
    listed = (await client.get("/api/pages")).json()
    assert [p["slug"] for p in listed] == ["first", "second", "third"]


async def test_equal_nav_order_falls_back_to_title(client):
    """A duplicated order (hand-edited row, import) must still be stable."""
    admin = await admin_token(client)
    await _create(client, admin, slug="beta", title="Beta", nav_order=0, visibility="public", draft=False)
    await _create(client, admin, slug="alpha", title="Alpha", nav_order=0, visibility="public", draft=False)
    listed = (await client.get("/api/pages")).json()
    assert [p["slug"] for p in listed] == ["alpha", "beta"]


# --- content handling --------------------------------------------------------


async def test_malformed_content_is_rejected(client):
    admin = await admin_token(client)
    resp = await client.post(
        "/api/admin/pages",
        json={"slug": "bad", "title": "Bad", "content": {"nope": True}},
        headers=_auth(admin),
    )
    assert resp.status_code == 422, resp.text


async def test_visually_empty_content_normalizes_to_null(client):
    admin = await admin_token(client)
    page = await _create(
        client,
        admin,
        slug="blank",
        content={"type": "doc", "content": [{"type": "paragraph"}]},
    )
    assert page["content"] is None


async def test_oversized_content_is_rejected(client):
    admin = await admin_token(client)
    huge = _doc("x" * 250_000)
    resp = await client.post(
        "/api/admin/pages",
        json={"slug": "huge", "title": "Huge", "content": huge},
        headers=_auth(admin),
    )
    assert resp.status_code == 422, resp.text


async def test_script_shaped_text_round_trips_unchanged(client):
    """The server must not sanitise, rewrite or escape the document.

    Safety comes from the renderer (a React tree under ProseMirror's schema,
    ADR-0034), so silently transforming content here would hide a regression in
    that argument rather than reinforce it — and would corrupt a page that
    legitimately discusses markup, which a CTF platform's pages plausibly do.
    """
    admin = await admin_token(client)
    payload = _doc("<script>alert(1)</script>")
    page = await _create(client, admin, slug="xss", content=payload)
    assert page["content"] == payload
    fetched = await client.get("/api/pages/xss", headers=_auth(admin))
    assert fetched.json()["content"] == payload


# --- events + audit ----------------------------------------------------------


async def test_mutations_emit_audited_events(client):
    admin = await admin_token(client)
    page = await _create(client, admin)
    await client.patch(
        f"/api/admin/pages/{page['id']}",
        json={"title": "Renamed"},
        headers=_auth(admin),
    )
    await client.delete(f"/api/admin/pages/{page['id']}", headers=_auth(admin))

    entries = (await client.get("/api/admin/audit-log", headers=_auth(admin))).json()
    kinds = {e["event_name"] for e in entries["items"]}
    assert {"page.created", "page.updated", "page.deleted"} <= kinds


async def test_update_event_names_fields_but_never_the_body(client):
    """The audit log is a trail, not a content store."""
    admin = await admin_token(client)
    page = await _create(client, admin)
    await client.patch(
        f"/api/admin/pages/{page['id']}",
        json={"content": _doc("secret rewrite")},
        headers=_auth(admin),
    )
    entries = (await client.get("/api/admin/audit-log", headers=_auth(admin))).json()
    updated = [e for e in entries["items"] if e["event_name"] == "page.updated"]
    assert updated
    assert "secret rewrite" not in str(updated)


# --- delete / reorder --------------------------------------------------------


async def test_delete_removes_the_page(client):
    admin = await admin_token(client)
    page = await _create(client, admin)
    resp = await client.delete(
        f"/api/admin/pages/{page['id']}", headers=_auth(admin)
    )
    assert resp.status_code == 204
    assert (await client.get("/api/pages/about")).status_code == 404


async def test_reorder_sets_positions(client):
    admin = await admin_token(client)
    a = await _create(client, admin, slug="aa", title="A", visibility="public", draft=False)
    b = await _create(client, admin, slug="bb", title="B", visibility="public", draft=False)
    c = await _create(client, admin, slug="cc", title="C", visibility="public", draft=False)

    resp = await client.post(
        "/api/admin/pages/reorder",
        json={"page_ids": [c["id"], a["id"], b["id"]]},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert [p["slug"] for p in (await client.get("/api/pages")).json()] == ["cc", "aa", "bb"]


async def test_reorder_ignores_unknown_ids(client):
    """A stale tab reordering a list someone else edited should settle."""
    admin = await admin_token(client)
    a = await _create(client, admin, slug="aa", title="A", visibility="public", draft=False)
    resp = await client.post(
        "/api/admin/pages/reorder",
        json={"page_ids": ["does-not-exist", a["id"]]},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text


async def test_reorder_requires_the_permission(client):
    token = await _participant_token(client)
    resp = await client.post(
        "/api/admin/pages/reorder", json={"page_ids": []}, headers=_auth(token)
    )
    assert resp.status_code == 403


# --- defaults ----------------------------------------------------------------


async def test_a_page_defaults_to_unpublished_and_members_only(client):
    """A page must never be live the instant it's created."""
    admin = await admin_token(client)
    resp = await client.post(
        "/api/admin/pages",
        json={"slug": "fresh", "title": "Fresh"},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["draft"] is True
    assert body["visibility"] == "authenticated"

    async with SessionLocal() as db:
        row = await db.scalar(select(Page).where(Page.slug == "fresh"))
        assert row.icon == "document"
        assert row.nav_order == 0


# --- icon allowlist (adversarial review finding) -----------------------------


@pytest.mark.parametrize(
    "icon", ["__proto__", "constructor", "toString", "hasOwnProperty", "valueOf"]
)
async def test_prototype_keys_are_rejected_as_icons(client, icon):
    """The high-severity case: these are ordinary-looking strings but inherited
    `Object.prototype` keys in the browser, so a naive client lookup returns a
    non-element and crashes the sidebar on *every* authenticated route —
    including the admin screen needed to undo it. A `manage_pages` holder is a
    delegated content editor, so that would be an availability escalation out of
    a content grant (ADR-0034)."""
    admin = await admin_token(client)
    resp = await client.post(
        "/api/admin/pages",
        json={"slug": "brick", "title": "Brick", "icon": icon},
        headers=_auth(admin),
    )
    assert resp.status_code == 422, resp.text


async def test_unknown_icon_is_rejected(client):
    admin = await admin_token(client)
    resp = await client.post(
        "/api/admin/pages",
        json={"slug": "weird", "title": "Weird", "icon": "not-a-real-icon"},
        headers=_auth(admin),
    )
    assert resp.status_code == 422, resp.text


async def test_icon_cannot_be_smuggled_through_an_update(client):
    admin = await admin_token(client)
    page = await _create(client, admin)
    resp = await client.patch(
        f"/api/admin/pages/{page['id']}",
        json={"icon": "__proto__"},
        headers=_auth(admin),
    )
    assert resp.status_code == 422, resp.text


async def test_every_catalog_icon_is_accepted(client):
    """The allowlist must not be so tight that the picker offers unusable
    glyphs — every name the frontend renders has to round-trip."""
    from models.page import ICON_NAMES

    admin = await admin_token(client)
    for index, icon in enumerate(sorted(ICON_NAMES)):
        resp = await client.post(
            "/api/admin/pages",
            json={"slug": f"icon-{index}", "title": icon, "icon": icon},
            headers=_auth(admin),
        )
        assert resp.status_code == 201, f"{icon}: {resp.text}"
