"""Automation action executors (ARCHITECTURE.md §5.3) — the full initial set.

Each executor is ``async (db, rule, event_name, payload, config) -> None``,
invoked by the engine (utils/automation_engine.py) for every action of a
matched rule. Conventions held by every executor:

- **Commit what you create.** Executors share the engine's session but own
  their commit, so one action's failure (rolled back by the engine) never
  drops a sibling's already-committed work.
- **Emit the §3.2 event for the mutation.** An automation's side effect is a
  mutation like any other — ``update_score`` emits ``score.adjusted``,
  ``create_ticket`` emits ``ticket.created`` (which is what makes the ticket
  reach the staff queue/notifications exactly like a hand-opened one).
- **Skip, don't raise, on missing context.** A rule on an event whose payload
  lacks the needed subject (e.g. ``create_award`` on an event with no
  user/team) logs and returns — a misaimed rule is an authoring problem, not
  a runtime error worth failing the batch for.
- **Never cross the tenant boundary.** Config-referenced entities
  (hints/challenges) must belong to the event's competition or the action
  skips — a global rule must not be able to unlock competition B's challenge
  from competition A's event (§6.2).

Config shapes are validated by ``schemas/automation.py`` at rule-write time;
executors still read defensively since rows are data, not code.

``webhook`` here is the basic transport — the §5.4 hardening (SSRF blocklist,
header stripping, content-type escaping, chat-token defang) is the next phase
and must land before any public release.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from models.automation import Achievement, AutomationRule
from models.challenge import Challenge
from models.hint import Hint, HintReveal
from models.role import Role, RoleAssignment
from models.score_adjustment import ScoreAdjustment
from models.team import TeamMembership
from models.ticket import Ticket, TicketMessage
from utils import mailer, webhook_security
from utils.event_bus import event_bus
from utils.notifications import broadcast_notifications, create_notifications

logger = logging.getLogger("automation")

Executor = Callable[..., Awaitable[None]]

# {field} placeholders filled from the event payload; unknown fields are left
# verbatim (debuggable), values coerced with str(). Deliberately not str.format
# (no attribute/index access — payload values are adversarial input, §5.4).
_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def render_template(template: str, payload: dict[str, Any]) -> str:
    def _sub(match: re.Match) -> str:
        field = match.group(1)
        return str(payload[field]) if field in payload else match.group(0)

    return _PLACEHOLDER.sub(_sub, template)


async def _notify_users(
    db, user_ids, *, type: str, title: str, body: str | None, competition_id
) -> None:
    made = await create_notifications(
        db,
        [u for u in user_ids if u],
        type=type,
        title=title,
        body=body,
        competition_id=competition_id,
    )
    if made:
        await db.commit()
        await broadcast_notifications(made)


# --- notify (§5.3): in-app notification to a user, team, or role -------------


async def _execute_notify(db, rule, event_name, payload, config) -> None:
    target = config.get("target")
    competition_id = payload.get("competition_id")
    recipients: list[str] = []

    if target == "self":
        recipients = [rule.owner_user_id]
    elif target == "event_user":
        recipients = [payload.get("user_id")]
    elif target == "event_team":
        team_id = payload.get("team_id")
        if team_id:
            rows = await db.scalars(
                select(TeamMembership.user_id).where(
                    TeamMembership.team_id == team_id
                )
            )
            recipients = list(rows)
    elif target == "role":
        # Everyone holding the named role here: assigned to this competition,
        # or globally (a global Administrator holds their role everywhere, §7.5).
        rows = await db.execute(
            select(RoleAssignment.user_id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                Role.name == config.get("role_name"),
                (RoleAssignment.competition_id == competition_id)
                | (RoleAssignment.competition_id.is_(None)),
            )
        )
        recipients = [user_id for (user_id,) in rows]

    if not recipients:
        logger.info("notify: no recipients for rule %s on %s", rule.id, event_name)
        return
    await _notify_users(
        db,
        dict.fromkeys(recipients),
        type=event_name,
        title=render_template(config.get("title", ""), payload),
        body=(
            render_template(config["body"], payload) if config.get("body") else None
        ),
        competition_id=competition_id,
    )


# --- send_email (§5.3): templated, payload-interpolated ----------------------


async def _execute_send_email(db, rule, event_name, payload, config) -> None:
    await mailer.send_email(
        to=list(config.get("to", [])),
        subject=render_template(config.get("subject", ""), payload),
        body=render_template(config.get("body", ""), payload),
    )


# --- webhook (§5.3): outbound HTTP call, hardened per §5.4 -------------------


async def _execute_webhook(db, rule, event_name, payload, config) -> None:
    import httpx

    url = config["url"]
    # §5.4: SSRF check on every call (DNS may have changed since rule save).
    try:
        await webhook_security.validate_webhook_url(url)
    except webhook_security.WebhookSecurityError as exc:
        logger.warning("webhook: rule %s refused unsafe target: %s", rule.id, exc)
        return

    # §5.4: strip caller-uncontrollable headers from the admin header set.
    headers = webhook_security.sanitize_headers(config.get("headers"))

    # A body_template (admin-authored) has its competitor-controlled values
    # escaped + defanged for the declared content type (§5.4); without one we
    # send the structured event as JSON to a generic endpoint (json.dumps
    # serialisation is injection-safe on its own).
    request_kwargs: dict = {"headers": headers}
    template = config.get("body_template")
    if template:
        content_type = config.get("content_type", "application/json")
        body = webhook_security.render_webhook_body(template, payload, content_type)
        headers["Content-Type"] = content_type
        request_kwargs["content"] = body.encode()
    else:
        request_kwargs["json"] = {
            "event": event_name,
            "payload": payload,
            "rule": {"id": rule.id, "name": rule.name},
        }

    # follow_redirects stays off (httpx default) so a 302 can't bounce the
    # request past the SSRF check to an internal target (§5.4).
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
        response = await client.post(url, **request_kwargs)
    logger.info("webhook: rule %s POST %s -> %s", rule.id, url, response.status_code)


# --- release_hint (§5.3): unlock a hint for the event's subject, free --------


async def _execute_release_hint(db, rule, event_name, payload, config) -> None:
    competition_id = payload.get("competition_id")
    user_id = payload.get("user_id")
    if not competition_id or not user_id:
        logger.info("release_hint: no subject on %s; skipping", event_name)
        return
    hint = await db.get(Hint, config.get("hint_id"))
    # Tenant guard: the configured hint must belong to the event's competition.
    if hint is None or hint.competition_id != competition_id:
        logger.warning("release_hint: hint not in competition; rule %s", rule.id)
        return

    team_id = payload.get("team_id")
    # Idempotent per subject, like an explicit reveal: released once, not per event.
    subject_filter = (
        (HintReveal.team_id == team_id)
        if team_id
        else ((HintReveal.user_id == user_id) & (HintReveal.team_id.is_(None)))
    )
    existing = await db.scalar(
        select(HintReveal.id).where(HintReveal.hint_id == hint.id, subject_filter)
    )
    if existing is not None:
        return

    db.add(
        HintReveal(
            competition_id=competition_id,
            hint_id=hint.id,
            challenge_id=hint.challenge_id,
            user_id=user_id,
            team_id=team_id,
            # A granted hint costs nothing — nobody chose to pay for it.
            cost_charged=0,
        )
    )
    await db.commit()
    await event_bus.emit(
        "hint.released",
        {
            "competition_id": competition_id,
            "challenge_id": hint.challenge_id,
            "hint_id": hint.id,
            "user_id": user_id,
            "team_id": team_id,
            "rule_id": rule.id,
        },
    )


# --- unlock_challenge (§5.3): publish a draft (e.g. bonus on first blood) ----


async def _execute_unlock_challenge(db, rule, event_name, payload, config) -> None:
    competition_id = payload.get("competition_id")
    challenge = await db.get(Challenge, config.get("challenge_id"))
    # Tenant guard (§6.2): never unlock across the competition boundary.
    if (
        challenge is None
        or not competition_id
        or challenge.competition_id != competition_id
    ):
        logger.warning("unlock_challenge: challenge not in competition; rule %s", rule.id)
        return
    if challenge.state == "published":
        return  # idempotent
    challenge.state = "published"
    await db.commit()
    await event_bus.emit(
        "challenge.published",
        {
            "competition_id": competition_id,
            "challenge_id": challenge.id,
            "title": challenge.title,
            "rule_id": rule.id,
        },
    )


# --- open_survey (§5.3 extension): mark a survey open for responses ----------


async def _execute_open_survey(db, rule, event_name, payload, config) -> None:
    from models.feedback import Survey

    competition_id = payload.get("competition_id")
    survey = await db.get(Survey, config.get("survey_id"))
    # Tenant guard (§6.2): only open a survey in the event's own competition.
    if survey is None or not competition_id or survey.competition_id != competition_id:
        logger.warning("open_survey: survey not in competition; rule %s", rule.id)
        return
    if survey.is_open:
        return  # idempotent
    survey.is_open = True
    await db.commit()
    # Same event the feedback router emits on a manual open — so "notify on
    # survey.opened" rules fire whether a human or a rule opened it.
    await event_bus.emit(
        "survey.opened",
        {
            "competition_id": competition_id,
            "survey_id": survey.id,
            "title": survey.title,
            "rule_id": rule.id,
        },
    )


# --- create_ticket (§5.3): open a thread in the event's context --------------


async def _execute_create_ticket(db, rule, event_name, payload, config) -> None:
    competition_id = payload.get("competition_id")
    opener_user_id = payload.get("user_id")
    # A ticket needs an opener; a system-authored (openerless) ticket would need
    # a schema change — until then the event's user is the thread's competitor
    # side, which fits the "open a thread about what just happened" use.
    if not competition_id or not opener_user_id:
        logger.info("create_ticket: no opener on %s; skipping", event_name)
        return
    membership = await db.scalar(
        select(TeamMembership).where(
            TeamMembership.competition_id == competition_id,
            TeamMembership.user_id == opener_user_id,
        )
    )
    subject = render_template(config.get("subject", ""), payload)
    ticket = Ticket(
        competition_id=competition_id,
        subject=subject,
        challenge_id=payload.get("challenge_id"),
        opener_user_id=opener_user_id,
        team_id=membership.team_id if membership else None,
    )
    db.add(ticket)
    await db.flush()
    db.add(
        TicketMessage(
            competition_id=competition_id,
            ticket_id=ticket.id,
            author_user_id=opener_user_id,
            body=render_template(config.get("body", ""), payload),
            is_internal=False,
        )
    )
    await db.commit()
    # Same event the router emits — the staff queue, notifications and audio
    # cue treat an automation-opened ticket exactly like a hand-opened one.
    await event_bus.emit(
        "ticket.created",
        {
            "competition_id": competition_id,
            "ticket_id": ticket.id,
            "opener_user_id": opener_user_id,
            "subject": subject,
            "rule_id": rule.id,
        },
    )


# --- update_score (§5.3): signed bonus/penalty adjustment --------------------


async def _execute_update_score(db, rule, event_name, payload, config) -> None:
    competition_id = payload.get("competition_id")
    user_id = payload.get("user_id")
    team_id = payload.get("team_id")
    if not competition_id or not (user_id or team_id):
        logger.info("update_score: no subject on %s; skipping", event_name)
        return
    adjustment = ScoreAdjustment(
        competition_id=competition_id,
        points=int(config.get("points", 0)),
        reason=render_template(config.get("reason", ""), payload),
        user_id=user_id,
        team_id=team_id,
        rule_id=rule.id,
    )
    db.add(adjustment)
    await db.commit()
    await event_bus.emit(
        "score.adjusted",
        {
            "competition_id": competition_id,
            "user_id": user_id,
            "team_id": team_id,
            "points": adjustment.points,
            "reason": adjustment.reason,
            "rule_id": rule.id,
        },
    )


# --- create_award (§5.3): a titled award that also grants points -------------


async def _execute_create_award(db, rule, event_name, payload, config) -> None:
    competition_id = payload.get("competition_id")
    user_id = payload.get("user_id")
    team_id = payload.get("team_id")
    if not competition_id or not (user_id or team_id):
        logger.info("create_award: no subject on %s; skipping", event_name)
        return
    achievement = Achievement(
        competition_id=competition_id,
        title=render_template(config.get("title", ""), payload),
        description=(
            render_template(config["description"], payload)
            if config.get("description")
            else None
        ),
        points=int(config.get("points", 0) or 0),
        user_id=user_id,
        team_id=team_id,
        rule_id=rule.id,
    )
    db.add(achievement)
    await db.commit()
    await event_bus.emit(
        "achievement.awarded",
        {
            "competition_id": competition_id,
            "user_id": user_id,
            "team_id": team_id,
            "title": achievement.title,
            "points": achievement.points,
            "rule_id": rule.id,
        },
    )


# --- registry ----------------------------------------------------------------


@dataclass(frozen=True)
class ActionSpec:
    execute: Executor
    # Whether a personal rule (§5.1) may use this type. Only notify — and the
    # schema layer additionally forces its target to "self".
    personal_allowed: bool = False


ACTIONS: dict[str, ActionSpec] = {
    "notify": ActionSpec(_execute_notify, personal_allowed=True),
    "send_email": ActionSpec(_execute_send_email),
    "webhook": ActionSpec(_execute_webhook),
    "release_hint": ActionSpec(_execute_release_hint),
    "unlock_challenge": ActionSpec(_execute_unlock_challenge),
    "open_survey": ActionSpec(_execute_open_survey),
    "create_ticket": ActionSpec(_execute_create_ticket),
    "update_score": ActionSpec(_execute_update_score),
    "create_award": ActionSpec(_execute_create_award),
}


async def execute_action(
    db, rule: AutomationRule, event_name: str, payload: dict, action: dict
) -> None:
    spec = ACTIONS.get(action.get("type", ""))
    if spec is None:
        logger.warning("unknown action type %r on rule %s", action.get("type"), rule.id)
        return
    await spec.execute(db, rule, event_name, payload, action)
