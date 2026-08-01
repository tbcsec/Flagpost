"""Webhook hardening internals (Tier 3 Phase 2, §5.4, ADR-0013): SSRF URL
validation, header stripping, chat-token defang, and content-type escaping.

SSRF cases use **literal-IP URLs** so no DNS (and no network) is needed — a
literal address goes through the same resolve+check path and is deterministic.
"""

import socket

import pytest

from utils import webhook_security
from utils.webhook_security import (
    WebhookSecurityError,
    defang_chat_tokens,
    escape_for_content_type,
    render_webhook_body,
    sanitize_headers,
    validate_webhook_url,
)


# --- SSRF (§5.4) --------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/hook",          # loopback
        "http://127.0.0.1:8000/hook",     # loopback + port
        "http://169.254.169.254/latest",  # cloud metadata (link-local)
        "http://10.0.0.5/x",              # private A
        "http://192.168.1.10/x",          # private C
        "http://172.16.0.1/x",            # private B
        "http://[::1]/x",                 # IPv6 loopback
        "http://[::ffff:169.254.169.254]/x",  # IPv4-mapped metadata
        "http://0.0.0.0/x",               # unspecified
        # RFC 6598 shared address space. None of is_private / is_loopback /
        # is_link_local / is_reserved / is_multicast covers 100.64.0.0/10, so
        # enumerating them left it reachable — it's the default range for
        # Tailscale, several K8s CNI layouts and ISP CGNAT.
        "http://100.64.0.1/x",
        # ...and on Alibaba Cloud this specific address is the instance
        # metadata service, i.e. the same class of target as 169.254.169.254.
        "http://100.100.100.200/latest/meta-data/",
    ],
)
async def test_ssrf_blocks_non_routable_targets(url):
    with pytest.raises(WebhookSecurityError):
        await validate_webhook_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",       # non-http scheme
        "file:///etc/passwd",        # non-http scheme
        "http:///nohost",            # missing host
    ],
)
async def test_ssrf_rejects_bad_schemes_and_hosts(url):
    with pytest.raises(WebhookSecurityError):
        await validate_webhook_url(url)


@pytest.mark.parametrize("ip", ["1.1.1.1", "8.8.8.8"])
async def test_ssrf_allows_public_addresses(ip, monkeypatch):
    # A public address passes the resolved-IP check. Resolution is stubbed so
    # the suite makes no real getaddrinfo call (which runs in a worker thread
    # and can leak a socket warning) — the block logic itself is what's tested.
    async def _resolves_to(host, port):
        return [ip]

    monkeypatch.setattr(webhook_security, "_resolve_host", _resolves_to)
    await validate_webhook_url(f"https://webhook.example/{ip}")


async def test_ssrf_refuses_unresolvable_host(monkeypatch):
    # A host that can't resolve can't be proven safe → refused. Resolution is
    # stubbed so the test is hermetic (no real DNS / no leaked socket).
    async def _boom(host, port):
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr(webhook_security, "_resolve_host", _boom)
    with pytest.raises(WebhookSecurityError):
        await validate_webhook_url("http://whatever.example/x")


# --- header stripping (§5.4) --------------------------------------------------


def test_sanitize_headers_strips_caller_uncontrollable():
    cleaned = sanitize_headers(
        {
            "X-Token": "keep",
            "Authorization": "Bearer nope",
            "cookie": "session=nope",
            "Host": "internal",
            "X-Forwarded-For": "10.0.0.1",
            "X-Forwarded-Proto": "https",
            "Content-Type": "text/evil",
            "Content-Length": "0",
        }
    )
    assert cleaned == {"X-Token": "keep"}


def test_sanitize_headers_handles_none_and_empty():
    assert sanitize_headers(None) == {}
    assert sanitize_headers({}) == {}


# --- chat-token defang (§5.4) -------------------------------------------------


@pytest.mark.parametrize("token", ["@everyone", "@here", "@channel"])
def test_defang_discord_broadcasts(token):
    out = defang_chat_tokens(f"hi {token} now")
    assert token not in out            # the literal ping token is broken
    assert token[1:] in out            # ...but still human-readable


@pytest.mark.parametrize(
    "token", ["<!channel>", "<!everyone>", "<@U123>", "<#C99>", "<!subteam^S1>"]
)
def test_defang_slack_angle_sequences(token):
    out = defang_chat_tokens(f"ping {token}")
    assert token not in out
    assert "​" in out  # broken with a zero-width space


def test_defang_markdown_links():
    out = defang_chat_tokens("[click](http://evil.example)")
    assert "](" not in out


def test_defang_leaves_ordinary_text_alone():
    assert defang_chat_tokens("team rocket solved web-100") == "team rocket solved web-100"


# --- content-type escaping (§5.4) ---------------------------------------------


def test_json_escaping_prevents_field_breakout():
    escaped = escape_for_content_type('","admin":true', "application/json")
    # Quotes are backslash-escaped, so the value can't become sibling keys.
    assert '\\"' in escaped
    body = '{"text":"' + escaped + '"}'
    import json

    parsed = json.loads(body)  # still valid, single key
    assert list(parsed.keys()) == ["text"]
    assert "admin" not in parsed  # never became a sibling key


def test_form_escaping_percent_encodes():
    escaped = escape_for_content_type("a&b=c d", "application/x-www-form-urlencoded")
    assert "&" not in escaped and "=" not in escaped and " " not in escaped
    assert "%26" in escaped


def test_text_plain_defangs_only():
    escaped = escape_for_content_type("@everyone hi", "text/plain")
    assert "@everyone" not in escaped
    assert "hi" in escaped


def test_render_webhook_body_escapes_substituted_values_only():
    body = render_webhook_body(
        '{"text":"Team {name} scored {pts}"}',
        {"name": '"><script>', "pts": 100},
        "application/json",
    )
    import json

    parsed = json.loads(body)
    assert parsed["text"] == 'Team "><script> scored 100'  # decoded back, intact
    # Unknown placeholders are left verbatim (debuggable).
    body2 = render_webhook_body(
        '{"x":"{missing}"}', {}, "application/json"
    )
    assert "{missing}" in body2
