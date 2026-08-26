# ADR-0035: Relicense from AGPL-3.0 to Apache 2.0

**Status:** Accepted
**Date:** 2026-08-25

## Context

Flagpost shipped v1.0.0 under AGPL-3.0, later adding the Flagpost Module
Exception (an AGPL §7 additional permission) so third-party modules could
carry their own licenses. The copyleft choice protected a possible future
hosted offering: AGPL §13 obliges anyone running a *modified* Flagpost as a
network service to offer its source.

In practice the license was costing the project its primary audience. A large
share of the target base — security and training teams at larger companies —
operates under corporate open-source policies that ban AGPL categorically,
regardless of the fact that self-hosting an unmodified copy carries almost no
obligations. Evaluation ends at the license line before features are seen, and
the actual posture was worse than plain AGPL: "AGPL plus a bespoke exception"
is two instruments for a corporate lawyer to review instead of a standard one.
The most direct open-source comparison, CTFd, is Apache-2.0 — so a shortlist
comparison was a strict licensing disadvantage.

The options actually considered:

- **Stay AGPL-3.0 (+ exception)** — keeps the strongest SaaS defence, keeps
  losing the enterprise segment.
- **Apache 2.0** — permissive, OSI-approved, explicit patent grant and
  patent-litigation termination (§3), trademark carve-out (§6). The standard
  "enterprise-safe" choice; also what CTFd uses, and CTFd has run a paid
  hosted offering on it for years.
- **MIT/BSD** — equally permissive but without the explicit patent language
  that enterprise review looks for.
- **BSL/FSL-style source-available** — protects a hosted business but is not
  open source, is itself blanket-banned by many of the same corporate
  policies, and would defeat the adoption goal outright.
- **Dual licensing (AGPL + commercial)** — keeps the AGPL scare at evaluation
  time and adds CLA overhead.

Feasibility was checked before deciding: the repository is effectively
sole-author (all human commits are the copyright holder's identities;
Dependabot's version bumps are not copyrightable), so no third-party consent
was required.

## Decision

From v1.5.1, Flagpost is licensed under the Apache License 2.0. The Flagpost
Module Exception is retired — under a permissive license, modules need no
additional permission to carry their own terms. Releases up to and including
v1.5.0 were published under AGPL-3.0 and remain available on those terms.

## Consequences

- **Easier:** enterprise adoption — plain, unmodified Apache-2.0 passes
  corporate open-source review without legal escalation, and the custom
  exception (one more thing to review) disappears. Third-party module
  licensing becomes trivially simple.
- **Harder:** there is no longer a copyleft lever against someone offering
  hosted Flagpost commercially. The protection for a future hosted offering
  is now the trademark (Apache-2.0 §6 explicitly withholds it) plus the
  operational moat, not the code. Judged acceptable: the code was never the
  moat for event tooling, and the closest comparable has run this exact model
  successfully.
- **Foreclosed (practically):** reversing course. Future versions could be
  relicensed again, but every Apache-licensed release remains forkable
  forever, and tightening later reliably provokes forks. The decision is made
  as if permanent.
- Contributions are accepted inbound=outbound under Apache-2.0 §5
  (CONTRIBUTING.md); no CLA is introduced.
