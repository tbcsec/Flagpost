"""Competitor-assistant tool catalogue (#98, ADR-0023 Phase 3, spec §5.1/§3.1).

Read-only tools for the competitor assistant, all executing **as the requesting
competitor**. The load-bearing safety property is structural, not behavioural:

- Challenge tools reuse ``ChallengeOut`` and the existing visibility path
  (``load_visible_challenge`` / the published-and-released filter). ``ChallengeOut``
  has no field that can carry a flag, hash, salt, regex, or the correct
  multiple-choice option (spec §3.1), so a fully jailbroken model has nothing to
  leak from these tools.
- The challenge tools exist **only when the per-competition challenge-metadata
  toggle is on** — a hard, code-enforced data toggle (``AiCompetitionSettings.
  challenge_metadata_access``), distinct from the behavioural guidance level and
  never conflated with it (spec §5). With the toggle off, the model isn't offered
  the tools at all, so it cannot read challenge specifics regardless of prompt.
- The scoreboard/standing/announcement tools return only what the competitor can
  already see in the UI (public standings respecting the freeze; their own
  standing; audience-appropriate announcements).

Every handler re-checks ``challenge_view`` in the competition first — the
"is a player here" marker a Participant holds — so a caller who somehow isn't a
participant gets a refusal, not data.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import user_has_permission
from db import ensure_aware_utc, utcnow
from models.challenge import Challenge
from models.competition import Competition
from models.user import User
from schemas.challenge import ChallengeOut
from utils.announcements import list_visible_announcements
from utils.richtext import doc_to_text
from utils.scoreboard import compute_scoreboard
from utils.scoring import resolve_subject, solved_challenge_ids

# Shared with the admin tools' shape; re-declared here to keep the two catalogues
# independent (they gate on different permissions and expose different data).
_MAX_ITEMS = 25
_MAX_TEXT = 2000

logger = logging.getLogger("ai")


class ToolError(Exception):
    """A competitor tool refused (missing permission, disabled data, bad id).
    Surfaced to the model as ``{"error": ...}``, never raised out of the loop."""


def _truncate(text: str | None) -> str:
    if not text:
        return ""
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + "…"


def _str_arg(args: dict, key: str) -> str | None:
    """A string argument value, or None if absent/non-string. Model-supplied
    arguments are untrusted, so a non-scalar (dict/list) value must never reach a
    query — binding one raises a DB error that poisons the session on Postgres."""
    value = args.get(key)
    return value if isinstance(value, str) else None


async def _require_player(db: AsyncSession, user: User, competition_id: str) -> None:
    if not await user_has_permission(db, user.id, "challenge_view", competition_id):
        raise ToolError("This information isn't available to you in this competition.")


def _is_released(challenge: Challenge) -> bool:
    return (
        challenge.release_at is None
        or ensure_aware_utc(challenge.release_at) <= utcnow()
    )


def _challenge_summary(challenge: Challenge, solved: set[str]) -> dict:
    """A concise, safe projection of a challenge for the list tool. Built from the
    ORM object's non-flag fields only; ``has_flag`` is the single flag-related
    fact, inherited from what ``ChallengeOut`` chooses to expose."""
    locked = any(pid not in solved for pid in (challenge.prerequisites or []))
    return {
        "id": challenge.id,
        "title": challenge.title,
        "category_id": challenge.category_id,
        "points": challenge.points,
        "tags": challenge.tags or [],
        "difficulty": challenge.difficulty,
        "flag_type": challenge.flag_type,
        "solved": challenge.id in solved,
        "locked": locked,
    }


# --- handlers ----------------------------------------------------------------


async def _scoreboard(db, user, competition, args) -> dict:
    await _require_player(db, user, competition.id)
    # live=False: a competitor never bypasses the freeze (that needs
    # scoreboard_freeze, which they don't hold) — the frozen board is what they
    # see in the UI, so it's what the assistant sees.
    board = await compute_scoreboard(db, competition, live=False)
    entries = board.get("entries", [])
    return {
        "frozen": bool(board.get("frozen")),
        "mode": board.get("mode"),
        "total_entries": len(entries),
        "top": entries[:_MAX_ITEMS],
    }


async def _my_standing(db, user, competition, args) -> dict:
    await _require_player(db, user, competition.id)
    subject = await resolve_subject(db, competition, user)
    if subject is None:
        return {"ranked": False, "detail": "You aren't on the scoreboard yet."}
    board = await compute_scoreboard(db, competition, live=False)
    for entry in board.get("entries", []):
        if entry.get("subject_id") == subject.id:
            return {
                "ranked": True,
                "rank": entry.get("rank"),
                "points": entry.get("points"),
                "name": entry.get("name"),
            }
    return {"ranked": False, "detail": "You aren't on the scoreboard yet."}


async def _announcements(db, user, competition, args) -> dict:
    await _require_player(db, user, competition.id)
    rows = await list_visible_announcements(db, competition.id, user)
    return {
        "count": len(rows),
        "announcements": [
            {
                "title": a.title,
                "body": _truncate(a.body),
                "severity": a.severity,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows[:_MAX_ITEMS]
        ],
    }


async def _visible_challenges(db, competition_id: str) -> list[Challenge]:
    rows = (
        (
            await db.execute(
                select(Challenge)
                .where(
                    Challenge.competition_id == competition_id,
                    Challenge.state == "published",
                    or_(
                        Challenge.release_at.is_(None),
                        Challenge.release_at <= utcnow(),
                    ),
                )
                .order_by(Challenge.created_at)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _list_challenges(db, user, competition, args) -> dict:
    await _require_player(db, user, competition.id)
    challenges = await _visible_challenges(db, competition.id)
    subject = await resolve_subject(db, competition, user)
    solved = (
        await solved_challenge_ids(db, competition.id, subject)
        if subject is not None
        else set()
    )
    return {
        "count": len(challenges),
        "challenges": [
            _challenge_summary(c, solved) for c in challenges[:_MAX_ITEMS]
        ],
    }


async def _get_challenge(db, user, competition, args) -> dict:
    await _require_player(db, user, competition.id)
    challenge_id = _str_arg(args, "challenge_id")
    if not challenge_id:
        raise ToolError("A valid challenge_id is required.")
    challenge = await db.scalar(
        select(Challenge).where(
            Challenge.competition_id == competition.id,
            Challenge.id == challenge_id,
        )
    )
    # Draft/unreleased challenges are invisible to a competitor — indistinguishable
    # from missing, exactly as the challenge route treats them.
    if challenge is None or challenge.state != "published" or not _is_released(challenge):
        raise ToolError("No such challenge is available to you in this competition.")
    subject = await resolve_subject(db, competition, user)
    solved = (
        await solved_challenge_ids(db, competition.id, subject)
        if subject is not None
        else set()
    )
    # Serialize through ChallengeOut so the flag-exclusion guarantee is inherited,
    # then hand the model plain-text description rather than the TipTap tree.
    out = ChallengeOut.model_validate(challenge)
    data = _challenge_summary(challenge, solved)
    data["description"] = _truncate(doc_to_text(challenge.description))
    data["has_flag"] = out.has_flag
    data["choices"] = out.choices  # options only; the correct one is never marked
    return data


# --- catalogue ---------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[AsyncSession, User, Competition, dict], Awaitable[dict]]
    needs_challenge_metadata: bool = False


_TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "get_scoreboard",
            "The current public scoreboard standings (top entries) for this "
            "competition, respecting any freeze.",
            {"type": "object", "properties": {}},
            _scoreboard,
        ),
        Tool(
            "get_my_standing",
            "The requesting competitor's own current rank and points.",
            {"type": "object", "properties": {}},
            _my_standing,
        ),
        Tool(
            "get_announcements",
            "Organiser announcements for this competition — schedule changes, "
            "challenge releases, rule clarifications, and hint or infrastructure "
            "updates. Use it for questions about competition logistics or what the "
            "organisers have posted.",
            {"type": "object", "properties": {}},
            _announcements,
        ),
        Tool(
            "list_challenges",
            "List the challenges available to the competitor: title, category, "
            "points, tags, difficulty, and whether they've solved or it's locked. "
            "Never includes flags or solutions.",
            {"type": "object", "properties": {}},
            _list_challenges,
            needs_challenge_metadata=True,
        ),
        Tool(
            "get_challenge",
            "Public details of one challenge by id: description, points, tags, "
            "difficulty, multiple-choice options. Never includes the flag or the "
            "correct option.",
            {
                "type": "object",
                "properties": {"challenge_id": {"type": "string"}},
                "required": ["challenge_id"],
            },
            _get_challenge,
            needs_challenge_metadata=True,
        ),
    ]
}


def competitor_tool_names() -> tuple[str, ...]:
    """Every competitor tool name — the allowlist the output leak-scrub anchors on
    (``utils.ai.artifacts``), sourced here so it can't drift from this catalogue
    when a tool is renamed or added."""
    return tuple(_TOOLS)


def competitor_tool_schemas(*, challenge_metadata_access: bool) -> list[dict]:
    """The OpenAI ``tools`` array offered to the competitor assistant. The
    challenge tools are included **only** when the data toggle is on — with it
    off they don't exist for the model, which is the hard guarantee (not the
    prompt)."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in _TOOLS.values()
        if challenge_metadata_access or not t.needs_challenge_metadata
    ]


async def execute_competitor_tool(
    db: AsyncSession,
    user: User,
    competition: Competition,
    name: str,
    args: dict,
    *,
    challenge_metadata_access: bool,
) -> dict:
    """Run one competitor tool as ``user``. A tool gated on the challenge-metadata
    toggle refuses when it's off even if the model somehow names it (belt to the
    schema's braces). Refusals come back as ``{"error": ...}``, never raised."""
    tool = _TOOLS.get(name)
    if tool is None:
        return {"error": f"Unknown tool: {name}"}
    if tool.needs_challenge_metadata and not challenge_metadata_access:
        return {"error": "Challenge details aren't available for this competition."}
    if not isinstance(args, dict):
        args = {}
    try:
        return await tool.handler(db, user, competition, args)
    except ToolError as exc:
        return {"error": str(exc)}
    except Exception:
        # Fail closed: a handler bug or a malformed model-supplied argument that
        # slipped through degrades to a tool error the model relays, never a 500
        # that escapes the loop (which would also skip the ai.error oversight
        # emit). Roll back so a mid-statement DB error — which poisons the
        # transaction on Postgres — can't break the turn's own commit.
        logger.exception("competitor tool %s failed", name)
        await db.rollback()
        return {"error": "That lookup didn't work — please try again."}
