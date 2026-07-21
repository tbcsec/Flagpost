"""Timestamps serialize as timezone-aware UTC (pre-Tier-2 fix).

SQLite drops tzinfo on read, which used to make ``created_at`` serialize without
an offset — a browser then read it as local time. The UtcDateTime type coerces
on load so every timestamp leaves the API as aware UTC, offset included.
"""

from datetime import datetime

from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_created_at_is_offset_aware(client):
    admin = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={"name": "CTF", "participation_mode": "team"},
        headers=_auth(admin),
    )
    created_at = resp.json()["created_at"]
    # Parseable as an aware datetime (has a tz offset), not a bare local string.
    parsed = datetime.fromisoformat(created_at)
    assert parsed.tzinfo is not None
