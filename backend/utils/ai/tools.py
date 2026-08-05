"""Administrator-assistant tool catalogue (#98, ADR-0023 §5.1/§5.4).

Thin, read-only wrappers over the Phase-0 service reads. The load-bearing
property (ADR-0023 §2, non-negotiable): **every tool executes as the requesting
user**, so each handler re-checks ``user_has_permission`` in the conversation's
competition before returning anything, and reuses the same visibility-scoped
service functions the routes use. A fully jailbroken model calling a tool the
caller isn't entitled to gets a permission error, never the data — the tool
*cannot* fetch what the human couldn't.

Everything here is read-only: no tool mutates, so the "every mutation emits an
event" rule is untouched. Results are bounded (list caps + text truncation) so a
tool can't blow the model's context or run up the token bill.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import user_has_permission
from db import utcnow
from models.user import User
from plugins.loader import is_module_enabled
from utils.announcements import list_visible_announcements
from utils.analytics import challenge_analytics
from utils.competitions import get_visible_competition
from utils.feedback import list_surveys, survey_results
from utils.scoreboard import compute_scoreboard
from utils.tickets import list_visible_tickets, ticket_detail, visible_ticket_row

_MAX_ITEMS = 25
_MAX_MESSAGES = 30
_MAX_TEXT = 2000


class ToolError(Exception):
    """A tool refused or failed in a way the model should be told about (a
    permission it lacks, a disabled module, a missing id). Surfaced to the model
    as an ``{"error": ...}`` result, not raised out of the loop."""


ToolHandler = Callable[[AsyncSession, User, str, dict], Awaitable[dict]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: ToolHandler


def _truncate(text: str | None) -> str:
    if not text:
        return ""
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + "…"


async def _require(db: AsyncSession, user: User, competition_id: str, permission: str) -> None:
    if not await user_has_permission(db, user.id, permission, competition_id):
        raise ToolError(
            f"You don't hold the '{permission}' permission in this competition, "
            "so this information isn't available to you."
        )


async def _require_module(db: AsyncSession, competition_id: str, module_id: str) -> None:
    if not await is_module_enabled(db, module_id, competition_id):
        raise ToolError(f"The {module_id} module is disabled for this competition.")


async def _competition_or_error(db: AsyncSession, user: User, competition_id: str):
    competition = await get_visible_competition(db, competition_id, user)
    if competition is None:
        raise ToolError("This competition isn't available to you.")
    return competition


# --- handlers ----------------------------------------------------------------


async def _overview(db, user, competition_id, args) -> dict:
    await _require(db, user, competition_id, "view_competition_analytics")
    c = await _competition_or_error(db, user, competition_id)
    now = utcnow()
    if c.archived_at is not None:
        phase = "archived"
    elif c.start_at is not None and now < c.start_at:
        phase = "not_started"
    elif c.end_at is not None and now >= c.end_at:
        phase = "ended"
    else:
        phase = "running"
    return {
        "name": c.name,
        "phase": phase,
        "paused": c.paused,
        "participation_mode": c.participation_mode,
        "visibility": c.visibility,
        "starts_at": c.start_at.isoformat() if c.start_at else None,
        "ends_at": c.end_at.isoformat() if c.end_at else None,
        "scoreboard_frozen": c.scoreboard_frozen_at is not None,
    }


async def _scoreboard(db, user, competition_id, args) -> dict:
    await _require(db, user, competition_id, "view_competition_analytics")
    c = await _competition_or_error(db, user, competition_id)
    # See the live (unfrozen) board only if the caller may bypass the freeze —
    # exactly what the scoreboard route grants (execution-as-caller).
    live = await user_has_permission(db, user.id, "scoreboard_freeze", competition_id)
    board = await compute_scoreboard(db, c, live=live)
    entries = board.get("entries", [])
    return {
        "frozen": bool(board.get("frozen")),
        "total_entries": len(entries),
        "top": entries[:_MAX_ITEMS],
    }


async def _challenge_stats(db, user, competition_id, args) -> dict:
    await _require(db, user, competition_id, "view_competition_analytics")
    await _require_module(db, competition_id, "analytics")
    c = await _competition_or_error(db, user, competition_id)
    rows = await challenge_analytics(db, c)
    return {"count": len(rows), "challenges": rows[:_MAX_ITEMS]}


async def _search_tickets(db, user, competition_id, args) -> dict:
    await _require(db, user, competition_id, "ticket_view")
    status = args.get("status")
    status = status if status in ("open", "resolved") else None
    tickets = await list_visible_tickets(
        db, competition_id, user, status_filter=status
    )
    query = (args.get("query") or "").strip().lower()
    if query:
        tickets = [t for t in tickets if query in t.subject.lower()]
    return {
        "count": len(tickets),
        "tickets": [t.model_dump(mode="json") for t in tickets[:_MAX_ITEMS]],
    }


async def _get_ticket(db, user, competition_id, args) -> dict:
    await _require(db, user, competition_id, "ticket_view")
    ticket_id = args.get("ticket_id")
    if not ticket_id:
        raise ToolError("A ticket_id is required.")
    if await visible_ticket_row(db, competition_id, ticket_id, user) is None:
        raise ToolError("No such ticket in this competition (or it isn't yours to view).")
    detail = await ticket_detail(db, competition_id, ticket_id, user)
    data = detail.model_dump(mode="json")
    messages = data.get("messages", [])
    for m in messages:
        m["body"] = _truncate(m.get("body"))
        m.pop("attachments", None)  # bytes/metadata the model doesn't need
    data["messages"] = messages[-_MAX_MESSAGES:]
    return data


async def _feedback_summary(db, user, competition_id, args) -> dict:
    await _require(db, user, competition_id, "feedback_view_responses")
    await _require_module(db, competition_id, "feedback")
    survey_id = args.get("survey_id")
    if survey_id:
        results = await survey_results(db, competition_id, survey_id)
        if results is None:
            raise ToolError("No such survey in this competition.")
        return results.model_dump(mode="json")
    return {"surveys": await list_surveys(db, competition_id)}


async def _announcements(db, user, competition_id, args) -> dict:
    await _require(db, user, competition_id, "announcement_create")
    rows = await list_visible_announcements(db, competition_id, user)
    return {
        "count": len(rows),
        "announcements": [
            {
                "id": a.id,
                "title": a.title,
                "body": _truncate(a.body),
                "severity": a.severity,
                "audience_type": a.audience_type,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows[:_MAX_ITEMS]
        ],
    }


_ADMIN_TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "get_competition_overview",
            "Basic status of the active competition: phase, pause state, mode, "
            "visibility, schedule, whether the scoreboard is frozen.",
            {"type": "object", "properties": {}},
            _overview,
        ),
        Tool(
            "get_scoreboard",
            "The current scoreboard standings (top entries) for the active "
            "competition.",
            {"type": "object", "properties": {}},
            _scoreboard,
        ),
        Tool(
            "get_challenge_stats",
            "Per-challenge analytics: solves, attempts, fails, completion rate, "
            "average solve time, hints used, linked tickets.",
            {"type": "object", "properties": {}},
            _challenge_stats,
        ),
        Tool(
            "search_tickets",
            "List support tickets in the active competition, optionally filtered "
            "by status and a substring of the subject.",
            {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["open", "resolved"],
                        "description": "Optional status filter.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional case-insensitive subject substring.",
                    },
                },
            },
            _search_tickets,
        ),
        Tool(
            "get_ticket",
            "The full thread of one support ticket by id.",
            {
                "type": "object",
                "properties": {"ticket_id": {"type": "string"}},
                "required": ["ticket_id"],
            },
            _get_ticket,
        ),
        Tool(
            "get_feedback_summary",
            "Survey feedback. With no argument, lists surveys and response counts; "
            "with a survey_id, returns that survey's aggregated results.",
            {
                "type": "object",
                "properties": {"survey_id": {"type": "string"}},
            },
            _feedback_summary,
        ),
        Tool(
            "get_announcements",
            "Announcements posted in the active competition.",
            {"type": "object", "properties": {}},
            _announcements,
        ),
    ]
}


# Staff-exclusive markers that make a user staff enough to open the admin
# assistant. Deliberately NOT the tool permissions verbatim: a participant holds
# ``ticket_view`` (their own tickets), so the gate keys on ``ticket_assign``
# instead. Each tool still re-checks its own permission, so a staff role that
# somehow lacks a specific read simply gets that one tool's refusal.
_STAFF_MARKER_PERMISSIONS = (
    "view_competition_analytics",
    "ticket_assign",
    "feedback_view_responses",
    "announcement_create",
)


async def can_use_admin_assistant(
    db: AsyncSession, user: User, competition_id: str
) -> bool:
    """Whether ``user`` may open the administrator assistant here — true if they
    hold at least one staff-marker permission (a global Administrator holds all;
    a bare participant holds none and is refused)."""
    for permission in _STAFF_MARKER_PERMISSIONS:
        if await user_has_permission(db, user.id, permission, competition_id):
            return True
    return False


def admin_tool_schemas() -> list[dict]:
    """OpenAI ``tools`` array for the administrator assistant."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in _ADMIN_TOOLS.values()
    ]


async def execute_admin_tool(
    db: AsyncSession, user: User, competition_id: str, name: str, args: dict
) -> dict:
    """Run one tool as ``user`` in ``competition_id``. Any refusal (unknown tool,
    missing permission, disabled module, bad id) comes back as an ``{"error": ...}``
    result the model relays — it is never raised out of the loop, and never
    returns data the caller couldn't already read."""
    tool = _ADMIN_TOOLS.get(name)
    if tool is None:
        return {"error": f"Unknown tool: {name}"}
    if not isinstance(args, dict):
        args = {}
    try:
        return await tool.handler(db, user, competition_id, args)
    except ToolError as exc:
        return {"error": str(exc)}
