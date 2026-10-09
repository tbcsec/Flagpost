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
    # Enable/disable optional modules for a competition (#168). Split out of
    # edit_competition so module management can be delegated (or withheld)
    # independently of general competition settings.
    Permission("manage_modules", "Competition Management", Scope.COMPETITION),
    # Generate a post-event report for a finished competition (#134, ADR-0030).
    # Its own competition-scoped grant (like manage_certificates / manage_modules)
    # so report generation can be delegated or withheld independently of general
    # settings. Reaches existing installs via the startup role re-sync.
    Permission("generate_report", "Competition Management", Scope.COMPETITION),
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
    # Certificates (optional module, #219, ADR-0027) — design the per-competition
    # certificate template + configure release. Participants download their own
    # via a self-scoped route (no permission), like API-token minting.
    Permission("manage_certificates", "Certificates", Scope.COMPETITION),
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
    # Authoring custom pages (#198, ADR-0034) — the About/Sponsors/Contact
    # content in the sidebar. Its own grant, and deliberately the *lowest*-stakes
    # one in this category: it's the grant an organiser hands a comms volunteer,
    # so it must not ride on manage_site_settings (which reaches SMTP and
    # branding). That separation only holds because page content can't execute —
    # rendering is React-tree-only, so this is a content grant and not a path to
    # an administrator's session (ADR-0034).
    Permission("manage_pages", "Site Settings", Scope.GLOBAL),
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
    # Challenge instancing (#266, ADR-0036). Site provisioner configuration —
    # its own grant for the same reason as auth providers and AI: it holds
    # infrastructure credentials and points the platform at a container runtime,
    # materially higher-stakes than a palette or SMTP host. Administrator-only
    # among the built-in roles.
    Permission("manage_instance_infra", "Site Settings", Scope.GLOBAL),
    # Launch a per-subject challenge instance (competitor-facing). Held by
    # Participant, but every launch is *additionally* gated server-side by
    # challenge eligibility (published, released, prerequisites met, competition
    # running) — the permission is the floor, not the whole check.
    Permission("instance_launch", "Challenge Instances", Scope.COMPETITION),
    # See every running instance in a competition + resource usage (staff ops).
    Permission("instance_view", "Challenge Instances", Scope.COMPETITION),
    # Kill or extend any subject's instance (staff moderation).
    Permission("instance_manage", "Challenge Instances", Scope.COMPETITION),
    # Marketplace / content packs (#387, ADR-0040). Install a content pack —
    # packaged challenges (into a competition) or brand themes (site-wide) —
    # through the existing importers. Global + Administrator-only among the
    # built-in roles: a pack is a bulk authoring op across the whole install or
    # into a chosen competition, comparable to a platform import, so it sits
    # above the per-competition challenge_create grant rather than folding in.
    Permission("install_content_pack", "Marketplace", Scope.GLOBAL),
    # Configure the marketplace itself (#389, ADR-0040): the registry URL, the
    # trust policy + trusted signing keys, the max installable tier, and the on/off
    # switch. Its own grant — split from install_content_pack and from
    # manage_site_settings for the same reason as manage_ai / manage_auth_providers:
    # trust config decides what code the instance will run, materially higher-stakes
    # than installing an already-trusted pack. Administrator-only among built-ins.
    Permission("manage_marketplace", "Marketplace", Scope.GLOBAL),
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
    "manage_modules",
    # Generate a post-event report for their competition (#134, ADR-0030).
    "generate_report",
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
    # Certificates (#219): a Judge designs and releases their competition's
    # certificate. Reaches existing installs via the startup role re-sync.
    "manage_certificates",
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
    # Challenge instances (#266): a Judge sees and moderates every subject's
    # instance in their competition — "full operational control" (§7.3).
    # Reaches existing installs via the startup role re-sync. Not
    # manage_instance_infra: site provisioner config stays Administrator-only.
    "instance_view",
    "instance_manage",
    # A Judge may also launch (e.g. to test a challenge before publish).
    "instance_launch",
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
    # Launch a per-subject instance of an eligible challenge (#266). The launch
    # route re-checks challenge eligibility and competition status on top of
    # this floor grant.
    "instance_launch",
]
