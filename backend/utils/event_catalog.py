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
    # A hidden hint became available to everyone (#213) — manual publish, a
    # scheduled release_at, or the publish_hint automation. Distinct from
    # hint.released (grant to one subject); this is "now visible to all".
    "hint.published",
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
    # Profile pictures: actor_user_id distinguishes a self-service change from
    # admin moderation in the audit log.
    "user.avatar_updated",
    "user.avatar_removed",
    # Username (display-name) change. Carries old_name/new_name because every
    # other surface renames retroactively (id-keyed), so the audit log is the
    # only record that "X was previously Y" — actor_user_id tells self from admin.
    "user.renamed",
    # Mass CSV import's single summary (#171) — bulk ops deliberately don't
    # flood `user.created` per row, though each role grant in the file still
    # emits its own `role.assigned`. Stays automation-triggerable (unlike
    # `platform.*`), gated `manage_users` like the rest of the user family.
    "users.imported",
    # Personal API tokens (issue #75) — administrator mint/revoke.
    "api_token.created",
    "api_token.revoked",
    # External identity providers (#58, ADR-0021).
    "auth_provider.created",
    "auth_provider.updated",
    "auth_provider.deleted",
    # Custom pages (#198, ADR-0034) — site-level admin-authored content. Audited
    # like any other mutation: `manage_pages` is delegable, so who changed the
    # public-facing copy and when is exactly the trail an operator needs.
    # Payloads carry the page id/slug, never the document body.
    "page.created",
    "page.updated",
    "page.deleted",
    # AI module (#98, ADR-0023). Provider config change, per-exchange usage
    # (ai.query) and upstream failure (ai.error) — usage metadata only, never
    # message content (spec §4) — plus a competitor's one-time acceptance of the
    # assistant disclosure (Phase 3).
    "ai.settings_updated",
    "ai.query",
    "ai.error",
    "ai.disclosure_accepted",
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
    # Certificates (#219, ADR-0027, optional module). template_updated is the
    # authoring event; released fires once a competition's certificates become
    # downloadable (manual trigger or the scheduled release), driving the
    # per-participant notification + celebratory modal.
    "certificate.template_updated",
    "certificate.released",
    # Post-event report finished rendering (#134, ADR-0030).
    "report.generated",
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
