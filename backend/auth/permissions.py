"""The permission catalog (ARCHITECTURE.md §7.1).

Permissions are granular, named, categorized capability strings — not baked
into role-check logic (ADR-0004). Each has a ``scope``:

- ``global``     — site-wide, evaluated against no particular competition
                   (creating a competition, managing users).
- ``competition``— meaningful only within one competition (editing a
                   challenge, responding to a ticket).

``category`` exists purely to group the admin UI into sections (§7.1); it has
no enforcement meaning. Roles store a list of these keys (§7.2); enforcement
resolves a key against the acting role's set in ``require_permission`` (§7.6).

Adding a permission here is the *only* place a new capability is introduced —
`require_permission("x")` referencing a key absent from this catalog is a bug,
guarded by a test (see tests/test_permissions.py, per ADR-0004).

Automations permissions are listed but marked reserved: the automation engine
is deferred (ROADMAP "Explicitly Deferred"), so nothing enforces them yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Scope(str, Enum):
    GLOBAL = "global"
    COMPETITION = "competition"


@dataclass(frozen=True)
class Permission:
    key: str
    category: str
    scope: Scope
    reserved: bool = False  # defined but not yet enforced (automation engine)


# Ordered by the §7.1 categories. Keys are the source of truth referenced by
# require_permission() and by seeded role permission-sets.
PERMISSIONS: tuple[Permission, ...] = (
    # Competition Management
    Permission("create_competition", "Competition Management", Scope.GLOBAL),
    Permission("edit_competition", "Competition Management", Scope.COMPETITION),
    Permission("delete_competition", "Competition Management", Scope.COMPETITION),
    Permission("manage_schedule", "Competition Management", Scope.COMPETITION),
    # Challenges
    Permission("challenge_view", "Challenges", Scope.COMPETITION),
    Permission("challenge_create", "Challenges", Scope.COMPETITION),
    Permission("challenge_edit", "Challenges", Scope.COMPETITION),
    Permission("challenge_delete", "Challenges", Scope.COMPETITION),
    Permission("challenge_publish", "Challenges", Scope.COMPETITION),
    # Scoring
    Permission("score_override", "Scoring", Scope.COMPETITION),
    Permission("scoreboard_freeze", "Scoring", Scope.COMPETITION),
    # Teams
    Permission("team_view_all", "Teams", Scope.COMPETITION),
    Permission("team_edit_any", "Teams", Scope.COMPETITION),
    Permission("team_disqualify", "Teams", Scope.COMPETITION),
    # Support Tickets
    Permission("ticket_view", "Support Tickets", Scope.COMPETITION),
    Permission("ticket_respond", "Support Tickets", Scope.COMPETITION),
    Permission("ticket_assign", "Support Tickets", Scope.COMPETITION),
    Permission(
        "ticket_view_internal_notes", "Support Tickets", Scope.COMPETITION
    ),
    # Announcements
    Permission("announcement_create", "Announcements", Scope.COMPETITION),
    Permission("announcement_delete", "Announcements", Scope.COMPETITION),
    # Users & Roles
    Permission("manage_users", "Users & Roles", Scope.GLOBAL),
    Permission("manage_roles", "Users & Roles", Scope.GLOBAL),
    Permission("view_all_users", "Users & Roles", Scope.GLOBAL),
    # Site Settings — the site-wide theme/branding an administrator sets for the
    # whole install (§9, site-wide theming). Global-scoped, Administrator-only.
    Permission("manage_site_settings", "Site Settings", Scope.GLOBAL),
    # Analytics
    Permission(
        "view_competition_analytics", "Analytics", Scope.COMPETITION
    ),
    Permission("view_global_analytics", "Analytics", Scope.GLOBAL),
    # Dashboard
    Permission("customize_dashboard", "Dashboard", Scope.COMPETITION),
    Permission("manage_dashboard_widgets", "Dashboard", Scope.COMPETITION),
    # Automations (reserved — not enforced until the engine ships, §7.1)
    Permission("automation_view", "Automations", Scope.COMPETITION, reserved=True),
    Permission(
        "automation_create", "Automations", Scope.COMPETITION, reserved=True
    ),
    Permission(
        "automation_edit", "Automations", Scope.COMPETITION, reserved=True
    ),
    # Audit — reading the cross-competition event log (§3.3). Site oversight, so
    # global-scoped and Administrator-only among the built-in roles.
    Permission("view_audit_log", "Audit", Scope.GLOBAL),
)

PERMISSIONS_BY_KEY: dict[str, Permission] = {p.key: p for p in PERMISSIONS}
ALL_PERMISSION_KEYS: frozenset[str] = frozenset(PERMISSIONS_BY_KEY)


def scope_of(key: str) -> Scope:
    return PERMISSIONS_BY_KEY[key].scope


def is_known(key: str) -> bool:
    return key in PERMISSIONS_BY_KEY


# --- Built-in role permission sets (§7.3) -----------------------------------
# Seeded at migration time. Administrator gets everything (including reserved
# keys, harmless until enforced); Judge/Participant get curated subsets.

ADMINISTRATOR_PERMISSIONS: list[str] = [p.key for p in PERMISSIONS]

# Judge: full operational control within an assigned competition — challenges,
# scoring, tickets, announcements, analytics. No user/role management.
JUDGE_PERMISSIONS: list[str] = [
    "edit_competition",
    "manage_schedule",
    "challenge_view",
    "challenge_create",
    "challenge_edit",
    "challenge_delete",
    "challenge_publish",
    "score_override",
    "scoreboard_freeze",
    "team_view_all",
    "team_edit_any",
    "team_disqualify",
    "ticket_view",
    "ticket_respond",
    "ticket_assign",
    "ticket_view_internal_notes",
    "announcement_create",
    "announcement_delete",
    "view_competition_analytics",
    "customize_dashboard",
]

# Participant: competitor-facing only — view challenges, view the scoreboard,
# create/answer their own tickets. (Flag submission and team self-management
# are enforced by ownership, not a catalog permission.)
PARTICIPANT_PERMISSIONS: list[str] = [
    "challenge_view",
    "ticket_view",
    "ticket_respond",
]
