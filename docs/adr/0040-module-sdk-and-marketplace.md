# ADR-0040: Module SDK, import & marketplace — tiered trust over an open registry protocol

**Status:** Accepted
**Date:** 2026-09-05
**Architecture reference:** `ARCHITECTURE.md` §11 (module system), §15 (the deferred sandbox); refines ADR-0002. Full protocol: `docs/MODULES.md`.

## Context

`VISION.md` calls for an Obsidian-style ecosystem where third parties distribute
modules and content. ADR-0002 built for it — nearly every feature registers
through one manifest-driven path (§11.1), split "by provenance and trust, not by
capability" — and §11.3 already anticipates *marketplace* modules alongside the
in-box *system* ones. But two walls have kept the marketplace on the "Don't build
yet" list:

1. **Untrusted code.** §15's open question — running third-party code safely —
   has no answer yet, and a real isolation story (subprocess/WASM/OCI + a
   capability broker) is a large effort we don't want to gate the whole feature
   on.
2. **A compiled frontend.** The Next.js app is monolithic; nav is hardcoded and
   the manifest's `settings`/`widgets`/`nav_items`/`extensions` fields have always
   been "declared-but-unused". A third party can't ship UI by writing to a folder.

The tension: you cannot ship "a marketplace" without *either* solving untrusted-
code sandboxing *or* finding a trust model that doesn't require it. The options
considered:

- **Wait for the sandbox.** Correct end-state, but it blocks everything —
  content packs and declarative modules, which carry little or no execution risk,
  would wait on the hardest problem in the set.
- **Ship code modules on trust-me.** Install arbitrary third-party code with no
  signature and no consent. Fast, and a security incident waiting to happen.
- **A hosted, proprietary marketplace the platform depends on.** Professional,
  but it makes the open-source core hard-depend on a service, breaks air-gapped
  and government installs, and cuts against the "nothing phones home" posture.

None is acceptable alone. What they miss is that *risk is not uniform across
"modules"*, and that *discovery, authenticity, and entitlement are separable
concerns*.

## Decision

Build the marketplace as a **tiered-trust system over an open, mirrorable
registry protocol**, shipping the low-risk tiers first and *never* requiring the
untrusted-code sandbox to ship. The protocol, schemas, and instance model are
specified in `docs/MODULES.md` and `docs/spec/*.schema.json`; in brief:

- **Four trust tiers** (a property of the artifact, in its manifest): **0**
  content packs (data only), **1** declarative modules (config + server-driven UI,
  no arbitrary code), **2** signed code modules (in-process, trust-on-signature +
  explicit consent), **3** sandboxed untrusted code — **reserved and out of
  scope**, still deferred to a future ADR per §15.
- **An open registry protocol**: a **signed, static, mirrorable catalog index**
  plus **code-based resolution** (`GET {marketplace_url}/resolve/{code}` →
  a confirmation payload). The instance takes a configurable `marketplace_url`
  and a trust policy, so `marketplace.flagpost.io` is the *default* registry, not
  a dependency (the VS Code ↔ Open VSX shape). The hosted service — browse UI,
  publisher accounts, artifact CDN, any commerce/licensing backend — is a
  **separate codebase**, not this repo.
- **Signing is orthogonal to entitlement.** The instance *always* verifies the
  artifact signature + digest + version compatibility (free and paid alike). A
  future *paid* artifact is gated only at **download** by an entitlement verified
  **offline** — no runtime DRM — so paid content still works self-hosted and
  air-gapped.
- **Nothing phones home.** The instance contacts a registry only on explicit
  operator action (resolve / browse / install / update), sending no instance or
  competitor data.
- **Manifest v2** formalises the long-declared `settings`/`widgets`/`nav_items`/
  `extensions` fields and adds `trust_tier`, `capabilities`, `permissions`, and
  compatibility bounds — backwards-compatible with the in-box v1 manifests.

This refines ADR-0002: that ADR split modules by "provenance and trust" but left
*how* a third-party module is discovered, authenticated, consented to, and
installed undefined. The tiers here are that missing definition; they do not
change the kernel / required-core / optional split.

## Consequences

- **Positive:** the feature can ship in usable increments — content packs
  (#387) and declarative modules (#388) deliver a real marketplace with little or
  no execution risk, without waiting on the sandbox. Code modules (#391) get an
  *explicit, signed, consented* trust model instead of an implicit one.
- **Positive:** the open protocol keeps the OSS core free of lock-in and makes
  air-gapped / government installs first-class (mirror the signed catalog, or
  install by file) while still allowing a professional hosted storefront and,
  later, paid content — without a runtime licence check.
- **Positive:** one registration path still covers in-box and marketplace
  modules (ADR-0002 preserved); manifest v2 is additive, so existing required-core
  modules load unchanged.
- **Negative / cost:** more concepts (four tiers, a signing/keystore story, a
  registry protocol, per-module migrations and permissions in #391) and a
  standing signature-verification + trust-policy surface the platform must
  maintain. Per-module migrations and permissions must round-trip cleanly or the
  marketplace slowly corrupts an instance's schema and RBAC.
- **Negative / cost:** "trust-on-signature, in-process" (Tier 2) means a
  *malicious signed* code module still runs with full access — signatures prove
  authorship, not safety. The default trust policy (verified publishers only) and
  `max_trust_tier` cap are the mitigation, not a substitute for the eventual
  sandbox.
- **Forecloses:** treating the marketplace as a single monolithic launch, or as
  a hosted proprietary dependency of the OSS platform. It also commits us to
  *not* solving untrusted-code isolation as part of this milestone — Tier 3 stays
  a deliberate, named gap rather than a hidden assumption that in-process code is
  safe.
