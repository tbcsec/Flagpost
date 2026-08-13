# Architecture Decision Records

This directory records significant architectural decisions: what was
decided, why, and what it costs. It's not a changelog and not a design
doc — `ARCHITECTURE.md` is where the full reasoning and current state
live. An ADR is a short, dated snapshot of *why a decision was made*,
kept even after the decision is superseded, so nobody has to re-litigate
a settled question without knowing why it was settled that way the first
time.

## When to write one

Write an ADR when a decision is hard to reverse, affects more than one
module, or was genuinely contested (more than one reasonable option
existed and a real tradeoff was made). Don't write one for anything
`ARCHITECTURE.md` already documents as a default pattern with no real
alternative considered — one-hook-per-domain, for example, doesn't need
an ADR; it's just the convention.

## Numbering and status

Files are numbered sequentially, zero-padded, never reused:
`0006-short-title.md` follows `0005-*.md` regardless of what happens to
earlier ones. Use `template.md` as the starting point.

Status is one of:

- **Proposed** — under discussion, not yet acted on.
- **Accepted** — the current decision. Code should reflect it.
- **Superseded by ADR-00XX** — no longer current; the record stays for
  history, and the new ADR explains what changed and why.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-app-level-multi-tenancy.md) | App-level multi-competition tenancy, not schema-per-competition | Accepted |
| [0002](0002-kernel-required-core-module-split.md) | Kernel / required-core / optional-module split | Accepted |
| [0003](0003-jwt-access-refresh-auth.md) | JWT access + refresh tokens, shared across REST and WebSocket | Accepted |
| [0004](0004-roles-permissions-as-data.md) | Roles and permissions as data, not a hardcoded enum | Accepted |
| [0005](0005-async-event-bus.md) | Async pub/sub event bus as the core mutation-notification mechanism | Accepted |
| [0006](0006-testing-stack.md) | Testing stack — pytest (backend) + Vitest (frontend) | Accepted |
| [0007](0007-first-user-admin-bootstrap.md) | First registered user becomes the Administrator | Superseded by ADR-0010 |
| [0008](0008-stateful-refresh-sessions.md) | Refresh tokens are stateful, hashed, rotating DB sessions | Accepted |
| [0009](0009-synchronous-event-dispatch-tier0.md) | Event dispatch is synchronous (awaited) in Tier 0 | Superseded by ADR-0012 |
| [0010](0010-seeded-admin-default-credentials.md) | Seed a default administrator with default credentials | Superseded by ADR-0017 |
| [0011](0011-site-wide-theming-only.md) | Site-wide theming only for now (per-competition deferred) | Accepted |
| [0012](0012-event-dispatch-sync-critical-vs-background.md) | Event dispatch splits into sync-critical vs async-background handlers | Accepted |
| [0013](0013-webhook-egress-hardening.md) | Webhook action egress policy — SSRF blocklist + value hardening | Accepted |
| [0014](0014-crdt-transport-and-persistence.md) | CRDT transport as a dumb relay + client-snapshot persistence | Accepted |
| [0015](0015-username-primary-optional-email.md) | Display name is the primary identifier; email is optional | Accepted |
| [0016](0016-platform-export-import.md) | Platform export/import — registry-driven, additive backup | Accepted |
| [0017](0017-first-run-setup-wizard.md) | First-run setup wizard (no seeded default admin) | Accepted |
| [0018](0018-regex-flag-redos-containment.md) | Containing ReDoS in regex flag matching | Accepted |
| [0019](0019-jwt-secret-hardening.md) | Derive a per-install JWT secret instead of a public default | Accepted |
| [0020](0020-secret-storage-encrypt-vs-hash.md) | Hash what is only verified, encrypt what must be retrieved | Accepted |
| [0021](0021-oidc-identity-provider-framework.md) | External identity via OIDC, with local login as break-glass | Accepted |
| [0022](0022-saml-ldap-identity-providers.md) | SAML and LDAP identity providers — generalizing the provider model | Accepted |
| [0023](0023-ai-assistant-provider-and-execution-model.md) | AI assistant provider integration and execution model | Accepted |
| [0024](0024-builtin-sso-provider-presets.md) | Built-in SSO provider presets — configuration, never credentials | Accepted |
| [0025](0025-multi-worker-broadcast-relay.md) | Multi-worker via a Redis broadcast relay behind the connection manager | Accepted |
| [0026](0026-cross-worker-presence.md) | Cross-worker presence via heartbeat-TTL liveness in Redis | Accepted |
| [0027](0027-certificate-rendering-server-side.md) | Certificate rendering — server-side Pillow → PNG, not a headless browser | Proposed |
