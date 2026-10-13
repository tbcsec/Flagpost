// The product changelog rendered at /changelog — bundled static data, not a
// runtime GitHub fetch: deployments can be air-gapped and nothing phones home
// (PRIVACY.md). Each entry links out to its GitHub release for the full notes.
//
// Entries are **release data, not UI chrome** (the ADR-0029 line the automation
// catalog and vocab lists follow), so the text stays literal English; only the
// page's chrome is translated. Newest first.
//
// Cutting a release: add the new version here (CONTRIBUTING → "Cutting a
// release") before tagging, so the tagged build ships its own history.

const RELEASES_URL = "https://github.com/tbcsec/Flagpost/releases/tag";

export interface ChangelogEntry {
  version: string; // tag, e.g. "v1.6.0"
  date: string; // ISO date of the release
  title: string;
  highlights: string[];
  url: string;
}

function entry(
  version: string,
  date: string,
  title: string,
  highlights: string[],
): ChangelogEntry {
  return { version, date, title, highlights, url: `${RELEASES_URL}/${version}` };
}

export const CHANGELOG: ChangelogEntry[] = [
  entry("v1.7.0", "2026-10-13", "Module SDK & marketplace, cross-competition skills, challenge sharing", [
    "Module SDK & marketplace: import content packs (challenges, themes) from an open, mirrorable registry over a signed, trust-tiered protocol — code-based resolve → confirm → signature/digest verification → install, an admin import + settings UI, and an authoring SDK (build, sign, validate, scaffold).",
    "Cross-competition skills web: competitors get a personal skills radar and at-a-glance stats across every event they play; organisers get a users × skills matrix with difficulty-weighted scores, coverage, a percentile heat-map, efficiency and first-blood signals, activity windows, a per-user drill-down, and CSV export.",
    "Challenge sharing: shareable invite and view links for a competition — revocable, expiring, use-capped — with a public landing page that walks recipients from link to sign-in to joined.",
    "RustFS replaces MinIO as the default object store, with vendor-neutral S3_* configuration (see the upgrade notes).",
    "An in-app changelog at /changelog, linked from the footer.",
    "A broad security-hardening pass across authentication, SSO, real-time, automations, webhooks, challenge instancing, import/export and the gameplay gates.",
  ]),
  entry("v1.6.0", "2026-08-31", "On-demand challenge instances, brand themes, dashboard breadth & observability", [
    "On-demand challenge instances: each team or player gets their own isolated, running copy of a service — Docker and Kubernetes provisioner backends, TTL reaping, TCP and HTTP exposure with per-instance subdomains (optional module).",
    "Organisation brand themes: admin-authored full design-token packs alongside the built-in palettes.",
    "A more customisable manager dashboard.",
    "First-class observability for operators.",
  ]),
  entry("v1.5.1", "2026-08-26", "Relicensed to Apache 2.0", [
    "The entire platform — backend, frontend, documentation and published images — now ships under the Apache License 2.0 (releases up to v1.5.0 remain available under AGPL-3.0).",
    "The Flagpost Module Exception is retired: third-party modules can carry any license.",
  ]),
  entry("v1.5.0", "2026-08-24", "Internationalization, external-auth breadth, certificates & reports", [
    "The whole web UI is translatable, with French, Spanish and Polish live and a language picker in the topbar.",
    "External authentication breadth: built-in provider presets and admission-policy polish.",
    "Participation certificates: designed per competition and released to competitors.",
    "Post-event reports for organisers.",
  ]),
  entry("v1.4.0", "2026-08-13", "AI assistants, scoreboard scale-out & multi-worker scaling", [
    "Optional AI assistants module: an administrator assistant and an audience-aware competitor assistant over an operator-configured provider — off by default, nothing is sent anywhere until enabled.",
    "Scoreboard scale-out: a cached read model plus delta/top-N broadcasts replacing per-solve refetch storms.",
    "Opt-in multi-worker deployments with a cross-worker realtime relay.",
    "A round of automation and authoring polish.",
  ]),
  entry("v1.3.0", "2026-08-04", "SAML & LDAP sign-in, encrypted secrets & venue mode", [
    "SAML 2.0 identity providers (SP-initiated, signature-before-trust).",
    "LDAP / Active Directory sign-in, with local login preserved as break-glass.",
    "Per-provider trust posture (open/closed) for external identities.",
    "Stored secrets encrypted at rest.",
    "Venue mode: a public activity display for on-site events.",
  ]),
  entry("v1.2.0", "2026-08-01", "SSO, self-service accounts & a security release", [
    "OIDC single sign-on on a reusable identity-provider framework.",
    "Self-service accounts: password reset, email change and verification.",
    "Seven security fixes, four tracked as GitHub Security Advisories — upgrading strongly recommended.",
    "Staff tooling improvements.",
  ]),
  entry("v1.1.1", "2026-07-26", "Versioned images & compose fix", [
    "Version-pinned container images on GHCR, built in same-origin mode so one image works behind any proxy.",
    "Fix: a fresh compose deployment no longer crash-loops when DEMO_MODE is unset.",
  ]),
  entry("v1.1.0", "2026-07-26", "Live updates, targeted announcements & more", [
    "Live updates across the site: dashboards, challenge cards, rosters and analytics move in real time.",
    "Expanded announcements: urgency levels, audience targeting, bell notifications.",
    "Public spectator insights: stat tiles, highlights and a points-over-time timeline.",
    "Judge analytics cards, archived-competition retention, and a personal challenge scratchpad for solo competitors.",
  ]),
  entry("v1.0.0", "2026-07-25", "Initial public release", [
    "Competitions in individual or team mode — visibility, scheduling, pause, archive and cloning.",
    "Challenges with static, regex, multiple-choice and dynamic-decay flags, hints, prerequisites, and ctfcli YAML import/export.",
    "Live WebSocket scoreboard with freeze, brackets, a public spectator board and a CTFtime feed.",
    "Collaborative CRDT notes, announcements, a notification centre and presence.",
    "Role-based access control, a visual automation engine, support tickets, audit log, and full export/import backup.",
  ]),
];
