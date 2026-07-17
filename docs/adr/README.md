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
