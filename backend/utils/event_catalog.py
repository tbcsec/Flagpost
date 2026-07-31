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
    # A user accepted the competition's effective rules / code of conduct (#57)
    # — recorded so organisers can audit who agreed, and when.
    "competition.rules_accepted",
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
    # Every *graded* flag submission, right or wrong (§13.2 logs the row; this
    # is its event half). Wrong guesses previously emitted nothing, leaving
    # attempt-counting surfaces (dashboard stats, challenge health, analytics)
    # stale until the next solve. Bounded by the submission rate limit.
    "challenge.attempted",
    "challenge.guesses_reset",
    "challenge.rated",
    "challenge.hint_requested",
    "hint.released",
    "category.created",
    "category.deleted",
    "user.registered",
    "user.password_changed",
    "user.email_verified",
    "user.created",
    "user.updated",
    "user.banned",
    "user.unbanned",
    "user.deleted",
    # Personal API tokens (issue #75) — administrator mint/revoke.
    "api_token.created",
    "api_token.revoked",
    # External identity providers (#58, ADR-0021).
    "auth_provider.created",
    "auth_provider.updated",
    "auth_provider.deleted",
    # An external identity was attached to (or detached from) a local account.
    "identity.linked",
    "identity.unlinked",
    "role.created",
    "role.updated",
    "role.deleted",
    "role.assigned",
    "role.unassigned",
    "ticket.created",
    "ticket.assigned",
    "ticket.resolved",
    "ticket.message_posted",
    # Screenshots on a ticket thread (issue #80).
    "ticket.attachment_added",
    "ticket.attachment_deleted",
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
