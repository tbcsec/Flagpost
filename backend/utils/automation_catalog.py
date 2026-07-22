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

from utils.automation_actions import ACTIONS
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
    "challenge.hint_requested": [
        "competition_id", "challenge_id", "hint_id", "user_id", "team_id", "cost",
    ],
    "hint.released": [
        "competition_id", "challenge_id", "hint_id", "user_id", "team_id",
    ],
    "ticket.created": ["competition_id", "ticket_id", "opener_user_id", "subject"],
    "ticket.assigned": ["competition_id", "ticket_id", "assignee_user_id"],
    "ticket.resolved": ["competition_id", "ticket_id"],
    "ticket.message_posted": [
        "competition_id", "ticket_id", "author_user_id", "is_internal",
    ],
    "score.adjusted": [
        "competition_id", "user_id", "team_id", "points", "reason",
    ],
    "achievement.awarded": ["competition_id", "user_id", "team_id", "name"],
    "competition.member_joined": ["competition_id", "user_id"],
    "competition.time_remaining": ["competition_id", "minutes_remaining"],
    "team.created": ["competition_id", "team_id"],
    "team.member_joined": ["competition_id", "team_id", "user_id"],
    "announcement.published": ["competition_id"],
    "feedback.submitted": ["competition_id", "user_id", "survey_id", "response_id"],
    "survey.opened": ["competition_id", "survey_id", "title"],
    "user.registered": ["user_id"],
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
    "site.settings_updated": "manage_site_settings",
    # Competition-lifecycle / staff events.
    "competition.created": "edit_competition",
    "competition.updated": "edit_competition",
    "competition.started": "edit_competition",
    "competition.ended": "edit_competition",
    "competition.time_remaining": "edit_competition",
    "module.enabled": "edit_competition",
    "module.disabled": "edit_competition",
    "ticket.created": "ticket_view",
    "ticket.assigned": "ticket_view",
    "ticket.resolved": "ticket_view",
    "ticket.message_posted": "ticket_view",
    "feedback.submitted": "feedback_view_responses",
    # Challenge authoring (draft/edit) is staff; play events are member-visible.
    "challenge.created": "challenge_edit",
    "challenge.updated": "challenge_edit",
    "challenge.deleted": "challenge_edit",
    "category.created": "challenge_edit",
    "category.deleted": "challenge_edit",
    # Member-visible events (published challenges, solves, scoreboard-facing).
    "challenge.published": "challenge_view",
    "challenge.solved": "challenge_view",
    "challenge.hint_requested": "challenge_view",
    "hint.released": "challenge_view",
    "score.adjusted": "challenge_view",
    "achievement.awarded": "challenge_view",
    "announcement.published": "challenge_view",
    "survey.opened": "challenge_view",
    "competition.member_joined": "challenge_view",
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
) -> dict:
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "required": required,
        "options": options,
        "placeholder": placeholder,
        "templateable": templateable,
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
    "release_hint": [_field("hint_id", "Hint ID")],
    "unlock_challenge": [_field("challenge_id", "Challenge ID")],
    "open_survey": [_field("survey_id", "Survey ID")],
    "create_ticket": [
        _field("subject", "Subject", templateable=True),
        _field("body", "Body", "textarea", templateable=True),
    ],
    "update_score": [
        _field("points", "Points", "number", placeholder="e.g. 50 or -25"),
        _field("reason", "Reason", templateable=True),
    ],
    "award_achievement": [
        _field("name", "Name", templateable=True),
        _field("description", "Description", "textarea", required=False, templateable=True),
    ],
}


def _titleize(event_or_type: str) -> str:
    return " ".join(event_or_type.replace(".", " ").replace("_", " ").split()).capitalize()


def build_catalog() -> dict:
    """The full editor catalog (§5.5) as plain dicts for the response model."""
    return {
        "triggers": [
            {
                "event": event,
                "label": _titleize(event),
                "fields": TRIGGER_FIELDS.get(event, _COMMON_FIELDS),
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
        ],
    }
