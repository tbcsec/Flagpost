"""Builder catalog for the automation rule editor (ARCHITECTURE.md §5.5).

The visual builder (Tier 3 Phase 3) is **generated from this catalog**, not
hand-coded per action — so adding an action type (or a field to one) is a
backend-only change that the UI picks up. It describes, for the editor:

- **triggers** — each §3.2 triggerable event plus the payload fields it carries,
  so a condition can pick a field and a template can offer ``{placeholders}``;
- **operators** — the condition operators, flagged ``unary`` when they take no
  value (``exists``/``not_exists``);
- **actions** — each §5.3 action type, whether a personal rule may use it
  (§5.1), and its config **fields** with a UI ``kind``.

Field descriptors are hand-authored alongside the Pydantic action models in
``schemas/automation.py`` rather than derived from them (a discriminated union
of custom-kinded fields doesn't reduce to a clean UI schema); a drift test keeps
the two in lockstep.
"""

from __future__ import annotations

from config import settings
from models.announcement import SEVERITIES
from utils.automation_actions import ACTIONS, DEMO_DISABLED_ACTIONS, FRIENDLY_FIELDS
from utils.automation_engine import CONDITION_OPERATORS
from utils.event_catalog import TRIGGERABLE_EVENTS

# Payload fields each trigger carries (for condition fields + {placeholders}).
# The builder's field input is a free-text combobox, so an omitted/partial entry
# only costs suggestions, never capability — this is a convenience, not a schema.
_COMMON_FIELDS = ["competition_id", "user_id", "team_id"]
TRIGGER_FIELDS: dict[str, list[str]] = {
    "challenge.solved": [
        "competition_id", "challenge_id", "user_id", "team_id", "points",
        "is_first_blood",
    ],
    "challenge.published": ["competition_id", "challenge_id", "user_id", "title"],
    "challenge.created": ["competition_id", "challenge_id", "user_id", "title"],
    "challenge.updated": ["competition_id", "challenge_id"],
    "challenge.attempted": [
        "competition_id", "challenge_id", "user_id", "team_id", "correct",
    ],
    "challenge.guesses_reset": ["competition_id", "challenge_id", "user_id", "team_id"],
    "challenge.rated": ["competition_id", "challenge_id", "user_id", "rating"],
    "challenge.hint_requested": [
        "competition_id", "challenge_id", "hint_id", "user_id", "team_id", "cost",
    ],
    "hint.released": [
        "competition_id", "challenge_id", "hint_id", "user_id", "team_id",
    ],
    "hint.published": ["competition_id", "challenge_id", "hint_id"],
    "ticket.created": ["competition_id", "ticket_id", "opener_user_id", "subject"],
    "ticket.assigned": ["competition_id", "ticket_id", "assignee_user_id"],
    "ticket.resolved": ["competition_id", "ticket_id"],
    "ticket.message_posted": [
        "competition_id", "ticket_id", "author_user_id", "is_internal",
    ],
    "ticket.attachment_added": [
        "competition_id", "ticket_id", "message_id", "attachment_id",
        "actor_user_id", "is_internal",
    ],
    "ticket.attachment_deleted": [
        "competition_id", "ticket_id", "message_id", "attachment_id",
        "actor_user_id",
    ],
    "score.adjusted": [
        "competition_id", "user_id", "team_id", "points", "reason",
    ],
    "achievement.awarded": ["competition_id", "user_id", "team_id", "title", "points"],
    "scoreboard.frozen": ["competition_id", "frozen_at"],
    "scoreboard.unfrozen": ["competition_id"],
    "competition.member_joined": ["competition_id", "user_id"],
    "competition.rules_accepted": ["competition_id", "user_id"],
    "competition.archived": ["competition_id"],
    "competition.unarchived": ["competition_id"],
    # `auto` distinguishes a retention purge (#26) from a manual delete.
    "competition.deleted": ["competition_id", "user_id", "auto"],
    "competition.time_remaining": ["competition_id", "minutes_remaining"],
    "competition.started": ["competition_id", "name"],
    "competition.ended": ["competition_id", "name"],
    "team.created": ["competition_id", "team_id"],
    "team.member_joined": ["competition_id", "team_id", "user_id"],
    "announcement.published": [
        "competition_id", "announcement_id", "title", "body", "severity",
        "audience_type",
    ],
    "survey.submitted": ["competition_id", "user_id", "survey_id", "response_id"],
    "survey.opened": ["competition_id", "survey_id", "title"],
    "certificate.template_updated": ["competition_id", "certificate_template_id"],
    "certificate.released": ["competition_id", "certificate_template_id"],
    "user.registered": ["user_id"],
    "user.email_verified": ["user_id"],
    "user.created": ["user_id", "email", "actor_user_id"],
    "user.updated": ["user_id", "actor_user_id"],
    "user.banned": ["user_id", "actor_user_id"],
    "user.unbanned": ["user_id", "actor_user_id"],
    "user.deleted": ["user_id", "actor_user_id"],
    # Mass CSV import summary (#171): user_id is the importing admin.
    "users.imported": ["user_id", "created", "skipped", "roles_assigned"],
    "api_token.created": ["api_token_id", "user_id", "created_by_user_id"],
    "api_token.revoked": ["api_token_id", "user_id"],
    "auth_provider.created": ["provider_id", "slug", "kind", "actor_user_id"],
    "auth_provider.updated": ["provider_id", "slug", "kind", "changed_fields", "actor_user_id"],
    "auth_provider.deleted": ["provider_id", "slug", "kind", "actor_user_id"],
    "identity.linked": ["user_id", "provider_id", "provider_slug"],
    "identity.unlinked": ["user_id", "provider_id", "provider_slug"],
}

# The permission that governs *observing* each trigger event (§5.1 trigger
# authorization). An org rule's creator must hold this in the rule's scope, so a
# Judge can't automate on — and thereby exfiltrate — an admin-only event like a
# role assignment. Tiers: global-admin domains (roles/users/site) need their
# global permission; staff events need a staff competition permission; events
# every competition member can already see map to `challenge_view` (the baseline
# a Participant holds). A drift test asserts every triggerable event is mapped.
TRIGGER_PERMISSIONS: dict[str, str] = {
    # Global admin domains — a competition role never grants these.
    "role.created": "manage_roles",
    "role.updated": "manage_roles",
    "role.deleted": "manage_roles",
    "role.assigned": "manage_roles",
    "role.unassigned": "manage_roles",
    "user.registered": "manage_users",
    "user.password_changed": "manage_users",
    "user.email_verified": "manage_users",
    "user.created": "manage_users",
    "user.updated": "manage_users",
    "user.banned": "manage_users",
    "user.unbanned": "manage_users",
    "user.deleted": "manage_users",
    "users.imported": "manage_users",
    "api_token.created": "manage_api_tokens",
    "api_token.revoked": "manage_api_tokens",
    # Who can log in is admin-domain data, like roles and users.
    "auth_provider.created": "manage_auth_providers",
    "auth_provider.updated": "manage_auth_providers",
    "auth_provider.deleted": "manage_auth_providers",
    "identity.linked": "manage_users",
    "identity.unlinked": "manage_users",
    "site.settings_updated": "manage_site_settings",
    # AI provider config is admin-domain, like site settings and auth providers.
    "ai.settings_updated": "manage_ai",
    # Per-competition assistant usage/errors — staff operational data, like the
    # analytics an org can already see.
    "ai.query": "view_competition_analytics",
    "ai.error": "view_competition_analytics",
    # Same oversight tier as transcript review — it's who accepted the terms of
    # that channel.
    "ai.disclosure_accepted": "ai_view_transcripts",
    # Competition-lifecycle / staff events.
    "competition.created": "edit_competition",
    "competition.updated": "edit_competition",
    "competition.archived": "edit_competition",
    "competition.unarchived": "edit_competition",
    "competition.deleted": "delete_competition",
    "competition.started": "edit_competition",
    "competition.ended": "edit_competition",
    "competition.time_remaining": "edit_competition",
    "module.enabled": "edit_competition",
    "module.disabled": "edit_competition",
    "ticket.created": "ticket_view",
    "ticket.assigned": "ticket_view",
    "ticket.resolved": "ticket_view",
    "ticket.message_posted": "ticket_view",
    "ticket.attachment_added": "ticket_view",
    "ticket.attachment_deleted": "ticket_view",
    "survey.submitted": "feedback_view_responses",
    # Certificate authoring is staff; release is member-visible (participants get
    # a certificate), so it maps to the baseline a Participant holds.
    "certificate.template_updated": "manage_certificates",
    "certificate.released": "challenge_view",
    # Challenge authoring (draft/edit) is staff; play events are member-visible.
    "challenge.created": "challenge_edit",
    "challenge.updated": "challenge_edit",
    "challenge.deleted": "challenge_edit",
    "challenge.guesses_reset": "challenge_edit",
    "category.created": "challenge_edit",
    "category.deleted": "challenge_edit",
    # Others' attempts (incl. failures) are staff analytics data, not
    # member-visible play state — same gate as reading the analytics page.
    "challenge.attempted": "view_competition_analytics",
    # Member-visible events (published challenges, solves, scoreboard-facing).
    "challenge.published": "challenge_view",
    "challenge.solved": "challenge_view",
    "challenge.rated": "feedback_view_responses",
    "challenge.hint_requested": "challenge_view",
    "hint.released": "challenge_view",
    "hint.published": "challenge_view",
    "score.adjusted": "challenge_view",
    "achievement.awarded": "challenge_view",
    "scoreboard.frozen": "scoreboard_freeze",
    "scoreboard.unfrozen": "scoreboard_freeze",
    "announcement.published": "challenge_view",
    "survey.opened": "challenge_view",
    "competition.member_joined": "challenge_view",
    # Same visibility tier as member_joined — a join-adjacent membership event.
    "competition.rules_accepted": "challenge_view",
    "team.created": "challenge_view",
    "team.member_joined": "challenge_view",
    "team.member_left": "challenge_view",
    "team.deleted": "challenge_view",
}


def required_permission(event: str) -> str:
    """The permission gating a rule's use of ``event`` as a trigger (§5.1).
    Falls back to the strictest global admin permission for any unmapped event
    (fail-closed) — but the drift test keeps the map complete."""
    return TRIGGER_PERMISSIONS.get(event, "manage_roles")


# Human labels for trigger payload fields, so the condition builder shows
# "Minutes remaining" / "First blood" instead of the raw key (§5.5). Anything
# unmapped falls back to a humanized key (see `_field_label`), so a newly-added
# trigger field is never surfaced as a bare `snake_case` key.
_FIELD_LABELS: dict[str, str] = {
    # Entity ids → the entity's human name (the id itself stays internal).
    "competition_id": "Competition",
    "challenge_id": "Challenge",
    "user_id": "User",
    "team_id": "Team",
    "hint_id": "Hint",
    "survey_id": "Survey",
    "ticket_id": "Ticket",
    "announcement_id": "Announcement",
    "response_id": "Response",
    "message_id": "Message",
    "attachment_id": "Attachment",
    "api_token_id": "API token",
    "provider_id": "Provider",
    "certificate_template_id": "Certificate",
    # Role-qualified actor ids.
    "actor_user_id": "Actor",
    "opener_user_id": "Opener",
    "assignee_user_id": "Assignee",
    "author_user_id": "Author",
    "created_by_user_id": "Created by",
    # Scalars.
    "points": "Points",
    "cost": "Cost",
    "rating": "Rating",
    "minutes_remaining": "Minutes remaining",
    "is_first_blood": "First blood",
    "correct": "Correct",
    "is_internal": "Internal",
    "auto": "Automatic",
    "frozen_at": "Frozen at",
    "severity": "Severity",
    "audience_type": "Audience",
    "changed_fields": "Changed fields",
    "roles_assigned": "Roles assigned",
    # Friendly companion placeholders (#27) appended by `_with_friendly`.
    "user_name": "User name",
    "team_name": "Team name",
    "challenge_title": "Challenge title",
    "survey_title": "Survey title",
    "ticket_subject": "Ticket subject",
    "competition_name": "Competition name",
}

# Which entity an id-shaped payload field points at, so a *condition value* on
# that field is chosen from a name dropdown instead of typed as a raw id (§9,
# "ids are internal"). Only types with a scoped list hook on the frontend are
# mapped; the rest stay plain inputs. Keyed on the payload field name.
_FIELD_ENTITY_TYPES: dict[str, str] = {
    "competition_id": "competition",
    "challenge_id": "challenge",
    "survey_id": "survey",
    "hint_id": "hint",
    "team_id": "team",
    "user_id": "user",
    "opener_user_id": "user",
    "assignee_user_id": "user",
    "author_user_id": "user",
    "actor_user_id": "user",
    "created_by_user_id": "user",
}

_OPERATOR_LABELS = {
    "equals": "equals",
    "not_equals": "does not equal",
    "contains": "contains",
    "gt": "is greater than",
    "gte": "is at least",
    "lt": "is less than",
    "lte": "is at most",
    "exists": "is present",
    "not_exists": "is absent",
}
_UNARY_OPERATORS = frozenset({"exists", "not_exists"})


def _field(
    key: str,
    label: str,
    kind: str = "text",
    *,
    required: bool = True,
    options: list[str] | None = None,
    placeholder: str | None = None,
    templateable: bool = False,
    entity_type: str | None = None,
) -> dict:
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "required": required,
        "options": options,
        "placeholder": placeholder,
        "templateable": templateable,
        # For kind="entity": which entity this id references, so the builder
        # renders a name-search dropdown (never a raw id box). The picker maps
        # the type to its list hook + scope on the frontend.
        "entity_type": entity_type,
    }


# Config fields per action type — mirrors the schemas/automation.py models
# (drift-guarded by test). ``templateable`` marks a value that supports
# {field} interpolation from the event payload.
ACTION_FIELDS: dict[str, list[dict]] = {
    "notify": [
        _field(
            "target", "Notify", "select",
            options=["event_user", "event_team", "role", "self"],
        ),
        _field(
            "role_name", "Role name", required=False, placeholder="e.g. Judge",
        ),
        _field(
            "title", "Title", templateable=True,
            placeholder="Solved {challenge_id}!",
        ),
        _field("body", "Body", "textarea", required=False, templateable=True),
    ],
    "send_email": [
        _field("to", "Recipients", "string_list", placeholder="ops@example.com"),
        _field("subject", "Subject", templateable=True),
        _field("body", "Body", "textarea", templateable=True),
    ],
    "webhook": [
        _field("url", "URL", placeholder="https://hooks.example.com/…"),
        _field(
            "content_type", "Content type", "select", required=False,
            options=[
                "application/json",
                "application/x-www-form-urlencoded",
                "text/plain",
            ],
        ),
        _field("headers", "Headers", "keyvalue", required=False),
        _field(
            "body_template", "Body template", "textarea", required=False,
            templateable=True, placeholder='{"text":"Solved {challenge_id}"}',
        ),
    ],
    "release_hint": [_field("hint_id", "Hint", "entity", entity_type="hint")],
    "publish_hint": [_field("hint_id", "Hint", "entity", entity_type="hint")],
    "unlock_challenge": [
        _field("challenge_id", "Challenge", "entity", entity_type="challenge"),
    ],
    "open_survey": [_field("survey_id", "Survey", "entity", entity_type="survey")],
    "create_ticket": [
        _field("subject", "Subject", templateable=True),
        _field("body", "Body", "textarea", templateable=True),
    ],
    "update_score": [
        _field("points", "Points", "number", placeholder="e.g. 50 or -25"),
        _field("reason", "Reason", templateable=True),
    ],
    "create_award": [
        _field("title", "Title", templateable=True),
        _field("description", "Description", "textarea", required=False, templateable=True),
        _field("points", "Points", "number", required=False, placeholder="e.g. 100"),
    ],
    "freeze_scoreboard": [],
    "unfreeze_scoreboard": [],
    "create_announcement": [
        _field("title", "Title", templateable=True),
        _field("body", "Body", "textarea", templateable=True),
        _field(
            "severity", "Severity", "select", required=False,
            options=list(SEVERITIES),
        ),
    ],
}


def _titleize(event_or_type: str) -> str:
    return " ".join(event_or_type.replace(".", " ").replace("_", " ").split()).capitalize()


def _field_label(key: str) -> str:
    """Human label for a trigger payload field. Curated where it matters,
    otherwise a humanized key (dropping a trailing ``_id``) so the builder never
    shows a raw `snake_case` key."""
    if key in _FIELD_LABELS:
        return _FIELD_LABELS[key]
    base = key[:-3] if key.endswith("_id") else key
    return _titleize(base)


def _with_friendly(fields: list[str]) -> list[str]:
    """Append the resolved friendly companions (#27) for every id field a
    trigger carries — {user_name}, {challenge_title}, … — so the builder
    suggests the human-readable placeholder alongside the raw id. The engine
    resolves them at rule-run time (utils.automation_actions.enrich_payload)."""
    return fields + [
        FRIENDLY_FIELDS[f][0] for f in fields if f in FRIENDLY_FIELDS
    ]


def build_catalog() -> dict:
    """The full editor catalog (§5.5) as plain dicts for the response model."""
    return {
        "triggers": [
            {
                "event": event,
                "label": _titleize(event),
                "fields": [
                    {
                        "key": key,
                        "label": _field_label(key),
                        "entity_type": _FIELD_ENTITY_TYPES.get(key),
                    }
                    for key in _with_friendly(TRIGGER_FIELDS.get(event, _COMMON_FIELDS))
                ],
            }
            for event in TRIGGERABLE_EVENTS
        ],
        "operators": [
            {
                "value": operator,
                "label": _OPERATOR_LABELS.get(operator, operator),
                "unary": operator in _UNARY_OPERATORS,
            }
            for operator in CONDITION_OPERATORS
        ],
        "actions": [
            {
                "type": action_type,
                "label": _titleize(action_type),
                "personal_allowed": ACTIONS[action_type].personal_allowed,
                "fields": ACTION_FIELDS.get(action_type, []),
            }
            for action_type in sorted(ACTIONS)
            # Demo instances hide the outbound/abusable actions (also enforced at
            # execution time) so the builder never offers them.
            if not (settings.demo_mode and action_type in DEMO_DISABLED_ACTIONS)
        ],
    }
