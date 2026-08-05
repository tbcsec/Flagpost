"""Direct tests for the extracted read service functions (AI Phase 0).

These functions were lifted out of their routers so they're callable outside an
HTTP request — the route tests already prove the endpoints behave unchanged;
this file pins the *standalone* contract the future assistant tools depend on:
the ``None``-returns (where the routers translate to a 404) and the
caller-scoped visibility filtering. Data is set up through the API, as the rest
of the suite does; the assertions call the service functions against a live
``SessionLocal`` session.
"""

from sqlalchemy import select

from db import SessionLocal
from models.competition import Competition
from models.role import Role, RoleAssignment
from models.user import User
from tests.conftest import admin_token
from utils.announcements import list_visible_announcements
from utils.competitions import can_see_competition, get_visible_competition
from utils.feedback import survey_results
from utils.tickets import list_visible_tickets, ticket_detail, visible_ticket_row


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> tuple[str, str]:
    token = (
        await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "password123",
                "display_name": email.split("@")[0],
            },
        )
    ).json()["access_token"]
    uid = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]
    return token, uid


async def _competition(client, admin, *, visibility="public", mode="individual") -> str:
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": mode, "visibility": visibility},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _make_participant(client, comp, email) -> tuple[str, str]:
    token, uid = await _register(client, email)
    async with SessionLocal() as session:
        role = await session.scalar(select(Role).where(Role.name == "Participant"))
        session.add(RoleAssignment(user_id=uid, competition_id=comp, role_id=role.id))
        await session.commit()
    return token, uid


async def _user(uid: str) -> User:
    async with SessionLocal() as session:
        return await session.get(User, uid)


# --- competitions ------------------------------------------------------------


async def test_get_visible_competition_none_semantics(client):
    admin = await admin_token(client)
    private = await _competition(client, admin, visibility="private")
    public = await _competition(client, admin, visibility="public")
    _outsider_token, outsider_id = await _register(client, "outsider@example.com")
    outsider = await _user(outsider_id)
    admin_user = await _user(
        (await client.get("/api/auth/me", headers=_auth(admin))).json()["id"]
    )

    async with SessionLocal() as db:
        # Private + non-member → None (existence not disclosed), never raised.
        assert await get_visible_competition(db, private, outsider) is None
        # Missing id → None, same shape.
        assert await get_visible_competition(db, "does-not-exist", outsider) is None
        # Public → visible to anyone.
        pub = await get_visible_competition(db, public, outsider)
        assert pub is not None and pub.id == public
        # Global admin sees the private one.
        seen = await get_visible_competition(db, private, admin_user)
        assert seen is not None and seen.id == private


async def test_can_see_competition_for_a_member(client):
    admin = await admin_token(client)
    private = await _competition(client, admin, visibility="private")
    _token, member_id = await _make_participant(client, private, "member@example.com")
    member = await _user(member_id)
    async with SessionLocal() as db:
        competition = await db.get(Competition, private)
        assert await can_see_competition(db, competition, member) is True


# --- tickets -----------------------------------------------------------------


async def test_ticket_reads_scope_to_the_caller(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    p1_token, p1_id = await _make_participant(client, comp, "p1@example.com")
    _p2_token, p2_id = await _make_participant(client, comp, "p2@example.com")
    ticket_id = (
        await client.post(
            f"/api/competitions/{comp}/tickets",
            json={"subject": "Help", "body": "stuck on web 100"},
            headers=_auth(p1_token),
        )
    ).json()["id"]

    p1, p2 = await _user(p1_id), await _user(p2_id)
    admin_user = await _user(
        (await client.get("/api/auth/me", headers=_auth(admin))).json()["id"]
    )

    async with SessionLocal() as db:
        # Staff (ticket_assign, admin globally) sees the ticket; the owner sees
        # it; an unrelated competitor sees nothing.
        assert len(await list_visible_tickets(db, comp, admin_user)) == 1
        assert [t.id for t in await list_visible_tickets(db, comp, p1)] == [ticket_id]
        assert await list_visible_tickets(db, comp, p2) == []

        # visible_ticket_row returns None (not raises) for a ticket that's not
        # the caller's, and for a missing id.
        assert await visible_ticket_row(db, comp, ticket_id, p2) is None
        assert await visible_ticket_row(db, comp, "missing", p1) is None
        assert (await visible_ticket_row(db, comp, ticket_id, p1))[0].id == ticket_id


async def test_ticket_detail_strips_internal_notes(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    p1_token, p1_id = await _make_participant(client, comp, "owner@example.com")
    ticket_id = (
        await client.post(
            f"/api/competitions/{comp}/tickets",
            json={"subject": "Help", "body": "hi"},
            headers=_auth(p1_token),
        )
    ).json()["id"]
    # Staff posts an internal note.
    await client.post(
        f"/api/competitions/{comp}/tickets/{ticket_id}/messages",
        json={"body": "staff-only note", "is_internal": True},
        headers=_auth(admin),
    )

    p1 = await _user(p1_id)
    admin_user = await _user(
        (await client.get("/api/auth/me", headers=_auth(admin))).json()["id"]
    )
    async with SessionLocal() as db:
        owner_view = await ticket_detail(db, comp, ticket_id, p1)
        staff_view = await ticket_detail(db, comp, ticket_id, admin_user)
    assert all(not m.is_internal for m in owner_view.messages)
    assert any(m.is_internal for m in staff_view.messages)


# --- feedback ----------------------------------------------------------------


async def test_survey_results_none_and_aggregate(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    survey_id = (
        await client.post(
            f"/api/competitions/{comp}/surveys",
            json={"title": "Exit survey"},
            headers=_auth(admin),
        )
    ).json()["id"]
    question_id = (
        await client.post(
            f"/api/competitions/{comp}/surveys/{survey_id}/questions",
            json={"prompt": "Rate the event", "type": "rating_1_5"},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.put(
        f"/api/competitions/{comp}/surveys/{survey_id}",
        json={"title": "Exit survey", "is_open": True},
        headers=_auth(admin),
    )
    resp = await client.post(
        f"/api/competitions/{comp}/surveys/{survey_id}/responses",
        json={"answers": [{"question_id": question_id, "value": "4"}]},
        headers=_auth(admin),
    )
    assert resp.status_code == 204, resp.text

    async with SessionLocal() as db:
        # Missing survey → None, never raised.
        assert await survey_results(db, comp, "no-such-survey") is None
        results = await survey_results(db, comp, survey_id)
    assert results is not None
    assert results.response_count == 1
    q = next(r for r in results.questions if r.question_id == question_id)
    assert q.answered == 1
    assert q.average == 4.0


# --- announcements -----------------------------------------------------------


async def test_list_visible_announcements_filters_by_audience(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    _a_token, a_id = await _make_participant(client, comp, "a@example.com")
    _b_token, b_id = await _make_participant(client, comp, "b@example.com")

    await client.post(
        f"/api/competitions/{comp}/announcements",
        json={"title": "Welcome", "body": "to all", "audience_type": "all"},
        headers=_auth(admin),
    )
    await client.post(
        f"/api/competitions/{comp}/announcements",
        json={
            "title": "For A",
            "body": "just you",
            "audience_type": "users",
            "audience_ids": [a_id],
        },
        headers=_auth(admin),
    )

    user_a, user_b = await _user(a_id), await _user(b_id)
    admin_user = await _user(
        (await client.get("/api/auth/me", headers=_auth(admin))).json()["id"]
    )
    async with SessionLocal() as db:
        a_titles = {x.title for x in await list_visible_announcements(db, comp, user_a)}
        b_titles = {x.title for x in await list_visible_announcements(db, comp, user_b)}
        staff_titles = {
            x.title for x in await list_visible_announcements(db, comp, admin_user)
        }
    assert a_titles == {"Welcome", "For A"}  # targeted user sees both
    assert b_titles == {"Welcome"}  # other competitor sees only "all"
    assert staff_titles == {"Welcome", "For A"}  # staff sees their sent history
