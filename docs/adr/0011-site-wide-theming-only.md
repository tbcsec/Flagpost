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

## Amendment: custom brand themes (2026-08-28, #323)

Site-wide theming gained a **custom theme** axis alongside the built-in palette
and accent: an administrator can author or upload a **complete pack of the
design tokens** (the same CSS variables the built-in palettes set), stored as
`theme_presets` rows and injected onto `<html>` at runtime — generalising the
existing custom-accent-hex path from one colour to the full token set.

This does **not** change the scope decision above:

- Still **site-wide, admin-only.** A preset is selected as the site's
  `default_palette` (its id may now name a preset or a built-in). The per-user
  override and per-scope token mechanism (§9) are unchanged.
- **Additive, not a rewrite.** No `Competition.theme` column; presets are
  site-level rows. Per-competition / white-label theming remains deferred and
  would build on this (a preset is exactly the shape a scoped theme would need).

Two boundaries make it safe and consistent, and are the reason to keep it:

- **Token pack only** — colours (`#RRGGBB`) for a fixed allowlist of tokens,
  plus a `dark`/`light` mode. **Not** arbitrary CSS/JS/fonts/markup: the
  validator constrains keys and values so the map can't carry CSS control
  characters, so injecting it as inline `--token` styles has no injection
  surface. Arbitrary CSS/JS was explicitly rejected (CSP/exfil/UI-redress risk,
  and a poor fit for a compiled front end).
- **Layout is fixed** — themes recolour; they don't move or restyle components.

See `docs/THEMING.md` for the theme-file format and token reference.
