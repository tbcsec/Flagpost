"""Competitor assistant — Phase 3 (#98, ADR-0023 §3/§5).

The load-bearing properties: the competitor tools cannot surface a flag
(structural, via ChallengeOut), the challenge tools exist only when the hard
challenge-metadata toggle is on, the assistant is offered only while the
competition is running (active-only, owner decision), the guidance level is
resolved with inheritance and shapes the prompt only, the output flag-scan
redacts flag shapes, and transcript review is gated on ai_view_transcripts. The
model is stubbed so the loop and tools run for real without a live endpoint.
"""

from datetime import timedelta

from db import SessionLocal, utcnow
from models.ai import AiMessage
from models.competition import Competition
from tests.conftest import admin_token
from tests.test_ai_assistant import (
    _auth,
    _competition,
    _enable_ai,
    _participant,
    _script,
    _user,
    _user_with_permissions,
)
from utils.ai.client import CompletionResult
from utils.ai.competitor_tools import (
    competitor_tool_schemas,
    execute_competitor_tool,
)
from utils.ai.flag_scan import contains_flag_shape, redact_flags
from utils.ai.guidance import (
    guidance_fragment,
    normalize_level,
    resolve_guidance_level,
)


# --- pure units --------------------------------------------------------------


def test_flag_scan_redacts_flag_shapes():
    assert redact_flags("the answer is flag{s3cr3t_here}!") == "the answer is [redacted]!"
    assert redact_flags("try picoCTF{abc-123}") == "try [redacted]"
    assert "[redacted]" in redact_flags("FLAG{x} and CTF{y}")
    # Ordinary prose/code with a space before the brace, or multi-line, is left.
    assert redact_flags("if (x) { return y }") == "if (x) { return y }"
    assert redact_flags("") == ""
    assert not contains_flag_shape("no flags here { spaced }")


def test_guidance_resolution_and_inheritance():
    # Override wins; else site default; else the safe default; garbage → safe.
    assert resolve_guidance_level("guided", "conceptual") == "guided"
    assert resolve_guidance_level(None, "conceptual") == "conceptual"
    assert resolve_guidance_level(None, None) == "platform_only"
    assert normalize_level("nonsense") == "platform_only"
    for level in ("platform_only", "conceptual", "guided"):
        assert guidance_fragment(level)


def test_metadata_toggle_controls_challenge_tools():
    with_meta = {t["function"]["name"] for t in competitor_tool_schemas(challenge_metadata_access=True)}
    without = {t["function"]["name"] for t in competitor_tool_schemas(challenge_metadata_access=False)}
    assert {"list_challenges", "get_challenge"} <= with_meta
    assert not ({"list_challenges", "get_challenge"} & without)
    # The non-challenge tools are always offered.
    assert {"get_scoreboard", "get_my_standing", "get_announcements"} <= without


# --- helpers -----------------------------------------------------------------


async def _publish_challenge(client, comp, admin, *, title="Crypto 1", flag="flag{real_secret}"):
    r = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": title, "flag": flag, "flag_type": "static", "points": 100},
        headers=_auth(admin),
    )
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/publish", headers=_auth(admin)
    )
    return cid


async def _enable_competitor(client, comp, admin, *, guidance=None, metadata=False):
    body = {"competitor_enabled": True, "challenge_metadata_access": metadata}
    if guidance is not None:
        body["guidance_level"] = guidance
    r = await client.put(
        f"/api/competitions/{comp}/ai/settings", json=body, headers=_auth(admin)
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _accept_disclosure(client, comp, token):
    r = await client.post(
        f"/api/competitions/{comp}/ai/disclosure/accept", headers=_auth(token)
    )
    assert r.status_code == 204, r.text


async def _competition_obj(comp_id) -> Competition:
    async with SessionLocal() as db:
        return await db.get(Competition, comp_id)


# --- per-competition settings ------------------------------------------------


async def test_settings_gated_on_edit_and_roundtrip(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    p_token, _ = await _participant(client, comp, "settingsp@example.com")

    # A participant can't read or change them (needs edit_competition).
    assert (await client.get(f"/api/competitions/{comp}/ai/settings", headers=_auth(p_token))).status_code == 403
    assert (
        await client.put(
            f"/api/competitions/{comp}/ai/settings",
            json={"competitor_enabled": True},
            headers=_auth(p_token),
        )
    ).status_code == 403

    out = await _enable_competitor(client, comp, admin, guidance="conceptual", metadata=True)
    assert out["competitor_enabled"] is True
    assert out["guidance_level"] == "conceptual"
    assert out["effective_guidance_level"] == "conceptual"
    assert out["challenge_metadata_access"] is True


async def test_guidance_level_inherits_site_default(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    # Site default is platform_only; enabling without an override inherits it.
    out = await _enable_competitor(client, comp, admin)
    assert out["guidance_level"] is None
    assert out["effective_guidance_level"] == "platform_only"


# --- availability + gating (active-only) -------------------------------------


async def test_availability_competitor_needs_active_enabled_participant(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _enable_ai(client, admin)
    p_token, _ = await _participant(client, comp, "availcp@example.com")

    # Enabled site-wide but the per-competition toggle is off → competitor False.
    r = await client.get(f"/api/competitions/{comp}/ai/availability", headers=_auth(p_token))
    assert r.json()["admin"] is False and r.json()["competitor"] is False

    await _enable_competitor(client, comp, admin)
    r = await client.get(f"/api/competitions/{comp}/ai/availability", headers=_auth(p_token))
    assert r.json()["competitor"] is True
    # The disclosure hasn't been accepted yet — the bit drives the first-run modal.
    assert r.json()["competitor_disclosure_accepted"] is False
    await _accept_disclosure(client, comp, p_token)
    r = await client.get(f"/api/competitions/{comp}/ai/availability", headers=_auth(p_token))
    assert r.json()["competitor_disclosure_accepted"] is True

    # A non-participant (no challenge_view) doesn't get the competitor assistant.
    outsider, _ = await _user_with_permissions(
        client, comp, "outsider@example.com", ["ticket_view"]
    )
    r = await client.get(f"/api/competitions/{comp}/ai/availability", headers=_auth(outsider))
    assert r.json()["competitor"] is False


async def test_competitor_conversation_requires_enabled_and_active(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _enable_ai(client, admin)
    p_token, _ = await _participant(client, comp, "convcp@example.com")

    body = {"assistant_type": "competitor"}
    # Disabled per-competition → 403.
    r = await client.post(f"/api/competitions/{comp}/ai/conversations", json=body, headers=_auth(p_token))
    assert r.status_code == 403

    await _enable_competitor(client, comp, admin)
    # Enabled, but the first-run disclosure hasn't been accepted → refused
    # server-side (the recorded acceptance is a gate, not a UI courtesy).
    r = await client.post(f"/api/competitions/{comp}/ai/conversations", json=body, headers=_auth(p_token))
    assert r.status_code == 409
    await _accept_disclosure(client, comp, p_token)
    r = await client.post(f"/api/competitions/{comp}/ai/conversations", json=body, headers=_auth(p_token))
    assert r.status_code == 201
    assert r.json()["assistant_type"] == "competitor"

    # End the competition → active-only gate refuses (409).
    past = (utcnow() - timedelta(hours=1)).isoformat()
    await client.patch(f"/api/competitions/{comp}", json={"end_at": past}, headers=_auth(admin))
    r = await client.post(f"/api/competitions/{comp}/ai/conversations", json=body, headers=_auth(p_token))
    assert r.status_code == 409


# --- execution-as-caller + structural flag exclusion -------------------------


async def test_get_challenge_tool_never_returns_a_flag(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    cid = await _publish_challenge(client, comp, admin, flag="flag{do_not_leak}")
    _t, uid = await _participant(client, comp, "toolcp@example.com")
    user = await _user(uid)
    competition = await _competition_obj(comp)

    async with SessionLocal() as db:
        data = await execute_competitor_tool(
            db, user, competition, "get_challenge", {"challenge_id": cid},
            challenge_metadata_access=True,
        )
    assert "error" not in data
    # The only flag-related fact is has_flag; no plaintext/hash/salt/regex.
    for banned in ("flag", "flag_hash", "flag_salt", "flag_regex"):
        assert banned not in data
    assert data["has_flag"] is True
    assert "do_not_leak" not in str(data)


async def test_challenge_tools_refuse_when_metadata_off(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    cid = await _publish_challenge(client, comp, admin)
    _t, uid = await _participant(client, comp, "metacp@example.com")
    user = await _user(uid)
    competition = await _competition_obj(comp)

    async with SessionLocal() as db:
        # Even if the model names the tool, the toggle-off path refuses (belt to
        # the schema's braces) — no challenge data comes back.
        listing = await execute_competitor_tool(
            db, user, competition, "list_challenges", {},
            challenge_metadata_access=False,
        )
        detail = await execute_competitor_tool(
            db, user, competition, "get_challenge", {"challenge_id": cid},
            challenge_metadata_access=False,
        )
    assert "error" in listing and "challenges" not in listing
    assert "error" in detail and "has_flag" not in detail


# --- turn: flag scan + persistence + event -----------------------------------


async def test_competitor_turn_redacts_and_emits(client, monkeypatch):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _enable_ai(client, admin)
    await _enable_competitor(client, comp, admin, guidance="guided", metadata=True)
    p_token, _ = await _participant(client, comp, "turncp@example.com")
    await _accept_disclosure(client, comp, p_token)

    # The model tries to leak a flag in its answer; the scan must redact it.
    _script(monkeypatch, [CompletionResult(content="Sure! The flag is flag{leaked_via_model}. Good luck!")])

    conv = (
        await client.post(
            f"/api/competitions/{comp}/ai/conversations",
            json={"assistant_type": "competitor"},
            headers=_auth(p_token),
        )
    ).json()["id"]
    r = await client.post(
        f"/api/competitions/{comp}/ai/conversations/{conv}/messages",
        json={"content": "what's the flag for crypto 1?"},
        headers=_auth(p_token),
    )
    assert r.status_code == 200, r.text
    assert "leaked_via_model" not in r.json()["content"]
    assert "[redacted]" in r.json()["content"]

    async with SessionLocal() as db:
        stored = (
            await db.execute(
                AiMessage.__table__.select().where(
                    AiMessage.conversation_id == conv, AiMessage.role == "assistant"
                )
            )
        ).first()
    assert "leaked_via_model" not in stored.content


# --- transcript review -------------------------------------------------------


async def test_transcript_review_gated_on_permission(client, monkeypatch):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _enable_ai(client, admin)
    await _enable_competitor(client, comp, admin)
    p_token, uid = await _participant(client, comp, "transcp@example.com")
    await _accept_disclosure(client, comp, p_token)

    _script(monkeypatch, [CompletionResult(content="Good luck out there!")])
    conv = (
        await client.post(
            f"/api/competitions/{comp}/ai/conversations",
            json={"assistant_type": "competitor"},
            headers=_auth(p_token),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/ai/conversations/{conv}/messages",
        json={"content": "any tips?"},
        headers=_auth(p_token),
    )

    # A reviewer with ai_view_transcripts sees the conversation and its messages.
    reviewer, _ = await _user_with_permissions(
        client, comp, "reviewer@example.com", ["ai_view_transcripts"]
    )
    listing = await client.get(f"/api/competitions/{comp}/ai/transcripts", headers=_auth(reviewer))
    assert listing.status_code == 200
    summaries = listing.json()
    assert any(s["id"] == conv and s["message_count"] >= 2 for s in summaries)
    detail = await client.get(
        f"/api/competitions/{comp}/ai/transcripts/{conv}", headers=_auth(reviewer)
    )
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) >= 2

    # The competitor themselves lacks the oversight grant → 403.
    denied = await client.get(f"/api/competitions/{comp}/ai/transcripts", headers=_auth(p_token))
    assert denied.status_code == 403
