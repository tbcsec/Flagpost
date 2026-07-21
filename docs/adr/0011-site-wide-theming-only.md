# ADR-0011: Site-wide theming only for now (per-competition deferred)

**Status:** Accepted
**Date:** 2026-07-21
**Architecture reference:** `ARCHITECTURE.md` §9

## Context

`ARCHITECTURE.md` §9 describes the token layer as supporting a
per-organisation / per-competition accent colour — white-labelling a
single competition instance by writing a scoped CSS-variable override.
ROADMAP #20 ("Basic per-competition theming") was the Tier 2 item to build
that.

Planning Tier 2, the owner reconsidered the scope. Per-competition theming
carries real cost that isn't obviously justified yet: a `theme` field on
`Competition`, a competition-scoped override applied on a wrapping scope
element, an accent picker in competition settings, and the edge cases of
themes interacting with the per-user light/dark preference and the logo
(which must never take a competition's colours, LOGO-SPEC §7). No concrete
demand for per-competition branding exists today; every install so far
wants a single look.

The alternatives were: (a) build per-competition theming as originally
planned; (b) build nothing and keep the shipped default palette; (c) build
**site-wide** theming — one platform theme an administrator sets for the
whole install — using the same token-override mechanism, minus the
per-competition scoping.

## Decision

Build **site-wide theming only** (option c) for now. An administrator sets
one platform theme (default palette + accent, alongside the platform name)
on the Admin → Appearance surface, applied globally by overriding the root
token channels. Per-competition / white-label theming is **deferred**; it
may return in a later tier if concrete demand appears. The token layer's
per-scope override capability (§9) is unchanged — this is a scope decision
about what UI/data we build on top of it, not a change to the mechanism.

## Consequences

- Positive: far less to build and maintain (no `Competition.theme` column,
  no competition-scoped override plumbing, no accent-vs-logo edge cases);
  one clear place to set branding; matches actual demand.
- Negative / cost: an organisation running several competitions on one
  install can't give each its own colours; reintroducing per-competition
  theming later means adding the scoped field + UI then (the token
  mechanism already supports it, so it's additive, not a rewrite).
- Forecloses: nothing permanently — this is "not yet", not "never". The
  §9 mechanism and this ADR both leave the per-competition door open.
