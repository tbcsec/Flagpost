"""AI module Phase 1 — provider plumbing (#98, ADR-0023).

Covers the OpenAI-compatible client against a stubbed httpx transport (parsing,
usage fallback, streaming, the SSRF exemption), the token estimate, the admin
provider-config surface (write-only key, enable invariant, manage_ai gating, the
ai.settings_updated audit event), and the test-connection action (both legs
reported separately).
"""

import json

import httpx
import pytest
from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from tests.conftest import admin_token
import routers.ai_admin as ai_admin
from utils.ai.client import (
    AiProviderError,
    CompletionResult,
    ProviderConfig,
    StreamDone,
    TextChunk,
    ToolCall,
    Usage,
    chat_completion,
    stream_chat_completion,
)
from utils.ai.tokens import estimate_tokens


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# A loopback endpoint on purpose — see the SSRF-exemption test.
CONFIG = ProviderConfig(
    base_url="http://127.0.0.1:11434/v1", model="test-model", api_key=None, timeout_s=5
)


def _mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# --- token helper ------------------------------------------------------------


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("x" * 400) == 100


# --- client: non-streaming ---------------------------------------------------


async def test_chat_completion_parses_content_usage_and_tools():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "hello",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {"name": "foo", "arguments": '{"a":1}'},
                                }
                            ],
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            },
        )

    result = await chat_completion(
        CONFIG, [{"role": "user", "content": "hi"}], transport=_mock(handler)
    )
    assert result.content == "hello"
    assert result.tool_calls == [ToolCall(id="c1", name="foo", arguments='{"a":1}')]
    assert result.usage == Usage(11, 3)
    assert result.finish_reason == "stop"


async def test_chat_completion_usage_falls_back_to_estimate():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "abcd efgh"}}]})

    result = await chat_completion(
        CONFIG, [{"role": "user", "content": "a longer prompt here"}], transport=_mock(handler)
    )
    assert result.usage is not None
    assert result.usage.output_tokens >= 1  # estimated, endpoint reported none
    assert result.usage.input_tokens >= 1


async def test_chat_completion_raises_on_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(AiProviderError):
        await chat_completion(
            CONFIG, [{"role": "user", "content": "x"}], transport=_mock(handler)
        )


async def test_chat_completion_reaches_a_loopback_endpoint():
    """SSRF exemption (ADR-0023 §3): a private/loopback base_url is used as-is.
    If the client ran the URL through the webhook SSRF blocklist, a request to
    127.0.0.1 would never reach the transport."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    await chat_completion(
        CONFIG, [{"role": "user", "content": "x"}], transport=_mock(handler)
    )
    assert seen["host"] == "127.0.0.1"


# --- client: streaming -------------------------------------------------------


def _sse(*chunks: dict) -> bytes:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return body.encode()


async def test_stream_assembles_text_tools_and_usage():
    chunks = [
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "c1", "function": {"name": "foo", "arguments": '{"a":'}}
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        return httpx.Response(
            200, content=_sse(*chunks), headers={"content-type": "text/event-stream"}
        )

    texts: list[str] = []
    done = None
    async for ev in stream_chat_completion(
        CONFIG, [{"role": "user", "content": "hi"}], transport=_mock(handler)
    ):
        if isinstance(ev, TextChunk):
            texts.append(ev.text)
        elif isinstance(ev, StreamDone):
            done = ev.result
    assert "".join(texts) == "Hello"
    assert done is not None
    assert done.content == "Hello"
    assert done.tool_calls == [ToolCall(id="c1", name="foo", arguments='{"a":1}')]
    assert done.usage == Usage(5, 2)
    assert done.finish_reason == "tool_calls"


async def test_stream_parallel_tool_calls_with_indices():
    """Two parallel tool calls split across chunks and disambiguated by index
    must not collide."""
    chunks = [
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "a", "function": {"name": "search", "arguments": '{"q":'}}
        ]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 1, "id": "b", "function": {"name": "weather", "arguments": '{"c":'}}
        ]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"x"}'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 1, "function": {"arguments": '"y"}'}}]}}]},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(*chunks))

    done = None
    async for ev in stream_chat_completion(CONFIG, [{"role": "user", "content": "hi"}], transport=_mock(handler)):
        if isinstance(ev, StreamDone):
            done = ev.result
    assert done.tool_calls == [
        ToolCall(id="a", name="search", arguments='{"q":"x"}'),
        ToolCall(id="b", name="weather", arguments='{"c":"y"}'),
    ]


async def test_stream_parallel_tool_calls_without_indices():
    """A non-compliant endpoint that omits index must still yield two distinct
    tool calls (a delta carrying an id/name opens a new call)."""
    chunks = [
        {"choices": [{"delta": {"tool_calls": [
            {"id": "a", "function": {"name": "search", "arguments": '{"q":"x"}'}}
        ]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"id": "b", "function": {"name": "weather", "arguments": '{"c":"y"}'}}
        ]}}]},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(*chunks))

    done = None
    async for ev in stream_chat_completion(CONFIG, [{"role": "user", "content": "hi"}], transport=_mock(handler)):
        if isinstance(ev, StreamDone):
            done = ev.result
    assert [(t.id, t.name) for t in done.tool_calls] == [("a", "search"), ("b", "weather")]


async def test_malformed_usage_falls_back_to_estimate():
    """A non-numeric usage field must not raise — the caller estimates instead."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": "not-a-number"},
            },
        )

    result = await chat_completion(
        CONFIG, [{"role": "user", "content": "a prompt"}], transport=_mock(handler)
    )
    assert result.usage is not None and result.usage.output_tokens >= 1


async def test_stream_usage_falls_back_when_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse({"choices": [{"delta": {"content": "hi there"}}]}))

    done = None
    async for ev in stream_chat_completion(
        CONFIG, [{"role": "user", "content": "prompt"}], transport=_mock(handler)
    ):
        if isinstance(ev, StreamDone):
            done = ev.result
    assert done is not None and done.usage.output_tokens >= 1


# --- admin settings CRUD -----------------------------------------------------


async def test_settings_defaults_and_write_only_key(client):
    admin = await admin_token(client)
    r = await client.get("/api/admin/ai/settings", headers=_auth(admin))
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is False and data["api_key_set"] is False
    assert data["default_guidance_level"] == "platform_only"
    assert "api_key" not in data

    r = await client.put(
        "/api/admin/ai/settings",
        headers=_auth(admin),
        json={
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "sk-secret",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["base_url"] == "https://api.openai.com/v1"
    assert data["api_key_set"] is True
    # The secret is never serialized back.
    assert "api_key" not in data and "sk-secret" not in json.dumps(data)

    async with SessionLocal() as db:
        ev = await db.scalar(
            select(AuditLogEntry).where(AuditLogEntry.event_name == "ai.settings_updated")
        )
        assert ev is not None


async def test_api_key_omit_preserves_empty_clears(client):
    admin = await admin_token(client)
    await client.put(
        "/api/admin/ai/settings",
        headers=_auth(admin),
        json={"base_url": "https://x/v1", "model": "m", "api_key": "sk-1"},
    )
    # Omitting the field preserves the stored key.
    await client.put("/api/admin/ai/settings", headers=_auth(admin), json={"model": "m2"})
    data = (await client.get("/api/admin/ai/settings", headers=_auth(admin))).json()
    assert data["api_key_set"] is True and data["model"] == "m2"
    # "" clears it (keyless local endpoint).
    await client.put("/api/admin/ai/settings", headers=_auth(admin), json={"api_key": ""})
    data = (await client.get("/api/admin/ai/settings", headers=_auth(admin))).json()
    assert data["api_key_set"] is False


async def test_enable_requires_base_url_and_model(client):
    admin = await admin_token(client)
    r = await client.put("/api/admin/ai/settings", headers=_auth(admin), json={"enabled": True})
    assert r.status_code == 400
    r = await client.put(
        "/api/admin/ai/settings",
        headers=_auth(admin),
        json={"enabled": True, "base_url": "https://x/v1", "model": "m"},
    )
    assert r.status_code == 200 and r.json()["enabled"] is True


async def test_manage_ai_permission_gates_the_surface(client):
    await admin_token(client)  # ensure the instance is set up
    tok = (
        await client.post(
            "/api/auth/register",
            json={
                "email": "nobody@example.com",
                "password": "password123",
                "display_name": "nobody",
            },
        )
    ).json()["access_token"]
    assert (await client.get("/api/admin/ai/settings", headers=_auth(tok))).status_code == 403
    assert (
        await client.put("/api/admin/ai/settings", headers=_auth(tok), json={"model": "m"})
    ).status_code == 403


# --- test-connection (stubbed provider) --------------------------------------


async def _configure(client, admin):
    await client.put(
        "/api/admin/ai/settings",
        headers=_auth(admin),
        json={"base_url": "http://ollama.local/v1", "model": "m"},
    )


async def test_test_connection_both_legs_pass(client, monkeypatch):
    admin = await admin_token(client)
    await _configure(client, admin)

    async def fake(config, messages, *, tools=None, tool_choice=None, max_tokens=None, transport=None):
        if tools:
            return CompletionResult(
                content="", tool_calls=[ToolCall("c1", "report_status", '{"status":"ok"}')]
            )
        return CompletionResult(content="OK")

    monkeypatch.setattr(ai_admin, "chat_completion", fake)
    r = await client.post("/api/admin/ai/test-connection", headers=_auth(admin))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["completion"]["ok"] is True
    assert data["tool_call"]["ok"] is True
    assert data["model"] == "m"


async def test_test_connection_reports_missing_tool_support(client, monkeypatch):
    admin = await admin_token(client)
    await _configure(client, admin)

    async def fake(config, messages, *, tools=None, tool_choice=None, max_tokens=None, transport=None):
        return CompletionResult(content="OK")  # never makes a tool call

    monkeypatch.setattr(ai_admin, "chat_completion", fake)
    data = (await client.post("/api/admin/ai/test-connection", headers=_auth(admin))).json()
    assert data["completion"]["ok"] is True
    assert data["tool_call"]["ok"] is False
    assert "tool" in data["tool_call"]["detail"].lower()


async def test_test_connection_reports_provider_error(client, monkeypatch):
    admin = await admin_token(client)
    await _configure(client, admin)

    async def fake(*a, **k):
        raise AiProviderError("connection refused")

    monkeypatch.setattr(ai_admin, "chat_completion", fake)
    data = (await client.post("/api/admin/ai/test-connection", headers=_auth(admin))).json()
    assert data["completion"]["ok"] is False
    assert "refused" in data["completion"]["detail"]


async def test_test_connection_requires_config(client):
    admin = await admin_token(client)
    r = await client.post("/api/admin/ai/test-connection", headers=_auth(admin))
    assert r.status_code == 400
