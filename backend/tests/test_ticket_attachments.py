"""Ticket attachments (issue #80): magic-byte sniffing, the size/count caps,
who may attach and delete, and the internal-note visibility rule."""

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from models.ticket_attachment import TicketAttachment
from tests.conftest import admin_token

# Real magic bytes — the endpoint sniffs rather than trusting Content-Type.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 40


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": email.split("@")[0],
        },
    )
    return resp.json()["access_token"]


async def _competition(client) -> tuple[str, str]:
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual"},
            headers=_auth(admin),
        )
    ).json()["id"]
    return admin, comp


async def _participant(client, comp, email) -> str:
    token = await _register(client, email)
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()
    async with SessionLocal() as session:
        from models.role import Role, RoleAssignment

        role = await session.scalar(select(Role).where(Role.name == "Participant"))
        session.add(
            RoleAssignment(user_id=me["id"], competition_id=comp, role_id=role.id)
        )
        await session.commit()
    return token


async def _open_ticket(client, comp, token) -> tuple[str, str]:
    """Open a ticket; return (ticket_id, first_message_id)."""
    detail = (
        await client.post(
            f"/api/competitions/{comp}/tickets",
            json={"subject": "Help", "body": "see screenshot"},
            headers=_auth(token),
        )
    ).json()
    return detail["id"], detail["messages"][0]["id"]


def _attach(client, comp, ticket, message, token, content=PNG, name="shot.png",
            declared="image/png"):
    return client.post(
        f"/api/competitions/{comp}/tickets/{ticket}/messages/{message}/attachments",
        files={"file": (name, content, declared)},
        headers=_auth(token),
    )


async def test_upload_sniffs_type_and_namespaces_key(client, object_storage):
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)

    resp = await _attach(client, comp, ticket, message, token)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == "shot.png"
    assert body["content_type"] == "image/png"
    assert body["size_bytes"] == len(PNG)
    assert "object_key" not in body  # internal (§13.3)

    async with SessionLocal() as session:
        row = await session.scalar(select(TicketAttachment))
    assert row.object_key.startswith(f"{comp}/tickets/{ticket}/")
    assert object_storage.read(row.object_key) == PNG


async def test_mislabelled_file_is_rejected_by_sniffing(client):
    """A script declared as image/png must not get through — the bytes decide."""
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)

    resp = await _attach(
        client, comp, ticket, message, token,
        content=b"<script>alert(1)</script>" + b"\x00" * 40,
        name="evil.png", declared="image/png",
    )
    assert resp.status_code == 415


async def test_gif_and_svg_are_rejected(client):
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)

    gif = await _attach(
        client, comp, ticket, message, token,
        content=b"GIF89a" + b"\x00" * 40, name="a.gif", declared="image/gif",
    )
    assert gif.status_code == 415
    svg = await _attach(
        client, comp, ticket, message, token,
        content=b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        name="a.svg", declared="image/svg+xml",
    )
    assert svg.status_code == 415


async def test_jpeg_and_webp_accepted(client):
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)

    jpeg = await _attach(client, comp, ticket, message, token, content=JPEG,
                         name="a.jpg", declared="image/jpeg")
    assert jpeg.status_code == 201
    assert jpeg.json()["content_type"] == "image/jpeg"
    webp = await _attach(client, comp, ticket, message, token, content=WEBP,
                         name="a.webp", declared="image/webp")
    assert webp.status_code == 201
    assert webp.json()["content_type"] == "image/webp"


async def test_oversize_rejected(client):
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)

    big = PNG + b"\x00" * 2_700_000
    resp = await _attach(client, comp, ticket, message, token, content=big)
    assert resp.status_code == 413


async def test_per_ticket_cap_spans_messages_and_authors(client):
    """The cap is 5 per *ticket* — not per message, and staff share it."""
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)

    for _ in range(4):
        assert (await _attach(client, comp, ticket, message, token)).status_code == 201

    # A reply creates a second message; the 5th attachment still fits.
    reply = (
        await client.post(
            f"/api/competitions/{comp}/tickets/{ticket}/messages",
            json={"body": "one more"},
            headers=_auth(token),
        )
    ).json()
    second = reply["messages"][-1]["id"]
    assert (await _attach(client, comp, ticket, second, token)).status_code == 201

    # The 6th is refused, across the whole ticket.
    assert (await _attach(client, comp, ticket, second, token)).status_code == 409

    # Staff hit the same shared cap on their own reply.
    staff_reply = (
        await client.post(
            f"/api/competitions/{comp}/tickets/{ticket}/messages",
            json={"body": "looking"},
            headers=_auth(admin),
        )
    ).json()
    staff_msg = staff_reply["messages"][-1]["id"]
    assert (await _attach(client, comp, ticket, staff_msg, admin)).status_code == 409


async def test_delete_frees_a_slot(client, object_storage):
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)

    ids = []
    for _ in range(5):
        ids.append((await _attach(client, comp, ticket, message, token)).json()["id"])
    assert (await _attach(client, comp, ticket, message, token)).status_code == 409

    async with SessionLocal() as session:
        key = await session.scalar(
            select(TicketAttachment.object_key).where(TicketAttachment.id == ids[0])
        )
    resp = await client.delete(
        f"/api/competitions/{comp}/tickets/{ticket}/attachments/{ids[0]}",
        headers=_auth(token),
    )
    assert resp.status_code == 204
    assert not object_storage.exists(key)
    # A freed slot is immediately reusable — the cap is a live count.
    assert (await _attach(client, comp, ticket, message, token)).status_code == 201


async def test_cannot_attach_to_someone_elses_message(client):
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)

    # Staff may not bolt an image onto the competitor's message…
    assert (await _attach(client, comp, ticket, message, admin)).status_code == 403

    # …nor the competitor onto staff's reply.
    staff_reply = (
        await client.post(
            f"/api/competitions/{comp}/tickets/{ticket}/messages",
            json={"body": "hi"},
            headers=_auth(admin),
        )
    ).json()
    staff_msg = staff_reply["messages"][-1]["id"]
    assert (await _attach(client, comp, ticket, staff_msg, token)).status_code == 403


async def test_outsider_cannot_reach_another_users_ticket(client):
    admin, comp = await _competition(client)
    owner = await _participant(client, comp, "owner@example.com")
    ticket, message = await _open_ticket(client, comp, owner)
    attachment = (await _attach(client, comp, ticket, message, owner)).json()

    other = await _participant(client, comp, "other@example.com")
    # Someone else's ticket is hidden entirely (404, not 403).
    assert (
        await client.get(
            f"/api/competitions/{comp}/tickets/{ticket}/attachments/{attachment['id']}/content",
            headers=_auth(other),
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/competitions/{comp}/tickets/{ticket}/attachments/{attachment['id']}",
            headers=_auth(other),
        )
    ).status_code == 404


async def test_content_served_defensively_to_opener_and_staff(client):
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)
    attachment = (await _attach(client, comp, ticket, message, token)).json()

    for actor in (token, admin):  # the opener previews too, not just staff
        resp = await client.get(
            f"/api/competitions/{comp}/tickets/{ticket}/attachments/{attachment['id']}/content",
            headers=_auth(actor),
        )
        assert resp.status_code == 200
        assert resp.content == PNG
        assert resp.headers["content-type"].startswith("image/png")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in resp.headers["content-security-policy"]


async def test_internal_note_attachment_hidden_from_competitor(client):
    """An image on a staff internal note must vanish with the note itself —
    both from the thread and from a direct fetch by id."""
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, _ = await _open_ticket(client, comp, token)

    note = (
        await client.post(
            f"/api/competitions/{comp}/tickets/{ticket}/messages",
            json={"body": "internal", "is_internal": True},
            headers=_auth(admin),
        )
    ).json()
    note_msg = note["messages"][-1]["id"]
    attachment = (await _attach(client, comp, ticket, note_msg, admin)).json()

    # Staff see the note and its attachment nested under it.
    staff_view = (
        await client.get(
            f"/api/competitions/{comp}/tickets/{ticket}", headers=_auth(admin)
        )
    ).json()
    internal = [m for m in staff_view["messages"] if m["is_internal"]]
    assert len(internal[0]["attachments"]) == 1

    # The competitor sees neither the note nor any attachment.
    own_view = (
        await client.get(
            f"/api/competitions/{comp}/tickets/{ticket}", headers=_auth(token)
        )
    ).json()
    assert all(not m["is_internal"] for m in own_view["messages"])
    assert all(m["attachments"] == [] for m in own_view["messages"])

    # And can't fetch the bytes by guessing the id.
    resp = await client.get(
        f"/api/competitions/{comp}/tickets/{ticket}/attachments/{attachment['id']}/content",
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_staff_may_delete_a_competitors_attachment(client):
    """Moderation: staff delete any; a competitor only their own."""
    admin, comp = await _competition(client)
    owner = await _participant(client, comp, "owner@example.com")
    ticket, message = await _open_ticket(client, comp, owner)
    attachment = (await _attach(client, comp, ticket, message, owner)).json()

    resp = await client.delete(
        f"/api/competitions/{comp}/tickets/{ticket}/attachments/{attachment['id']}",
        headers=_auth(admin),
    )
    assert resp.status_code == 204


async def test_attachment_events_are_audited(client):
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)
    attachment = (await _attach(client, comp, ticket, message, token)).json()
    await client.delete(
        f"/api/competitions/{comp}/tickets/{ticket}/attachments/{attachment['id']}",
        headers=_auth(token),
    )

    async with SessionLocal() as session:
        events = (
            await session.scalars(
                select(AuditLogEntry.event_name).where(
                    AuditLogEntry.event_name.like("ticket.attachment%")
                )
            )
        ).all()
    assert "ticket.attachment_added" in events
    assert "ticket.attachment_deleted" in events


async def test_competition_delete_cleans_up_ticket_objects(client, object_storage):
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)
    await _attach(client, comp, ticket, message, token)

    async with SessionLocal() as session:
        key = await session.scalar(select(TicketAttachment.object_key))
    assert object_storage.exists(key)

    await client.delete(f"/api/competitions/{comp}", headers=_auth(admin))
    # Rows cascade; the objects must go too rather than orphan in the bucket.
    assert not object_storage.exists(key)


def _png_of(width: int, height: int) -> bytes:
    """A flat-colour PNG — tiny on disk, arbitrarily large when decoded."""
    import struct
    import zlib

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + b"\x00" * (width * 3) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


async def test_decompression_bomb_rejected(client):
    """A 20000x20000 flat PNG is ~1 MB — under the byte cap — but decodes to
    ~1.5 GB in the viewer's browser. Thumbnails render on thread open, so this
    would be a one-click memory bomb aimed at whichever judge picks it up."""
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)

    bomb = _png_of(20000, 20000)
    assert len(bomb) < 2_621_440, "must be under the byte cap to prove anything"
    resp = await _attach(client, comp, ticket, message, token, content=bomb,
                         name="bomb.png")
    assert resp.status_code == 413
    assert "dimensions" in resp.json()["detail"].lower()


async def test_large_but_legitimate_screenshot_accepted(client):
    """The dimension guard must not reject real screenshots — a tall full-page
    capture is legitimately several thousand pixels high."""
    admin, comp = await _competition(client)
    token = await _participant(client, comp, "p@example.com")
    ticket, message = await _open_ticket(client, comp, token)

    tall = _png_of(1920, 6000)  # a long scrolling capture: 11.5 MP
    resp = await _attach(client, comp, ticket, message, token, content=tall,
                         name="page.png")
    assert resp.status_code == 201
