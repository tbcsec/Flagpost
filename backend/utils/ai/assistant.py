"""Administrator-assistant orchestration (#98, ADR-0023).

Runs one assistant turn: assemble the prompt, stream the model, resolve any tool
calls **as the requesting user**, feed the results back, and stream the final
answer. The tool loop is bounded so a model that keeps calling tools can't spin
forever, and the whole exchange is read-only (the tools don't mutate).

Prompt shape (spec §6): a small **non-overridable preamble** (assistant identity,
competition, server time, that access is read-only) is injected ahead of the
configured system prompt, which is the code-shipped default unless an admin set
an override. Per the ADR-0023 axiom the prompt governs tone and topicality only —
no data-scoping property depends on it; the tools' permission checks are the
guarantee.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from models.ai import AiSettings
from models.competition import Competition
from models.user import User
from utils.ai.client import (
    StreamDone,
    TextChunk,
    config_from_settings,
    stream_chat_completion,
)
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


def _preamble(competition_name: str, now: datetime) -> str:
    return (
        f'You are assisting a competition organiser with the competition '
        f'"{competition_name}". The current server time is {now.isoformat()}. '
        f"Your access is read-only and scoped to this competition."
    )


@dataclass
class AssistantOutcome:
    """The durable result of one turn — what to persist and to put in the usage
    counter / ai.query event. The streamed text was already delivered via the
    ``on_text`` callback; ``content`` is the same text, assembled, for storage."""

    content: str
    tools_used: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


def build_messages(
    settings: AiSettings,
    competition: Competition,
    history: list[dict],
    user_message: str,
    *,
    now: datetime,
) -> list[dict]:
    system = _preamble(competition.name, now) + "\n\n" + (
        settings.admin_prompt_override or DEFAULT_ADMIN_PROMPT
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    return messages


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
    """Drive one administrator-assistant turn, streaming answer text through
    ``on_text``. Tool calls execute as ``user`` in ``competition``; the loop runs
    at most :data:`MAX_TOOL_ROUNDS` tool rounds. ``settings`` must have its
    ``api_key`` loaded (the caller undefers it). Provider failures propagate as
    ``AiProviderError`` for the caller to turn into an ``ai.error``."""
    config = config_from_settings(settings)
    tools = admin_tool_schemas()
    messages = build_messages(settings, competition, history, user_message, now=now)

    tools_used: list[str] = []
    input_tokens = output_tokens = 0
    final_content = ""

    for _round in range(MAX_TOOL_ROUNDS + 1):
        result = None
        async for event in stream_chat_completion(
            config, messages, tools=tools, max_tokens=settings.max_output_tokens
        ):
            if isinstance(event, TextChunk):
                await on_text(event.text)
            elif isinstance(event, StreamDone):
                result = event.result
        if result is None:  # defensive: stream yielded nothing
            break
        if result.usage:
            input_tokens += result.usage.input_tokens
            output_tokens += result.usage.output_tokens
        # Accumulate every round's text, not just the final round's: a tool round
        # can carry a preamble ("let me check the scoreboard…") alongside its tool
        # calls, and that text was already streamed to the client via on_text — so
        # the stored turn must include it too, or the transcript won't match what
        # the user saw.
        if result.content:
            final_content += result.content
        if not result.tool_calls:
            break
        messages.append(_assistant_tool_call_message(result))
        for tc in result.tool_calls:
            tools_used.append(tc.name)
            output = await execute_admin_tool(
                db, user, competition.id, tc.name, _parse_args(tc.arguments)
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": json.dumps(output, default=str),
                }
            )
    else:
        # Exhausted the rounds without a tool-free answer — give the organiser
        # something honest rather than nothing.
        if not final_content:
            final_content = (
                "I gathered some data but couldn't finish answering within the "
                "allowed number of steps. Try asking something more specific."
            )
            await on_text(final_content)

    return AssistantOutcome(
        content=final_content,
        tools_used=tools_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
