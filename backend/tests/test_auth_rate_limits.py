"""Throttles on the unauthenticated credential endpoints.

Before this, the rate limiter existed but was wired into exactly three call
sites, all of them keyed on an *already authenticated* subject. Login,
registration, password reset and email verification had no throttle and no
lockout of any kind: a breach corpus could be replayed against /login at full
concurrency, and forgot-password would mail any address as often as asked.
"""

from config import settings
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_login_is_throttled_per_identifier(client):
    await admin_token(client)  # ensure the instance is set up

    codes = [
        (
            await client.post(
                "/api/auth/login",
                json={"identifier": "admin@example.com", "password": "wrong"},
            )
        ).status_code
        for _ in range(settings.auth_rate_limit + 2)
    ]
    assert 429 in codes, codes
    # The throttle runs *before* the lookup, so it applies to a wrong password
    # and a nonexistent account alike — no timing difference to probe.
    assert codes[-1] == 429

    # A correct password is refused too while the window holds: the limit is on
    # attempts, not on failures, so an attacker can't reset it by guessing right.
    blocked = await client.post(
        "/api/auth/login",
        json={"identifier": "admin@example.com", "password": "changeme"},
    )
    assert blocked.status_code == 429


async def test_login_throttle_is_case_insensitive(client):
    """The identifier lookup is case-insensitive (§7.7), so the bucket must be
    too — otherwise re-casing hands out a fresh budget every time."""
    await admin_token(client)
    for _ in range(settings.auth_rate_limit + 1):
        await client.post(
            "/api/auth/login",
            json={"identifier": "admin@example.com", "password": "wrong"},
        )
    recased = await client.post(
        "/api/auth/login",
        json={"identifier": "ADMIN@EXAMPLE.COM", "password": "wrong"},
    )
    assert recased.status_code == 429


async def test_one_identifier_does_not_exhaust_anothers_budget(client):
    await admin_token(client)
    for _ in range(settings.auth_rate_limit + 1):
        await client.post(
            "/api/auth/login",
            json={"identifier": "victim@example.com", "password": "wrong"},
        )
    other = await client.post(
        "/api/auth/login",
        json={"identifier": "someone-else@example.com", "password": "wrong"},
    )
    assert other.status_code != 429


async def test_forgot_password_is_throttled_more_tightly(client):
    """It accepts an arbitrary address and mails it, so it's a mail cannon."""
    await admin_token(client)
    codes = [
        (
            await client.post(
                "/api/auth/forgot-password", json={"email": "victim@example.com"}
            )
        ).status_code
        for _ in range(settings.auth_email_rate_limit + 1)
    ]
    assert codes[-1] == 429, codes
    # Tighter than the login limit, since each call costs an outbound email.
    assert settings.auth_email_rate_limit < settings.auth_rate_limit


async def test_registration_is_throttled(client):
    await admin_token(client)
    codes = []
    for i in range(settings.auth_rate_limit + 2):
        resp = await client.post(
            "/api/auth/register",
            json={"display_name": "flood", "password": "password123"},
        )
        codes.append(resp.status_code)
    assert 429 in codes, codes


async def test_token_redemption_endpoints_are_throttled(client):
    await admin_token(client)
    reset = [
        (
            await client.post(
                "/api/auth/reset-password",
                json={"token": "a" * 43, "new_password": "newpassword123"},
            )
        ).status_code
        for _ in range(settings.auth_rate_limit + 2)
    ]
    assert 429 in reset, reset

    verify = [
        (
            await client.post("/api/auth/verify-email", json={"token": "b" * 43})
        ).status_code
        for _ in range(settings.auth_rate_limit + 2)
    ]
    assert 429 in verify, verify


async def test_successful_login_resets_the_identifier_throttle(client, monkeypatch):
    """GHSA-vv68: a successful login clears the identifier's bucket, so an
    attacker filling a known user's login bucket with wrong guesses can't lock
    the real user out — a correct password in any freed slot resets the count.
    Failed attempts still accrue, so brute-force stays throttled."""
    monkeypatch.setattr(settings, "auth_rate_limit", 3)
    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "throttletgt", "email": "tt@example.com", "password": "correct-horse"},
    )
    assert reg.status_code == 201  # register uses its own bucket, not login's

    # Two wrong guesses — the login bucket sits at 2/3.
    for _ in range(2):
        r = await client.post(
            "/api/auth/login", json={"identifier": "tt@example.com", "password": "wrong"}
        )
        assert r.status_code == 401
    # A correct login (the 3rd, still allowed) resets the bucket.
    ok = await client.post(
        "/api/auth/login", json={"identifier": "tt@example.com", "password": "correct-horse"}
    )
    assert ok.status_code == 200
    # Bucket cleared → three more wrong guesses are allowed (401); without the
    # reset the very next attempt would already be 429.
    for _ in range(3):
        r = await client.post(
            "/api/auth/login", json={"identifier": "tt@example.com", "password": "wrong"}
        )
        assert r.status_code == 401, r.text


async def test_login_throttle_ignores_surrounding_whitespace(client):
    """GHSA-vv68: the lookup strips the identifier, so the bucket must too —
    otherwise every padded spelling of a known username is a fresh budget and
    online brute force runs at the hash pool's speed."""
    await admin_token(client)
    for _ in range(settings.auth_rate_limit + 1):
        await client.post(
            "/api/auth/login",
            json={"identifier": "admin@example.com", "password": "wrong"},
        )
    for padded in (" admin@example.com", "admin@example.com\t", "　admin@example.com "):
        resp = await client.post(
            "/api/auth/login", json={"identifier": padded, "password": "changeme"}
        )
        assert resp.status_code == 429, (padded, resp.text)


async def test_padded_success_resets_the_shared_bucket(client):
    """The reset after a successful login clears the same normalised key the
    throttle recorded, whichever spelling got in."""
    await admin_token(client)
    for _ in range(settings.auth_rate_limit - 1):
        await client.post(
            "/api/auth/login",
            json={"identifier": "admin@example.com", "password": "wrong"},
        )
    ok = await client.post(
        "/api/auth/login", json={"identifier": "  Admin@Example.com ", "password": "changeme"}
    )
    assert ok.status_code == 200, ok.text
    # A whole fresh budget: had the reset missed the recorded key, the bucket
    # would still hold the failures above and refuse well before the end.
    for _ in range(settings.auth_rate_limit):
        again = await client.post(
            "/api/auth/login", json={"identifier": "admin@example.com", "password": "wrong"}
        )
        assert again.status_code == 401, again.text


async def test_login_throttle_folds_lookalike_spellings(client):
    """GHSA-vv68: a directory matches identifiers under its own rules (RFC 4518:
    compatibility forms, case folding, formatting characters dropped), so
    fullwidth letters or zero-width characters must not mint fresh budgets."""
    await admin_token(client)
    for _ in range(settings.auth_rate_limit + 1):
        await client.post(
            "/api/auth/login",
            json={"identifier": "admin@example.com", "password": "wrong"},
        )
    for lookalike in (
        "ａｄｍｉｎ@example.com",  # fullwidth
        "ad\u200bmin@example.com",  # zero-width space
        "ad\u00admin@example.com",  # soft hyphen
        "\U0001d41admin@example.com",  # mathematical bold a
    ):
        resp = await client.post(
            "/api/auth/login", json={"identifier": lookalike, "password": "wrong"}
        )
        assert resp.status_code == 429, (lookalike, resp.text)


async def test_password_taking_endpoints_share_one_budget(client):
    """GHSA-vv68: every endpoint that takes the caller's current password draws
    on one per-account budget, so a stolen session gets five guesses in five
    minutes, not five per endpoint."""
    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "stepper", "email": "stepper@example.com", "password": "password123"},
    )
    token = reg.json()["access_token"]
    for _ in range(5):
        wrong = await client.post(
            "/api/auth/change-password",
            json={"current_password": "wrong-guess", "new_password": "another-pass-1"},
            headers=_auth(token),
        )
        assert wrong.status_code != 429, wrong.text
    for path, body in (
        ("/api/auth/change-email", {"current_password": "password123", "new_email": "s2@example.com"}),
        ("/api/auth/change-username", {"current_password": "password123", "new_display_name": "stepper2"}),
        ("/api/api-tokens", {"current_password": "password123", "description": "ci", "expires_in_days": 30}),
    ):
        resp = await client.post(path, json=body, headers=_auth(token))
        assert resp.status_code == 429, (path, resp.text)
