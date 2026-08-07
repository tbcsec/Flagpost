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
from utils.ai.artifacts import scrub_leaked_tool_calls, strip_tool_call_artifacts
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


def test_strip_leading_tool_call_artifact():
    # The observed llama3.1/Ollama shape: a bare `{}` ahead of the real answer.
    assert strip_tool_call_artifacts("{}\nHere's the answer") == "Here's the answer"
    assert strip_tool_call_artifacts("  { }\n\nHi") == "Hi"
    assert strip_tool_call_artifacts("[]\nHi") == "Hi"
    assert strip_tool_call_artifacts("{}{}\nHi") == "Hi"  # a run folds to one strip
    # A legitimate empty object mid-answer, or not at the very start, is untouched.
    assert strip_tool_call_artifacts("An empty object is {} in JSON") == (
        "An empty object is {} in JSON"
    )
    assert strip_tool_call_artifacts("Sure {} here") == "Sure {} here"
    # Non-empty braces (a code snippet) are never the artifact.
    assert strip_tool_call_artifacts("{a: 1}\nHi") == "{a: 1}\nHi"
    # Degenerate: artifact-only content is kept, not blanked.
    assert strip_tool_call_artifacts("{}") == "{}"
    assert strip_tool_call_artifacts("") == ""


def test_scrub_leaked_tool_calls():
    # The observed llama3.1 shape: a good answer, then a whole tool call emitted
    # as prose. The JSON block is dropped; the raw call never renders.
    leaked = (
        "XSS is a web vulnerability.\n\n"
        "Here is the JSON for the function call: "
        '{"name": "get_announcements", "parameters": {}}'
    )
    assert scrub_leaked_tool_calls(leaked) == "XSS is a web vulnerability."
    # A HALLUCINATED (non-catalogue) tool name is NOT masked — a genuinely broken
    # call stays visible as the failure it is, rather than being hidden.
    hallucinated = 'Check: {"name": "get_top_n_standings", "parameters": {"n": 5}}'
    assert scrub_leaked_tool_calls(hallucinated) == hallucinated
    # Legitimate prose is untouched: the gate is the tool name as a quoted VALUE of
    # a name/function key, so discussing JSON, empty braces, a non-tool "name"
    # value, or a flag shape all pass through unchanged.
    assert scrub_leaked_tool_calls("An empty object is {} in JSON.") == (
        "An empty object is {} in JSON."
    )
    assert scrub_leaked_tool_calls('Config: {"name": "get_started"}') == (
        'Config: {"name": "get_started"}'
    )
    assert scrub_leaked_tool_calls("Flags look like flag{abc_123}.") == (
        "Flags look like flag{abc_123}."
    )
    # A message that is nothing but a leaked call becomes an honest placeholder,
    # never raw JSON or a blank bubble.
    assert scrub_leaked_tool_calls(
        '{"name": "get_scoreboard", "parameters": {}}'
    ).startswith("Sorry")
    assert scrub_leaked_tool_calls("") == ""
    assert scrub_leaked_tool_calls(scrub_leaked_tool_calls(leaked)) == (
        scrub_leaked_tool_calls(leaked)
    )


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


async def test_competitor_tool_fails_closed_on_bad_args(client):
    """A non-scalar tool argument must degrade to a tool error, never raise a 500
    out of the loop (the reported get_challenge({"challenge_id": {...}}) path)."""
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _publish_challenge(client, comp, admin)
    _t, uid = await _participant(client, comp, "badargcp@example.com")
    user = await _user(uid)
    competition = await _competition_obj(comp)
    async with SessionLocal() as db:
        out = await execute_competitor_tool(
            db, user, competition, "get_challenge", {"challenge_id": {"x": 1}},
            challenge_metadata_access=True,
        )
    assert "error" in out and "has_flag" not in out


async def test_competitor_tool_backstop_catches_handler_error(client, monkeypatch):
    """Any handler exception (not just ToolError) is caught and returned as a
    tool error — the loop stays fail-closed as documented."""
    from utils.ai import competitor_tools as ct

    async def boom(db, user, competition, args):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(
        ct._TOOLS,
        "get_scoreboard",
        ct.Tool("get_scoreboard", "d", {"type": "object", "properties": {}}, boom),
    )
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    _t, uid = await _participant(client, comp, "backstopcp@example.com")
    user = await _user(uid)
    competition = await _competition_obj(comp)
    async with SessionLocal() as db:
        out = await execute_competitor_tool(
            db, user, competition, "get_scoreboard", {},
            challenge_metadata_access=False,
        )
    assert "error" in out  # caught + rolled back, not raised


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


async def test_competitor_turn_strips_leaked_tool_call(client, monkeypatch):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _enable_ai(client, admin)
    await _enable_competitor(client, comp, admin)
    p_token, _ = await _participant(client, comp, "leakcp@example.com")
    await _accept_disclosure(client, comp, p_token)

    # The model answers well, then leaks a whole tool call as prose (llama3.1
    # shape). The buffered post-process must drop the JSON block before delivery.
    _script(monkeypatch, [CompletionResult(content=(
        "XSS injects scripts into browsers.\n\n"
        "Here is the JSON for the function call: "
        '{"name": "get_announcements", "parameters": {}}'
    ))])
    conv = (
        await client.post(
            f"/api/competitions/{comp}/ai/conversations",
            json={"assistant_type": "competitor"},
            headers=_auth(p_token),
        )
    ).json()["id"]
    r = await client.post(
        f"/api/competitions/{comp}/ai/conversations/{conv}/messages",
        json={"content": "tell me about xss"},
        headers=_auth(p_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()["content"]
    assert body == "XSS injects scripts into browsers."
    assert "get_announcements" not in body and "{" not in body


async def test_competitor_turn_strips_leading_tool_artifact(client, monkeypatch):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _enable_ai(client, admin)
    await _enable_competitor(client, comp, admin)
    p_token, _ = await _participant(client, comp, "artifactcp@example.com")
    await _accept_disclosure(client, comp, p_token)

    # The model leaks a bare `{}` ahead of its prose (llama3.1/Ollama quirk); the
    # buffered competitor post-process drops it before the answer is delivered.
    _script(monkeypatch, [CompletionResult(content="{}\nHere's a platform tip!")])

    conv = (
        await client.post(
            f"/api/competitions/{comp}/ai/conversations",
            json={"assistant_type": "competitor"},
            headers=_auth(p_token),
        )
    ).json()["id"]
    r = await client.post(
        f"/api/competitions/{comp}/ai/conversations/{conv}/messages",
        json={"content": "how do I submit a flag?"},
        headers=_auth(p_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "Here's a platform tip!"

    async with SessionLocal() as db:
        stored = (
            await db.execute(
                AiMessage.__table__.select().where(
                    AiMessage.conversation_id == conv, AiMessage.role == "assistant"
                )
            )
        ).first()
    assert stored.content == "Here's a platform tip!"


# --- transcript review -------------------------------------------------------


async def test_transcript_excludes_empty_and_orders_by_activity(client, monkeypatch):
    """The review list omits opened-but-never-used (empty) threads and is ordered
    by last activity — so a resumed thread reads as one entry with a live 'last
    seen', not a pile of empty sessions."""
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _enable_ai(client, admin)
    await _enable_competitor(client, comp, admin)
    reviewer, _ = await _user_with_permissions(
        client, comp, "rev2@example.com", ["ai_view_transcripts"]
    )

    # Participant A opens the assistant but never sends a message → empty thread.
    a_token, _ = await _participant(client, comp, "emptya@example.com")
    await _accept_disclosure(client, comp, a_token)
    await client.post(
        f"/api/competitions/{comp}/ai/conversations",
        json={"assistant_type": "competitor"}, headers=_auth(a_token),
    )

    # Participant B actually chats → a real thread.
    _script(monkeypatch, [CompletionResult(content="Hi B!")])
    b_token, _ = await _participant(client, comp, "sendb@example.com")
    await _accept_disclosure(client, comp, b_token)
    conv_b = (
        await client.post(
            f"/api/competitions/{comp}/ai/conversations",
            json={"assistant_type": "competitor"}, headers=_auth(b_token),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/ai/conversations/{conv_b}/messages",
        json={"content": "hi"}, headers=_auth(b_token),
    )

    listing = (
        await client.get(f"/api/competitions/{comp}/ai/transcripts", headers=_auth(reviewer))
    ).json()
    # Only B's thread appears; A's empty one is filtered out.
    assert [t["id"] for t in listing] == [conv_b]
    assert all(t["message_count"] > 0 for t in listing)
    assert "last_activity_at" in listing[0]


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
