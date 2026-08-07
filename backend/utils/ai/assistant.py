"""Assistant orchestration (#98, ADR-0023) — the admin and competitor turns.

Both assistants share one bounded tool loop (:func:`_drive_turn`): assemble the
prompt, stream the model, resolve any tool calls **as the requesting user**, feed
the results back, and finish the answer. The loop is capped so a model that keeps
calling tools can't spin forever, and every exchange is read-only.

The two differ only in what :func:`_drive_turn` is handed:

- **Admin** — the admin tool catalogue, the admin output cap, and *live*
  streaming (chunks go to the client as they arrive; it executes as the organiser
  so there's nothing to scrub).
- **Competitor** — the competitor tool catalogue (gated by the challenge-metadata
  toggle), the lower competitor cap, a guidance-level prompt fragment, and
  **buffered** delivery: the answer is assembled, run through the flag-format
  redactor (spec §5 layer 3), then delivered — so a competitor never sees a
  token-streamed flag shape ahead of the scan. Per the ADR axiom none of the
  safety properties live in the prompt; the tools and the redactor are the guard.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from models.ai import AiCompetitionSettings, AiSettings
from models.competition import Competition
from models.user import User
from utils.ai.client import (
    AiProviderError,
    StreamDone,
    TextChunk,
    config_from_settings,
    stream_chat_completion,
)
from utils.ai.artifacts import scrub_leaked_tool_calls, strip_tool_call_artifacts
from utils.ai.competitor_tools import competitor_tool_schemas, execute_competitor_tool
from utils.ai.flag_scan import redact_flags
from utils.ai.guidance import guidance_fragment, resolve_guidance_level
from utils.ai.tools import admin_tool_schemas, execute_admin_tool

# A model that keeps calling tools without answering is capped here; the final
# round after this many still gets to produce text.
MAX_TOOL_ROUNDS = 6

DEFAULT_ADMIN_PROMPT = (
    "You are the Flagpost administrator assistant, helping an organiser run a "
    "Capture-the-Flag competition. Answer their operational questions using the "
    "read-only tools available to you — competition status, scoreboard, "
    "per-challenge stats, support tickets, survey feedback, and announcements.\n\n"
    "Call a tool whenever a question needs live data; don't guess at numbers. If "
    "a tool reports that you lack a permission or that a module is disabled, tell "
    "the organiser plainly instead of inventing an answer. Be concise and "
    "factual. You are strictly read-only — you cannot change anything, start or "
    "stop anything, or message anyone."
)

DEFAULT_COMPETITOR_PROMPT = (
    "You are the Flagpost competitor assistant, helping a participant during a "
    "Capture-the-Flag competition. Use the read-only tools to ground your answers "
    "in real data — the scoreboard, the competitor's own standing, the "
    "organisers' announcements (operational notices about the competition), and "
    "(when available) public challenge details.\n\n"
    "Be encouraging and concise. You must never reveal, guess, or confirm a flag "
    "or a correct multiple-choice answer, and you cannot change anything. Follow "
    "the guidance level above for how much help with solving you may give."
)


def _preamble(competition_name: str, now: datetime) -> str:
    return (
        f'You are assisting a competition organiser with the competition '
        f'"{competition_name}". The current server time is {now.isoformat()}. '
        f"Your access is read-only and scoped to this competition. Never mention, "
        f"name, or quote the internal tools or functions you use to fetch data; "
        f"describe what you are doing in plain language."
    )


def _competitor_preamble(competition_name: str, now: datetime) -> str:
    return (
        f'You are assisting a competitor in the competition "{competition_name}". '
        f"The current server time is {now.isoformat()}. Your access is read-only "
        f"and scoped to this competition, and you must never reveal a flag or a "
        f"correct answer — you do not have access to them and must not guess them. "
        f"Looking things up is silent and invisible to the competitor: never "
        f"announce, offer, or narrate an intent to look something up or call a "
        f"function (nothing like: I can check the announcements, let me look that "
        f"up, or here is the function call). Never write a tool or function name, "
        f"and never write JSON, a function call, or any tool-invocation syntax in "
        f"your reply. Either answer directly, or fetch what you need behind the "
        f"scenes and answer only from the result — as if you simply knew it."
    )


@dataclass
class AssistantOutcome:
    """The durable result of one turn — what to persist and put in the usage
    counter / ``ai.query`` event. For the admin assistant the streamed text was
    already delivered chunk-by-chunk; for the competitor assistant the (redacted)
    ``content`` was delivered in one shot. Either way ``content`` is what to
    store, and it matches what the client saw."""

    content: str
    tools_used: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


def _assistant_tool_call_message(result) -> dict:
    return {
        "role": "assistant",
        "content": result.content or None,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in result.tool_calls
        ],
    }


def _parse_args(raw: str) -> dict:
    try:
        args = json.loads(raw or "{}")
    except ValueError:
        return {}
    return args if isinstance(args, dict) else {}


def build_messages(
    settings: AiSettings,
    competition: Competition,
    history: list[dict],
    user_message: str,
    *,
    now: datetime,
) -> list[dict]:
    """The admin assistant's message list (kept as a named helper for tests)."""
    system = _preamble(competition.name, now) + "\n\n" + (
        settings.admin_prompt_override or DEFAULT_ADMIN_PROMPT
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    return messages


async def _drive_turn(
    config,
    messages: list[dict],
    *,
    tools: list[dict],
    max_tokens: int,
    execute_tool: Callable[[str, dict], Awaitable[dict]],
    on_text: Callable[[str], Awaitable[None]],
    stream_live: bool,
    post_process: Callable[[str], str] | None = None,
) -> AssistantOutcome:
    """The shared bounded tool loop. ``stream_live`` forwards each content chunk
    to ``on_text`` as it arrives (admin); otherwise the answer is buffered,
    ``post_process``-ed (the competitor flag scan), and delivered once at the
    end. Provider failures propagate as ``AiProviderError`` for the caller."""
    tools_used: list[str] = []
    input_tokens = output_tokens = 0
    final_content = ""

    # Bound the WHOLE turn, not just each provider read. httpx's timeout is a
    # per-read timeout that resets on every SSE chunk, so a slow/drip-feeding
    # endpoint could otherwise pin this worker — and its pooled DB connection —
    # indefinitely across up to MAX_TOOL_ROUNDS+1 rounds. The overall budget is
    # the per-call timeout times the round cap; blowing it surfaces as a provider
    # error so the caller fails closed (generic message + ai.error) rather than
    # letting it escape as a 500.
    deadline = config.timeout_s * (MAX_TOOL_ROUNDS + 1)
    try:
        async with asyncio.timeout(deadline):
            for _round in range(MAX_TOOL_ROUNDS + 1):
                result = None
                async for event in stream_chat_completion(
                    config, messages, tools=tools, max_tokens=max_tokens
                ):
                    if isinstance(event, TextChunk):
                        if stream_live:
                            await on_text(event.text)
                    elif isinstance(event, StreamDone):
                        result = event.result
                if result is None:  # defensive: stream yielded nothing
                    break
                if result.usage:
                    input_tokens += result.usage.input_tokens
                    output_tokens += result.usage.output_tokens
                # Accumulate every round's text (a tool round can carry a preamble
                # alongside its tool calls), so the stored/delivered turn matches.
                if result.content:
                    final_content += result.content
                if not result.tool_calls:
                    break
                messages.append(_assistant_tool_call_message(result))
                for tc in result.tool_calls:
                    tools_used.append(tc.name)
                    output = await execute_tool(tc.name, _parse_args(tc.arguments))
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.name,
                            "content": json.dumps(output, default=str),
                        }
                    )
            else:
                # Exhausted the rounds without a tool-free answer — say so honestly.
                if not final_content:
                    final_content = (
                        "I gathered some data but couldn't finish answering within "
                        "the allowed number of steps. Try asking something more "
                        "specific."
                    )
                    if stream_live:
                        await on_text(final_content)

            if post_process is not None:
                final_content = post_process(final_content)
            if not stream_live and final_content:
                # Buffered path (competitor): deliver the post-processed answer in
                # one shot, so the client never renders text ahead of the scan.
                await on_text(final_content)
    except TimeoutError as exc:
        raise AiProviderError(
            f"the assistant turn exceeded its {deadline}s time budget"
        ) from exc

    return AssistantOutcome(
        content=final_content,
        tools_used=tools_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


async def run_admin_turn(
    db: AsyncSession,
    user: User,
    competition: Competition,
    settings: AiSettings,
    history: list[dict],
    user_message: str,
    *,
    now: datetime,
    on_text: Callable[[str], Awaitable[None]],
) -> AssistantOutcome:
    """Drive one administrator-assistant turn, streaming answer text live through
    ``on_text``. Tool calls execute as ``user`` in ``competition``. ``settings``
    must have its ``api_key`` loaded (the caller undefers it)."""
    config = config_from_settings(settings)
    messages = build_messages(settings, competition, history, user_message, now=now)

    async def execute(name: str, args: dict) -> dict:
        return await execute_admin_tool(db, user, competition.id, name, args)

    return await _drive_turn(
        config,
        messages,
        tools=admin_tool_schemas(),
        max_tokens=settings.max_output_tokens,
        execute_tool=execute,
        on_text=on_text,
        stream_live=True,
    )


def _scrub_competitor_output(text: str) -> str:
    """Competitor output post-processing (buffered path, spec §5), innermost
    first: strip a leading empty tool-call artifact, remove any leaked whole
    tool-call JSON naming a known tool, then redact any flag-shaped string on what
    actually ships. Admin output is never scrubbed — it executes as the organiser
    and streams live, so there's nothing to hide and no buffer to scrub."""
    return redact_flags(scrub_leaked_tool_calls(strip_tool_call_artifacts(text)))


async def run_competitor_turn(
    db: AsyncSession,
    user: User,
    competition: Competition,
    settings: AiSettings,
    comp_settings: AiCompetitionSettings | None,
    history: list[dict],
    user_message: str,
    *,
    now: datetime,
    on_text: Callable[[str], Awaitable[None]],
) -> AssistantOutcome:
    """Drive one competitor-assistant turn. The guidance level (competition
    override → site default) shapes the prompt only; the challenge-metadata toggle
    (a hard data gate) decides whether the challenge tools exist. The answer is
    buffered, flag-format-redacted, then delivered — competitor output is never
    token-streamed ahead of the scan. Tool calls execute as ``user``; the lower
    competitor output cap applies."""
    config = config_from_settings(settings)
    level = resolve_guidance_level(
        comp_settings.guidance_level if comp_settings else None,
        settings.default_guidance_level,
    )
    metadata = bool(comp_settings and comp_settings.challenge_metadata_access)
    system = "\n\n".join(
        [
            _competitor_preamble(competition.name, now),
            guidance_fragment(level),
            settings.competitor_prompt_override or DEFAULT_COMPETITOR_PROMPT,
        ]
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    async def execute(name: str, args: dict) -> dict:
        return await execute_competitor_tool(
            db, user, competition, name, args, challenge_metadata_access=metadata
        )

    return await _drive_turn(
        config,
        messages,
        tools=competitor_tool_schemas(challenge_metadata_access=metadata),
        max_tokens=settings.competitor_max_output_tokens,
        execute_tool=execute,
        on_text=on_text,
        stream_live=False,
        post_process=_scrub_competitor_output,
    )
