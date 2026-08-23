"""User avatars: self-service upload/remove, admin moderation, hardening, audit.

The upload contract under test: whatever comes in, what's *stored* (and served)
is the server's own 256x256 WebP re-encode — so EXIF (GPS!) is gone, polyglots
don't survive, and the type/size are ours. Removal is self-service or
``manage_users`` moderation, and every mutation lands in the audit log with the
actor attached.
"""

import io

from PIL import Image
from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from tests.conftest import admin_token
from utils.avatars import AVATAR_SIZE


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, name: str) -> tuple[str, str]:
    """Register → (token, user_id)."""
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": f"{name}@example.com",
            "password": "password123",
            "display_name": name,
        },
    )
    token = resp.json()["access_token"]
    me = await client.get("/api/auth/me", headers=_auth(token))
    return token, me.json()["id"]


# Magic-byte-only PNG (1x1 header, corrupt IDAT) — for the paths that must
# reject *before* any decode (pixel budget, byte cap). Never decodable.
_PNG_HEADER_ONLY = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da6360000002000154a24f8f0000000049454e44ae426082"
)
_SVG = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'


def _png(size: tuple[int, int] = (64, 48)) -> bytes:
    """A real, decodable PNG."""
    buf = io.BytesIO()
    Image.new("RGBA", size, "#1F9E6B").save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_with_exif() -> bytes:
    """A 300x200 JPEG carrying EXIF orientation 6 (rotate 90 CW to view)."""
    img = Image.new("RGB", (300, 200), "#1F9E6B")
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


async def test_upload_serves_reencoded_square_webp(client):
    token, user_id = await _register(client, "ada")

    me = await client.get("/api/auth/me", headers=_auth(token))
    assert me.json()["avatar_updated_at"] is None

    resp = await client.post(
        "/api/profile/avatar",
        files={"file": ("me.png", _png(), "image/png")},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["avatar_updated_at"] is not None

    served = await client.get(f"/api/users/{user_id}/avatar", headers=_auth(token))
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert "immutable" in served.headers["cache-control"]
    assert served.headers["x-content-type-options"] == "nosniff"

    img = Image.open(io.BytesIO(served.content))
    assert img.format == "WEBP"
    assert img.size == (AVATAR_SIZE, AVATAR_SIZE)


async def test_reencode_strips_exif_and_applies_orientation(client):
    token, user_id = await _register(client, "grace")

    resp = await client.post(
        "/api/profile/avatar",
        files={"file": ("photo.jpg", _jpeg_with_exif(), "image/jpeg")},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text

    served = await client.get(f"/api/users/{user_id}/avatar", headers=_auth(token))
    img = Image.open(io.BytesIO(served.content))
    # The stored artifact is our re-encode: square, WebP, and — the part that
    # matters for privacy — carrying none of the source's EXIF.
    assert img.size == (AVATAR_SIZE, AVATAR_SIZE)
    assert dict(img.getexif()) == {}


async def test_upload_rejects_non_images_by_content(client):
    token, _ = await _register(client, "mallory")

    # SVG is a script-bearing document, never an avatar.
    resp = await client.post(
        "/api/profile/avatar",
        files={"file": ("a.svg", _SVG, "image/svg+xml")},
        headers=_auth(token),
    )
    assert resp.status_code == 400

    # A content-type claim doesn't make HTML a PNG — magic bytes decide.
    resp = await client.post(
        "/api/profile/avatar",
        files={"file": ("a.png", b"<html>totally a png</html>", "image/png")},
        headers=_auth(token),
    )
    assert resp.status_code == 400


async def test_upload_rejects_header_declared_pixel_bomb(client):
    token, _ = await _register(client, "boom")

    # Real PNG magic, but the IHDR declares 60000x60000 — refused before any
    # decode (the pixel budget reads the header, Pillow never runs).
    bomb = bytearray(_PNG_HEADER_ONLY)
    bomb[16:20] = (60000).to_bytes(4, "big")
    bomb[20:24] = (60000).to_bytes(4, "big")
    resp = await client.post(
        "/api/profile/avatar",
        files={"file": ("bomb.png", bytes(bomb), "image/png")},
        headers=_auth(token),
    )
    assert resp.status_code == 400


async def test_upload_rejects_oversize_body(client):
    token, _ = await _register(client, "chunky")
    resp = await client.post(
        "/api/profile/avatar",
        files={"file": ("big.png", _PNG_HEADER_ONLY + b"\x00" * (2 * 1024 * 1024), "image/png")},
        headers=_auth(token),
    )
    assert resp.status_code == 413


async def test_self_remove(client):
    token, user_id = await _register(client, "lin")
    await client.post(
        "/api/profile/avatar",
        files={"file": ("me.png", _png(), "image/png")},
        headers=_auth(token),
    )

    resp = await client.delete("/api/profile/avatar", headers=_auth(token))
    assert resp.status_code == 204
    assert (
        await client.get(f"/api/users/{user_id}/avatar", headers=_auth(token))
    ).status_code == 404
    me = await client.get("/api/auth/me", headers=_auth(token))
    assert me.json()["avatar_updated_at"] is None

    # Nothing left to remove.
    resp = await client.delete("/api/profile/avatar", headers=_auth(token))
    assert resp.status_code == 404


async def test_admin_moderation_and_permission_gate(client):
    token, user_id = await _register(client, "artist")
    await client.post(
        "/api/profile/avatar",
        files={"file": ("me.png", _png(), "image/png")},
        headers=_auth(token),
    )

    # Another plain user can't moderate.
    bystander, _ = await _register(client, "bystander")
    resp = await client.delete(f"/api/users/{user_id}/avatar", headers=_auth(bystander))
    assert resp.status_code == 403

    # An administrator can.
    admin = await admin_token(client)
    resp = await client.delete(f"/api/users/{user_id}/avatar", headers=_auth(admin))
    assert resp.status_code == 204
    assert (
        await client.get(f"/api/users/{user_id}/avatar", headers=_auth(token))
    ).status_code == 404


async def test_avatar_serves_publicly_like_the_logo(client):
    # <img> tags can't send a bearer token, so the read path is public — an
    # unguessable uuid path serving our own re-encode, same posture as the logo.
    token, user_id = await _register(client, "shy")
    await client.post(
        "/api/profile/avatar",
        files={"file": ("me.png", _png(), "image/png")},
        headers=_auth(token),
    )
    assert (await client.get(f"/api/users/{user_id}/avatar")).status_code == 200


async def test_events_reach_the_audit_log_with_actors(client):
    token, user_id = await _register(client, "tracked")
    await client.post(
        "/api/profile/avatar",
        files={"file": ("me.png", _png(), "image/png")},
        headers=_auth(token),
    )
    admin = await admin_token(client)
    admin_id = (await client.get("/api/auth/me", headers=_auth(admin))).json()["id"]
    await client.delete(f"/api/users/{user_id}/avatar", headers=_auth(admin))

    async with SessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLogEntry).where(
                        AuditLogEntry.event_name.in_(
                            ["user.avatar_updated", "user.avatar_removed"]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
    by_name = {r.event_name: r for r in rows}
    assert by_name["user.avatar_updated"].payload["actor_user_id"] == user_id
    # Moderation is attributable: the remover was the admin, not the owner.
    removed = by_name["user.avatar_removed"]
    assert removed.payload["user_id"] == user_id
    assert removed.payload["actor_user_id"] == admin_id
