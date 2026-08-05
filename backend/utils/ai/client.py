"""OpenAI-compatible chat-completions client (#98, ADR-0023 §1).

One integration surface — ``POST {base_url}/chat/completions`` with its
tool-calling and SSE streaming sub-protocols — covering hosted providers and the
self-hosted set (Ollama, vLLM, LM Studio, LiteLLM). It is deliberately defensive
about the "OpenAI-compatible" spectrum: local endpoints vary in where ``usage``
lands, in tool-call delta shapes, and in whether they stream at all, so parsing
tolerates missing fields and never assumes OpenAI's exact wire format.

**SSRF exemption (ADR-0023 §3).** ``base_url`` is a trusted operator setting in
the same class as the SMTP host and OIDC issuer — set only by an admin holding
``manage_ai``, never from competitor-controlled input — so it is deliberately
**not** run through the ``utils.webhook_security`` blocklist. Pointing it at a
loopback/private address (a local inference server) is the intended self-hosted
deployment, not an attack.

The client is DB-agnostic: it takes a plain :class:`ProviderConfig` and an
optional httpx transport, so it's fully exercisable against ``httpx.MockTransport``
without a live endpoint. The caller (the admin settings router, later the
assistants) builds the config from the ``ai_settings`` row.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from utils.ai.tokens import estimate_tokens

_MAX_ERROR_BODY = 500


class AiProviderError(Exception):
    """The AI endpoint could not be reached or returned an unusable response.

    Carries a message safe to log; the admin surface shows it, competitor-facing
    callers translate it to a generic "assistant unavailable" (spec §10).
    """


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout_s: int = 60


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, as the model emitted it


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class CompletionResult:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None
    finish_reason: str | None = None


@dataclass(frozen=True)
class TextChunk:
    """A streamed content delta."""

    text: str


@dataclass(frozen=True)
class StreamDone:
    """The terminal event of a stream, carrying the assembled result."""

    result: CompletionResult


def config_from_settings(settings) -> ProviderConfig:
    """Build a :class:`ProviderConfig` from an ``AiSettings`` row.

    The caller must have loaded the deferred ``api_key`` first (the column is
    deferred so ordinary settings loads don't decrypt — ADR-0020).
    """
    return ProviderConfig(
        base_url=settings.base_url or "",
        model=settings.model or "",
        api_key=settings.api_key,
        timeout_s=settings.request_timeout_s,
    )


def _endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _payload(
    config: ProviderConfig,
    messages: list[dict],
    *,
    tools: list[dict] | None,
    tool_choice: Any | None,
    max_tokens: int | None,
    stream: bool,
) -> dict:
    body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "stream": stream,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if tools:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    return body


def _truncate(text: str) -> str:
    return text[:_MAX_ERROR_BODY]


def _messages_text(messages: Iterable[dict]) -> str:
    parts = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _parse_usage(raw: Any) -> Usage | None:
    if not isinstance(raw, dict):
        return None
    try:
        return Usage(
            input_tokens=int(raw.get("prompt_tokens") or 0),
            output_tokens=int(raw.get("completion_tokens") or 0),
        )
    except (ValueError, TypeError):
        # A non-numeric usage field from a misbehaving endpoint → treat as
        # "no usage reported" so the caller estimates, rather than raising.
        return None


def _parse_tool_calls(raw: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for tc in raw or []:
        fn = tc.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        calls.append(
            ToolCall(id=tc.get("id") or "", name=name, arguments=fn.get("arguments") or "")
        )
    return calls


def _parse_completion(data: Any) -> CompletionResult:
    if not isinstance(data, dict):
        raise AiProviderError("AI endpoint returned a non-object response")
    choices = data.get("choices") or []
    if not choices:
        raise AiProviderError("AI endpoint returned no choices")
    choice = choices[0] or {}
    message = choice.get("message") or {}
    return CompletionResult(
        content=message.get("content") or "",
        tool_calls=_parse_tool_calls(message.get("tool_calls")),
        usage=_parse_usage(data.get("usage")),
        finish_reason=choice.get("finish_reason"),
    )


def _with_estimated_usage(
    result: CompletionResult, messages: list[dict]
) -> CompletionResult:
    if result.usage is not None:
        return result
    return replace(
        result,
        usage=Usage(
            input_tokens=estimate_tokens(_messages_text(messages)),
            output_tokens=estimate_tokens(result.content),
        ),
    )


async def chat_completion(
    config: ProviderConfig,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    tool_choice: Any | None = None,
    max_tokens: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CompletionResult:
    """One non-streaming completion. Raises :class:`AiProviderError` on any
    transport failure or unusable response. ``usage`` falls back to a local
    estimate when the endpoint doesn't report one."""
    body = _payload(
        config, messages, tools=tools, tool_choice=tool_choice,
        max_tokens=max_tokens, stream=False,
    )
    async with httpx.AsyncClient(timeout=config.timeout_s, transport=transport) as http:
        try:
            resp = await http.post(
                _endpoint(config.base_url), json=body, headers=_headers(config.api_key)
            )
        except httpx.HTTPError as exc:
            raise AiProviderError(f"request to the AI endpoint failed: {exc}") from exc
    if resp.status_code >= 400:
        raise AiProviderError(
            f"AI endpoint returned {resp.status_code}: {_truncate(resp.text)}"
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise AiProviderError("AI endpoint returned a non-JSON response") from exc
    return _with_estimated_usage(_parse_completion(data), messages)


async def stream_chat_completion(
    config: ProviderConfig,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    max_tokens: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[TextChunk | StreamDone]:
    """Stream a completion as SSE, yielding a :class:`TextChunk` per content
    delta and a terminal :class:`StreamDone` with the assembled result (full
    text, any tool calls, usage, finish reason).

    Tolerant of dialect differences: non-``data:`` lines and malformed chunks are
    skipped, ``usage`` is read from whichever chunk carries it (OpenAI puts it on
    a final choices-less chunk when ``stream_options.include_usage`` is set), and
    tool-call deltas are accumulated by index."""
    body = _payload(
        config, messages, tools=tools, tool_choice=None,
        max_tokens=max_tokens, stream=True,
    )
    # Ask for usage on the terminal chunk where supported; endpoints that don't
    # understand it ignore it, and the estimate backstops the rest.
    body["stream_options"] = {"include_usage": True}

    content_parts: list[str] = []
    # Tool-call deltas are accumulated across chunks. The compliant path keys by
    # ``index``; a non-compliant endpoint that omits the index is handled by the
    # protocol convention that the delta *starting* a call carries its ``id`` and
    # function name while continuations carry only ``arguments`` — so an id/name
    # delta opens a new slot and an arguments-only delta extends the current one.
    # This keeps two parallel tool calls from colliding into one when the index
    # is missing (see _open_tool_slot).
    tool_slots: list[dict[str, str]] = []
    index_map: dict[int, dict[str, str]] = {}
    usage: Usage | None = None
    finish_reason: str | None = None

    def _open_tool_slot(tc: dict) -> dict[str, str]:
        raw_index = tc.get("index")
        if raw_index is not None:
            slot = index_map.get(raw_index)
            if slot is None:
                slot = {"id": "", "name": "", "arguments": ""}
                index_map[raw_index] = slot
                tool_slots.append(slot)
            return slot
        starts_new = bool(tc.get("id")) or bool((tc.get("function") or {}).get("name"))
        if starts_new or not tool_slots:
            slot = {"id": "", "name": "", "arguments": ""}
            tool_slots.append(slot)
            return slot
        return tool_slots[-1]

    async with httpx.AsyncClient(timeout=config.timeout_s, transport=transport) as http:
        try:
            async with http.stream(
                "POST", _endpoint(config.base_url), json=body,
                headers=_headers(config.api_key),
            ) as resp:
                if resp.status_code >= 400:
                    raw = await resp.aread()
                    raise AiProviderError(
                        f"AI endpoint returned {resp.status_code}: "
                        f"{_truncate(raw.decode(errors='replace'))}"
                    )
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    if chunk.get("usage"):
                        usage = _parse_usage(chunk["usage"])
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        text = delta.get("content")
                        if text:
                            content_parts.append(text)
                            yield TextChunk(text)
                        for tc in delta.get("tool_calls") or []:
                            slot = _open_tool_slot(tc)
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
        except httpx.HTTPError as exc:
            raise AiProviderError(f"request to the AI endpoint failed: {exc}") from exc

    full = "".join(content_parts)
    tool_calls = [
        ToolCall(id=s["id"], name=s["name"], arguments=s["arguments"])
        for s in tool_slots
        if s["name"]
    ]
    if usage is None:
        usage = Usage(
            input_tokens=estimate_tokens(_messages_text(messages)),
            output_tokens=estimate_tokens(full),
        )
    yield StreamDone(
        CompletionResult(
            content=full, tool_calls=tool_calls, usage=usage, finish_reason=finish_reason
        )
    )
