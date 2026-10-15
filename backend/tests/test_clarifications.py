"""Clarifications (#450): a competitor asks about a challenge privately (a
ticket linked to it); a judge can answer privately, or send the answer to
everyone — the question as the judge words it plus the answer, as an
announcement about that challenge, listed on its page, and never carrying who
asked."""

import json

import pytest
from sqlalchemy import select

from db import SessionLocal
from models.announcement import Announcement
from models.challenge import Challenge
from models.competition import Competition
from models.notification import Notification
from models.role import Role, RoleAssignment
from tests.test_judge_submissions import _auth, _player, _setup
from tests.ws_client import WsTestClient
from utils.event_bus import event_bus

import main  # noqa: E402

QUESTION = "Hi, it's Mei from team Lambda — can the numbers be negative? My solution fails."


class Events:
    def __init__(self, *names):
        self.names, self.seen = names, []

    async def __call__(self, name, payload):
        self.seen.append((name, payload))

    def __enter__(self):
        for n in self.names:
            event_bus.subscribe(n, self, owner="test-clarify")
        return self

    def __exit__(self, *exc):
        event_bus.unsubscribe_owner("test-clarify")


async def _ask(client, comp, token, chal, body=QUESTION) -> str:
    resp = await client.post(
        f"/api/competitions/{comp}/tickets",
        json={"subject": "Question about A + B", "body": body, "challenge_id": chal, "kind": "question"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _clarify(client, comp, token, ticket, question="Can the numbers be negative?", answer="Yes."):
    return client.post(
        f"/api/competitions/{comp}/tickets/{ticket}/clarify",
        json={"question": question, "answer": answer},
        headers=_auth(token),
    )


def _clarifications(client, comp, chal, token):
    return client.get(f"/api/competitions/{comp}/challenges/{chal}/clarifications", headers=_auth(token))


async def test_a_judge_sends_an_answer_to_everyone(client, object_storage):
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    omar = await _player(client, comp, "omar")
    ticket = await _ask(client, comp, mei, chal)

    with Events("announcement.published", "ticket.message_posted") as events:
        resp = await _clarify(client, comp, admin, ticket)
        await event_bus.wait_for_background()
    assert resp.status_code == 200, resp.text
    # The asker gets the answer in their thread, marked as sent to everyone.
    answer = resp.json()["messages"][-1]
    assert answer["body"] == "Yes." and answer["sent_to_all"] is True and not answer["is_internal"]

    # Everyone sees it on the challenge's page…
    listed = (await _clarifications(client, comp, chal, omar)).json()
    assert [(c["question"], c["body"]) for c in listed] == [("Can the numbers be negative?", "Yes.")]
    # …and in the ordinary feed, as a clarification about the challenge.
    [feed] = (await client.get(f"/api/competitions/{comp}/announcements", headers=_auth(omar))).json()
    assert feed["kind"] == "clarification" and feed["challenge_id"] == chal
    assert feed["title"] == "A + B" and feed["question"] == "Can the numbers be negative?"

    # Nothing anywhere says who asked: not the feed, nor the event payload.
    names = {n for n, _ in events.seen}
    assert names == {"announcement.published", "ticket.message_posted"}
    [published] = [p for n, p in events.seen if n == "announcement.published"]
    assert published["kind"] == "clarification" and published["challenge_id"] == chal
    for blob in (json.dumps(feed), json.dumps(published)):
        assert "mei" not in blob.lower() and ticket not in blob

    # The bell notification links to the problem.
    async with SessionLocal() as db:
        omar_id = (await client.get("/api/auth/me", headers=_auth(omar))).json()["id"]
        [note] = (await db.scalars(select(Notification).where(Notification.user_id == omar_id))).all()
    assert note.type == "announcement.clarification" and note.link == f"/challenges/{chal}"


async def test_only_staff_who_may_announce_can_send_to_all(client, object_storage):
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    ticket = await _ask(client, comp, mei, chal)
    # A competitor can't, even on their own ticket.
    assert (await _clarify(client, comp, mei, ticket)).status_code == 403

    # A helpdesk role that answers tickets but may not announce can't either.
    helper = await _player(client, comp, "helper")
    async with SessionLocal() as db:
        role = Role(
            name="Helpdesk", scope="competition",
            permissions=["challenge_view", "ticket_view", "ticket_respond", "ticket_assign"],
        )
        db.add(role)
        await db.flush()
        helper_id = (await client.get("/api/auth/me", headers=_auth(helper))).json()["id"]
        db.add(RoleAssignment(user_id=helper_id, competition_id=comp, role_id=role.id))
        await db.commit()
    resp = await _clarify(client, comp, helper, ticket)
    assert resp.status_code == 403 and "announcements" in resp.json()["detail"]
    async with SessionLocal() as db:
        assert (await db.scalars(select(Announcement))).all() == []


async def test_only_a_question_about_a_visible_challenge(client, object_storage):
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    general = (
        await client.post(
            f"/api/competitions/{comp}/tickets",
            json={"subject": "Wifi", "body": "The wifi is down"},
            headers=_auth(mei),
        )
    ).json()["id"]
    assert (await _clarify(client, comp, admin, general)).status_code == 400

    ticket = await _ask(client, comp, mei, chal)
    async with SessionLocal() as db:
        (await db.get(Challenge, chal)).state = "draft"
        await db.commit()
    resp = await _clarify(client, comp, admin, ticket)
    assert resp.status_code == 400 and "privately" in resp.json()["detail"]


async def test_a_challenge_hidden_later_hides_its_clarifications(client, object_storage):
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    await _clarify(client, comp, admin, await _ask(client, comp, mei, chal))
    async with SessionLocal() as db:
        (await db.get(Challenge, chal)).state = "draft"
        await db.commit()
    assert (await _clarifications(client, comp, chal, mei)).status_code == 404
    feed = (await client.get(f"/api/competitions/{comp}/announcements", headers=_auth(mei))).json()
    assert feed == []
    # Nor does a reconnect's snapshot carry it.
    async with WsTestClient(main.app, f"/ws/announcements/{comp}") as ws:
        await ws.send_json({"token": mei})
        assert (await ws.receive_json())["type"] == "auth_ok"
        assert (await ws.receive_json())["announcements"] == []
    # Staff still see their own sent history.
    staff_feed = (await client.get(f"/api/competitions/{comp}/announcements", headers=_auth(admin))).json()
    assert len(staff_feed) == 1


async def test_deleting_the_challenge_deletes_its_clarifications(client, object_storage):
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    await _clarify(client, comp, admin, await _ask(client, comp, mei, chal))
    await client.post(
        f"/api/competitions/{comp}/announcements", json={"title": "Hello", "body": "Welcome"},
        headers=_auth(admin),
    )
    resp = await client.delete(f"/api/competitions/{comp}/challenges/{chal}", headers=_auth(admin))
    assert resp.status_code == 204, resp.text
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Announcement))).all()
    assert [(a.kind, a.title) for a in rows] == [("announcement", "Hello")]


async def test_the_live_frame_says_which_challenge(client, object_storage):
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    ticket = await _ask(client, comp, mei, chal)
    async with WsTestClient(main.app, f"/ws/announcements/{comp}") as ws:
        await ws.send_json({"token": mei})
        assert (await ws.receive_json())["type"] == "auth_ok"
        assert (await ws.receive_json())["type"] == "announcements"
        await _clarify(client, comp, admin, ticket)
        await event_bus.wait_for_background()
        frame = (await ws.receive_json())["announcement"]
    assert frame["kind"] == "clarification" and frame["challenge_id"] == chal
    assert frame["question"] == "Can the numbers be negative?" and frame["body"] == "Yes."
    assert "mei" not in json.dumps(frame).lower()


async def test_ordinary_announcements_are_unchanged(client, object_storage):
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    await client.post(
        f"/api/competitions/{comp}/announcements", json={"title": "Hello", "body": "Welcome"},
        headers=_auth(admin),
    )
    [a] = (await client.get(f"/api/competitions/{comp}/announcements", headers=_auth(mei))).json()
    assert a["kind"] == "announcement" and a["challenge_id"] is None and a["question"] is None
    assert (await _clarifications(client, comp, chal, mei)).json() == []


@pytest.mark.competition_lifecycle
async def test_nothing_goes_to_everyone_while_competitors_cant_see_the_challenge(client, object_storage):
    """Before the start the status gate hides every challenge, so a clarification
    can't be sent — and one sent while running is hidden again if play is reset."""
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    ticket = await _ask(client, comp, admin, chal)  # staff can file one before the start
    resp = await _clarify(client, comp, admin, ticket)
    assert resp.status_code == 400 and "privately" in resp.json()["detail"]

    async with SessionLocal() as db:
        (await db.get(Competition, comp)).status = "running"
        await db.commit()
    assert (await _clarify(client, comp, admin, ticket)).status_code == 200
    feed = (await client.get(f"/api/competitions/{comp}/announcements", headers=_auth(mei))).json()
    assert [a["kind"] for a in feed] == ["clarification"]

    async with SessionLocal() as db:
        (await db.get(Competition, comp)).status = "not_started"
        await db.commit()
    feed = (await client.get(f"/api/competitions/{comp}/announcements", headers=_auth(mei))).json()
    assert feed == []


# --- a question is one message ---------------------------------------------------------


async def test_a_question_is_read_only_for_the_asker(client, object_storage):
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    ticket = await _ask(client, comp, mei, chal)
    msgs = f"/api/competitions/{comp}/tickets/{ticket}/messages"
    # No follow-up in the thread: a follow-up is a new question.
    resp = await client.post(msgs, json={"body": "Also, what about zero?"}, headers=_auth(mei))
    assert resp.status_code == 403 and "new question" in resp.json()["detail"]
    # Nor a screenshot on the question itself.
    detail = (await client.get(f"/api/competitions/{comp}/tickets/{ticket}", headers=_auth(mei))).json()
    first = detail["messages"][0]["id"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    up = await client.post(
        f"/api/competitions/{comp}/tickets/{ticket}/messages/{first}/attachments",
        files={"file": ("shot.png", png, "image/png")}, headers=_auth(mei),
    )
    assert up.status_code == 403
    assert detail["kind"] == "question" and detail["status"] == "open"

    # Text both ways: a judge's answer can't carry a screenshot either.
    answered = (await client.post(msgs, json={"body": "See the statement."}, headers=_auth(admin))).json()
    answer = answered["messages"][-1]["id"]
    staff_up = await client.post(
        f"/api/competitions/{comp}/tickets/{ticket}/messages/{answer}/attachments",
        files={"file": ("shot.png", png, "image/png")}, headers=_auth(admin),
    )
    assert staff_up.status_code == 403


async def test_a_judges_answer_settles_the_question(client, object_storage):
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    ticket = await _ask(client, comp, mei, chal)
    msgs = f"/api/competitions/{comp}/tickets/{ticket}/messages"
    # A staff-only note doesn't answer it…
    note = await client.post(msgs, json={"body": "checking", "is_internal": True}, headers=_auth(admin))
    assert note.json()["status"] == "open"
    # …a reply does, and a second answer keeps it answered.
    assert (await client.post(msgs, json={"body": "Yes."}, headers=_auth(admin))).json()["status"] == "resolved"
    assert (await client.post(msgs, json={"body": "Also yes."}, headers=_auth(admin))).json()["status"] == "resolved"

    other = await _ask(client, comp, mei, chal)
    assert (await _clarify(client, comp, admin, other)).json()["status"] == "resolved"


async def test_a_question_needs_a_challenge_the_asker_can_see(client, object_storage):
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    url = f"/api/competitions/{comp}/tickets"
    general = await client.post(url, json={"subject": "Q", "body": "?", "kind": "question"}, headers=_auth(mei))
    assert general.status_code == 400
    async with SessionLocal() as db:
        (await db.get(Challenge, chal)).state = "draft"
        await db.commit()
    draft = await client.post(
        url, json={"subject": "Q", "body": "?", "kind": "question", "challenge_id": chal}, headers=_auth(mei)
    )
    assert draft.status_code == 404


async def test_support_tickets_keep_their_conversation(client, object_storage):
    admin, comp, chal = await _setup(client)
    mei = await _player(client, comp, "mei")
    with Events("ticket.created") as events:
        ticket = (
            await client.post(
                f"/api/competitions/{comp}/tickets",
                json={"subject": "Server down", "body": "A + B's checker is down", "challenge_id": chal},
                headers=_auth(mei),
            )
        ).json()
    assert ticket["kind"] == "support"
    [(_, created)] = events.seen
    assert created["kind"] == "support"
    msgs = f"/api/competitions/{comp}/tickets/{ticket['id']}/messages"
    await client.post(msgs, json={"body": "Fixed."}, headers=_auth(admin))
    reply = await client.post(msgs, json={"body": "Thanks, works now."}, headers=_auth(mei))
    assert reply.status_code == 200 and reply.json()["status"] == "open"
