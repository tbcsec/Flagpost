"""The canonical §3.2 event vocabulary, mirrored in code (ARCHITECTURE.md §3.2).

One authoritative list of every ``<entity>.<verb>`` event the platform emits,
kept in lockstep with the doc — §3.2 says the vocabulary "should be documented
and versioned alongside the schema, not left implicit in code"; this is the
in-code half. Consumers:

- the automation engine (§5.1): a rule's ``trigger_type`` must be a name from
  this catalog — that's what makes "anything that emits an event is
  automatable" checkable rather than aspirational;
- the rule-builder UI (Phase 3) reads it to offer the trigger list.

``TRIGGERABLE_EVENTS`` excludes the ``automation.*`` family: the engine never
evaluates its own events as triggers (the trivial self-loop guard, §5.2).
"""

from __future__ import annotations

EVENT_TYPES: tuple[str, ...] = (
    "competition.created",
    "competition.updated",
    "competition.archived",
    "competition.unarchived",
    "competition.deleted",
    "competition.started",
    "competition.ended",
    "competition.member_joined",
    # Emitted by the scheduler as a competition nears its end_at (§5.2) — a
    # time-based trigger, unlike the mutation events around it.
    "competition.time_remaining",
    "team.created",
    "team.member_joined",
    "team.member_left",
    "team.deleted",
    "challenge.created",
    "challenge.updated",
    "challenge.published",
    "challenge.deleted",
    "challenge.solved",
    "challenge.guesses_reset",
    "challenge.rated",
    "challenge.hint_requested",
    "hint.released",
    "category.created",
    "category.deleted",
    "user.registered",
    "user.password_changed",
    "user.created",
    "user.updated",
    "user.banned",
    "user.unbanned",
    "user.deleted",
    "role.created",
    "role.updated",
    "role.deleted",
    "role.assigned",
    "role.unassigned",
    "ticket.created",
    "ticket.assigned",
    "ticket.resolved",
    "ticket.message_posted",
    "survey.submitted",
    "survey.opened",
    "announcement.published",
    "site.settings_updated",
    "score.adjusted",
    "achievement.awarded",
    "scoreboard.frozen",
    "scoreboard.unfrozen",
    "module.enabled",
    "module.disabled",
    "automation.rule_triggered",
    "automation.rule_created",
    "automation.rule_updated",
    "automation.rule_deleted",
    # Platform administration (Admin → Site settings). Not competition events, so
    # they're excluded from automation triggers below.
    "platform.imported",
)

TRIGGERABLE_EVENTS: tuple[str, ...] = tuple(
    name
    for name in EVENT_TYPES
    if not name.startswith(("automation.", "platform."))
)

_TRIGGERABLE_SET = frozenset(TRIGGERABLE_EVENTS)


def is_triggerable(event_name: str) -> bool:
    return event_name in _TRIGGERABLE_SET
