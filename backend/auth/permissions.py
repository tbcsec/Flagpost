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

``reserved`` marks a permission that is defined ahead of the feature enforcing
it (so role editors can see it coming); nothing carries it today — the
automations keys shed it when the engine shipped (Tier 3 Phase 1).
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
    reserved: bool = False  # defined ahead of the feature that enforces it


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
    # Feedback (§5-adjacent, ROADMAP #22) — post-competition surveys.
    Permission("feedback_manage", "Feedback", Scope.COMPETITION),
    Permission("feedback_view_responses", "Feedback", Scope.COMPETITION),
    Permission("feedback_submit", "Feedback", Scope.COMPETITION),
    # Users & Roles
    Permission("manage_users", "Users & Roles", Scope.GLOBAL),
    Permission("manage_roles", "Users & Roles", Scope.GLOBAL),
    Permission("view_all_users", "Users & Roles", Scope.GLOBAL),
    # Oversight of personal API tokens (issue #75): list every token on the
    # platform and revoke any of them, so a leaked credential can be killed by
    # someone other than its holder. Deliberately NOT an issuance grant —
    # minting is self-only (routers/api_tokens.py), so this permission can never
    # become a route to acting as another account. Holders manage their own
    # tokens from /profile without it.
    Permission("manage_api_tokens", "Users & Roles", Scope.GLOBAL),
    # Site Settings — the site-wide theme/branding an administrator sets for the
    # whole install (§9, site-wide theming). Global-scoped, Administrator-only.
    Permission("manage_site_settings", "Site Settings", Scope.GLOBAL),
    # External identity providers (#58, ADR-0021). Deliberately its own grant
    # rather than folded into manage_site_settings: this surface decides who can
    # log in at all, so a misconfiguration or a compromise here is materially
    # worse than changing a palette or an SMTP host.
    Permission("manage_auth_providers", "Site Settings", Scope.GLOBAL),
    # AI assistants provider config (#98, ADR-0023). Its own grant for the same
    # reason as auth providers: this surface holds an API key and enables outbound
    # calls to an operator-chosen endpoint (a data-processing relationship), so
    # it's a higher-stakes control than a palette or SMTP host.
    Permission("manage_ai", "Site Settings", Scope.GLOBAL),
    # Reading competitor-assistant conversation transcripts (#98, ADR-0023 Phase
    # 3) — the oversight lens on a hint channel. Competition-scoped and its own
    # grant: transcripts are competitor content of a different sensitivity than
    # analytics or tickets, so a Judge holds it for their competition without it
    # riding on view_competition_analytics.
    Permission("ai_view_transcripts", "AI Assistants", Scope.COMPETITION),
    # Analytics
    Permission(
        "view_competition_analytics", "Analytics", Scope.COMPETITION
    ),
    Permission("view_global_analytics", "Analytics", Scope.GLOBAL),
    # Raw submission payloads are more sensitive than aggregate stats (ROADMAP
    # #76 submissions browser), so it's a separate grant Judge/Admin hold by
    # default rather than folded into view_competition_analytics.
    Permission("view_submissions", "Analytics", Scope.COMPETITION),
    # Dashboard
    Permission("customize_dashboard", "Dashboard", Scope.COMPETITION),
    Permission("manage_dashboard_widgets", "Dashboard", Scope.COMPETITION),
    # Automations — enforced since the engine shipped (Tier 3 Phase 1, §5).
    # Personal rules (§5.1) deliberately need none of these; a global rule
    # requires holding create/edit via a *global* assignment (§5.1).
    Permission("automation_view", "Automations", Scope.COMPETITION),
    Permission("automation_create", "Automations", Scope.COMPETITION),
    Permission("automation_edit", "Automations", Scope.COMPETITION),
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
    # Feedback (ROADMAP #22): a Judge builds surveys and reads results, and can
    # answer one too.
    "feedback_manage",
    "feedback_view_responses",
    "feedback_submit",
    "view_competition_analytics",
    "view_submissions",
    # Review competitor-assistant transcripts in their competition (#98).
    "ai_view_transcripts",
    "customize_dashboard",
    # Automations (§5): a Judge runs their competition's rules — "full
    # operational control" (§7.3). Reaches existing installs via the startup
    # role re-sync (seed_system_roles).
    "automation_view",
    "automation_create",
    "automation_edit",
]

# Participant: competitor-facing only — view challenges, view the scoreboard,
# create/answer their own tickets. (Flag submission and team self-management
# are enforced by ownership, not a catalog permission.)
PARTICIPANT_PERMISSIONS: list[str] = [
    "challenge_view",
    "ticket_view",
    "ticket_respond",
    # Answer a post-competition survey (ROADMAP #22).
    "feedback_submit",
]
