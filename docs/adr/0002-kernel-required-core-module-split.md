# ADR-0002: Kernel / required-core / optional-module split

**Status:** Accepted
**Date:** 2026-07-17
**Architecture reference:** `ARCHITECTURE.md` §11.3

> Refined by ADR-0040 (module SDK, import & marketplace), which defines the
> trust tiers, registry protocol, and install model for the *marketplace*
> modules this ADR anticipates — without changing the kernel / required-core /
> optional split decided here.

## Context

`VISION.md` calls for an Obsidian-inspired plugin ecosystem where most
functionality — including things that ship in the box — is modular. The
first pass at this modeled it as a flat binary: "if disabling it
wouldn't affect a competition, it's a plugin; otherwise it's core." That
rule undersold how much of the platform could actually be built as
modules, but pushing it to its logical extreme (nearly everything is a
disable-able module, including Challenges and Scoring) went too far the
other way — a competition with Challenges disabled isn't a degraded CTF
platform, it isn't a CTF platform.

## Decision

Split the system into three tiers instead of two:

1. **Kernel** — never a module, never disableable: Auth & RBAC, the
   competition entity and tenancy scoping, the event bus, and the module
   loader itself. What every module is built on top of.
2. **Required core** — Challenges, Scoring (and the live scoreboard),
   Hints, Support Tickets, Announcements, and Dashboard customization.
   May be *organized* internally as modules (registered through the same
   manifest-driven path as everything else, for code-organization
   consistency) but carry no enabled/disabled flag in the admin UI. With
   every optional module off, this is what makes the platform a fully
   functional CTF tool, not a shell.
3. **Optional modules** — Feedback, Challenge Lifecycle/Review,
   Analytics, Automations, AI Assistants, and third-party integrations
   (SSO providers, Slack/Discord, CTFtime import/export). Split further
   by trust/provenance (system vs. marketplace), not by capability.

## Consequences

- Positive: nearly everything still goes through one registration
  mechanism (§11.1), which is what makes the module system genuinely
  reusable rather than two parallel code paths (core code vs. plugin
  code) that drift apart over time.
- Positive: the required-core boundary gives a clear, defensible answer
  to "does this need a disable toggle in the admin UI" without a
  case-by-case argument every time a new feature is proposed.
- Negative / cost: the three-tier model is more concepts to hold in mind
  than a flat plugin/core split, and the boundary between "required
  core" and "optional module" is a judgment call that will need
  revisiting as real features get proposed (e.g., is the Challenge
  Lifecycle/Review workflow really optional, or should it move to
  required-core once organisers depend on it day one?).
- Forecloses: treating disable-ability as the *only* signal for what
  counts as a module. Under this model, something can be structurally a
  module and still be mandatory — that's a deliberate design choice, not
  an accident, but it means "is it a module?" no longer answers "can a
  user turn it off?" on its own.
