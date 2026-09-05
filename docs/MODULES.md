# Flagpost module & marketplace protocol

> **Spec status: draft.** Normative target for the v1.7.0 flagship
> ([#385](https://github.com/tbcsec/Flagpost/issues/385)) and defined by
> **ADR-0040**. This document is the authoritative written contract; the
> machine-readable schemas live in [`docs/spec/`](spec/) and are the source of
> truth for validation. Where prose and a `*.schema.json` disagree, the schema
> wins and the prose is a bug.

This spec covers the **open, self-hostable platform side** of the module system:
the artifact/manifest formats, the registry protocol an instance speaks, and the
trust model. The hosted discovery/commerce service (`marketplace.flagpost.io` —
browse UI, publisher accounts, artifact CDN, any licensing backend) is a
**separate service** and is out of scope here; it is one *implementation* of the
registry role defined below, and the platform never hard-depends on it.

Related: `ARCHITECTURE.md` §11 (module loader, extension slots, the
kernel/required-core/optional split), ADR-0002 (that split), ADR-0040 (this
work), and the child issues #386–#391.

---

## 1. The tiered trust model

The risk of "a module" is not uniform, so the system is tiered and the low-risk
tiers ship first. A tier is a property of the artifact, declared in its manifest
and echoed in the catalog.

| Tier | Artifact `kind` / `trust_tier` | What it may contain | What establishes trust | Ships |
|------|-------------------------------|---------------------|------------------------|-------|
| **0** | `kind: pack` | Data only — challenges, themes, translations, automation recipes. No executable code. | Signature + it cannot execute. | #387 |
| **1** | `kind: module`, `trust_tier: declarative` | Config + **server-driven UI** via the manifest (`settings`/`widgets`/`nav_items`/`extensions`) and the §11.2 extension slots. No arbitrary backend code. | Signature + the render layer only interprets a validated, declarative description. | #388 |
| **2** | `kind: module`, `trust_tier: code` | Real backend code — routers, listeners, its own tables + permissions. Runs in-process. | **Signature + explicit operator consent** to the requested capabilities. *Not* sandboxed. | #389/#391 |
| **3** | `trust_tier: sandboxed` | Untrusted third-party code. | Isolation (subprocess/WASM/OCI + capability broker). | **Out of scope** — reserved, deferred to a future ADR (`ARCHITECTURE.md` §15). The tiering is deliberately structured so nothing above needs it to ship. |

The tiers form a single ordering used by the instance trust policy (§6):
`pack < declarative < code < sandboxed`.

**Signing is orthogonal to tier.** A signed pack and a signed code module are
verified the same way; the tier governs *what the operator is consenting to run*,
not *whether the bytes are authentic*.

---

## 2. The module artifact

A distributable artifact is a single content-addressed file (proposed extension
`.fpmod`) containing:

- `plugin.yaml` — the **manifest** (§3), and
- the payload: for a `module`, its code/declarative assets; for a `pack`, its
  data (e.g. a ctfcli challenge bundle, a `theme_presets` token pack, locale
  messages, or automation definitions).

The artifact is identified by its **`sha256:…` digest**, never its URL — a mirror
may rewrite the host. It carries a **detached publisher signature** over its
exact bytes. Packaging tooling (deterministic build, `sign`, `verify`) is the SDK
(#390); this spec fixes only the envelope, the digest, and the signature scheme
so all three consumers (loader, SDK, registry) agree.

**Signature scheme.** `ed25519` detached signatures for v1 (`sigstore` reserved
as a second `algorithm` value). A signature is `{ algorithm, key_id, value }`;
`key_id` maps to a trust level through the instance's policy/keystore (§6). The
**catalog index** (§5.1) is itself signed, by the *registry root* key, as a
separate detached signature over its bytes.

---

## 3. Manifest v2

Schema: [`docs/spec/module-manifest.schema.json`](spec/module-manifest.schema.json).
Manifest v2 formalises the `settings`/`widgets`/`nav_items`/`extensions` shape
that `ARCHITECTURE.md` §11.1 has always sketched but left "declared-but-unused",
and adds the fields the tiers and the registry need. It is **backwards-compatible**
with the current in-box manifests: they omit `manifest_version`, `publisher`, and
`trust_tier` and are treated as `manifest_version: 1` first-party kernel-trusted
code. **Third-party artifacts MUST declare `manifest_version: 2`.**

### 3.1 Example — a Tier-2 code module

```yaml
manifest_version: 2
id: acme.slack-notifier          # namespaced to avoid collisions
name: ACME Slack Notifier
version: 1.2.0                    # semver
kind: module
trust_tier: code
publisher:
  id: acme
  name: ACME Security
  url: https://acme.example
requires_flagpost:
  min: "1.7.0"                   # inclusive; `max` is exclusive
dependencies: [notifications]
provides:
  routes: true
  event_listeners: true
  migrations: true
capabilities:                    # every entry is shown for consent (§7)
  - network.egress
  - events.subscribe
  - settings.store
  - migrations.run
  - permissions.define
permissions:                     # registered on install, retired on uninstall
  - key: MANAGE_SLACK_NOTIFIER
    name: Manage Slack notifier
    category: Integrations
    scope: competition
settings:                        # rendered as a form by the generic settings UI
  - key: webhook_url
    type: secret
    label: Slack webhook URL
    required: true
```

### 3.2 Example — a Tier-0 content pack

```yaml
manifest_version: 2
id: acme.web-101-pack
name: Web 101 Pack
version: 1.0.0
kind: pack
publisher: { id: acme, name: ACME Security }
pack:
  pack_type: challenges          # challenges | theme | translations | automation-recipes
  target: competition            # challenges/automation-recipes → competition; theme/translations → site
```

### 3.3 Field notes

- **`trust_tier`** is required when `kind: module`; **`pack`** is required when
  `kind: pack` (enforced by the schema's conditional rules).
- **`capabilities`** is the consent surface. A `declarative` module may request
  only the declarative-safe subset — never `network.egress`, `migrations.run`, or
  `permissions.define` (those imply real code). The loader/validator enforces
  this in #388/#391.
- **`permissions`** mirror `auth/permissions.py` (a `key`, `category`, and
  `global`/`competition` `scope`). They are *central* today; #391 makes install
  register them into the catalog (so an Administrator gets them without a
  hand-written migration) and uninstall retire them.
- **`extensions`** keys are §11.2 slot names (`challenge.tabs`,
  `dashboard.widgets`, `team.detail.panels`, …); a contribution names a
  `component` the **compiled** frontend registry knows how to render — never raw
  markup or code (that is what keeps Tier 1 safe without a sandbox).
- **`required_core`** stays an in-box-only concept; a registry-distributed module
  is never required-core and is always subject to the per-competition enable gate
  (`is_module_enabled`).

---

## 4. Roles in the protocol

- **Registry** — serves a signed **catalog index** (§5.1) and resolves import
  **codes** (§5.2). `marketplace.flagpost.io` is the default; a private mirror or
  an air-gapped static host is a first-class alternative (§5.4).
- **Artifact store** — hosts the signed artifacts, content-addressed. Often a CDN;
  may be the same origin as the registry or a different one.
- **Instance** — the Flagpost deployment. Speaks the protocol *only on explicit
  operator action* (§6), verifies everything locally (§7), and never sends
  instance or competitor data to the registry.

---

## 5. Registry protocol

### 5.1 Catalog index

Schema: [`docs/spec/catalog-index.schema.json`](spec/catalog-index.schema.json).
A **signed, static, mirrorable** JSON document listing entries → versions →
`{ artifact (url + sha256 digest + size), signature, requires_flagpost,
capabilities, paid }`. Distributed with a **detached signature over its exact
bytes** (`catalog-index.json` + `catalog-index.json.sig`); the instance verifies
that against the registry's pinned root key before trusting any entry. Because it
is a plain signed file, an operator can mirror it wholesale (§5.4).

The index is a *discovery/listing* convenience. It is not required to install —
an operator who already has a code or an artifact file can install without ever
fetching it (§5.2, §5.4).

### 5.2 Code resolution (the primary online install UX)

An operator pastes a short **code** (e.g. `8fy17`). The instance calls:

```
GET {marketplace_url}/resolve/{code}
```

and receives a **resolution / confirmation payload**
([`docs/spec/resolve-response.schema.json`](spec/resolve-response.schema.json)):
the resolved identity + version + tier, publisher, the artifact `url`+`digest`,
the `signature`, `requires_flagpost`, the requested `capabilities`/`permissions`,
and — for paid items — a `commerce` block (§7). The instance renders this as a
**confirmation/trust screen**, and only on operator consent proceeds to fetch +
verify + install (§7, then #389).

Two rules make this safe:

1. **The code is a lookup key, never the trust boundary.** The operator consents
   to a *resolved identity*, not to a code.
2. **Every boolean in the response is a display hint.** `compatible`, `trust.*`,
   `commerce.entitlement_present` describe the *registry's* view. The instance
   **re-verifies** signature, digest, and version compatibility locally before
   installing and never relies on the server's say-so (§7).

Codes are **not secret** for free artifacts (a public code is a friendly alias,
fine to be short). A **paid** artifact's entitlement is a *different* class —
high-entropy, rate-limited, single-use or account/site-bound — and is handled at
download, not as a short guessable alias. Don't conflate the two.

### 5.3 Artifact fetch

The instance fetches `artifact.url`, checks the bytes against `artifact.digest`,
and verifies the detached `signature` against its trust policy (§6). A short-lived
signed URL MAY be issued for paid downloads; if so the resolution's `expires_at`
bounds it.

### 5.4 Mirroring & air-gap

The catalog index and artifacts are plain signed files, so an operator can mirror
the ones they need into their own object store / static host and point instances
at it with `marketplace_url`. For fully disconnected installs, the same
`resolve → confirm → verify → install` pipeline accepts an **artifact URL or an
uploaded file** directly (#389) — no registry round-trip. This is the path for
government/enterprise sovereignty and offline bundles; the private mirror MAY mint
its own codes since a code is resolved against whatever `marketplace_url` is
configured.

---

## 6. Instance-side model

Settings (surfaced in Admin; defaults chosen conservative-but-usable — finalised
in #389):

| Setting | Default | Meaning |
|---------|---------|---------|
| `marketplace_url` | `https://marketplace.flagpost.io` | The registry to resolve codes / fetch the catalog against. Point at a mirror to change trust root + source. |
| `marketplace_enabled` | `true` | Master switch. `false` removes the surface entirely (no resolve, no install) — for locked-down installs. No background calls are made even when `true`. |
| `trust_policy` | `verified` | Which signatures are acceptable: `official` (Flagpost root key only) ⊂ `verified` (official + registry-verified publishers) ⊂ `signed` (any key the operator added to the keystore) ⊂ `any` (accept unsigned — **dev only**, loud warning). |
| `max_trust_tier` | `declarative` | Caps what tier may be installed: `pack` ⊂ `declarative` ⊂ `code`. Ships conservative — installing third-party **code** (Tier 2) requires an explicit operator opt-in (raise to `code`). A hardened profile lowers it to `pack`. |

**On-demand only.** The instance contacts the registry *solely* when an operator
resolves a code, browses (fetches the catalog), installs, or checks for an
update. There is no background polling and no instance/competitor data in any
request — consistent with the "nothing phones home" posture (`PRIVACY.md` §13.4).
The install lifecycle (resolve → confirm → verify → install → enable → update →
uninstall), the installed-module registry (pinned `version`+`digest`, audited via
`module.*` events), and these settings are specified and built in **#389**.

---

## 7. Security model

- **Signing ⟂ entitlement.** The instance **always** verifies the artifact
  signature + digest + `requires_flagpost` — free and paid alike. Trust comes
  from the signature, never from having paid.
- **Entitlement (paid) is checked at *download*, then verified *offline*.** A
  paid artifact is gated at the distribution boundary (you need an entitlement to
  download) and, where a module enforces licensing, via a **signed license the
  module verifies offline** — **no runtime license phone-home**. This is what
  keeps paid content working on self-hosted and air-gapped installs. Do **not**
  add a runtime DRM/subscription check to the core.
- **Capabilities are explicit consent.** The confirmation screen enumerates the
  module's requested `capabilities` (and, for code tier, the `permissions` it
  would add); consent is recorded in the install audit. After download the
  instance re-reads the manifest and refuses if the artifact requests more than
  was consented to.
- **Local re-verification is mandatory.** Registry-supplied `compatible`/`trust`
  flags are display hints; the instance re-derives the real answer. A tampered,
  incompatible, disallowed-tier, or wrong-signature artifact is refused with a
  clear reason.
- **Non-goal: isolating untrusted code.** Tier 2 code runs in-process with full
  access — the honesty is in making that *explicit, signed, and consented*, the
  same posture the `ai` module uses to ship a risky capability safely (off/guarded
  by default). Running genuinely untrusted code safely is **Tier 3**, deferred
  (`ARCHITECTURE.md` §15). The conservative defaults (`trust_policy: verified`,
  `max_trust_tier: declarative`) mean an out-of-the-box instance installs only
  signed, verified-publisher content and *declarative* modules; running
  third-party **code** requires an explicit operator opt-in, and widening trust to
  self-signed/unsigned keys is a further, separate opt-in.

---

## 8. Versioning & compatibility

- Artifacts are **semver**; `requires_flagpost.min` is inclusive and `max`
  exclusive. The instance refuses anything outside its own version's range.
- Each wire format carries a `schema_version` (manifest: `manifest_version`);
  consumers reject an unknown major.
- A published version can be **`yanked`** (withdrawn, e.g. for a security issue):
  already-installed instances keep it, new installs are refused.

---

## 9. Open drafting questions (to close during #386/#389 implementation)

- **Artifact container format** — tarball vs. zip vs. OCI artifact. OCI would let
  the existing registry/CDN infrastructure carry modules, at the cost of a heavier
  client; a signed tarball is simpler and air-gap-trivial. Decide in #390.
- **Root-key distribution & rotation** — how the Flagpost root public key and
  registry keys are pinned in the instance, and rotated without a redeploy.
- **Entitlement token format** — the offline license/entitlement structure for
  paid artifacts (a signed, instance- or org-bound token) is defined with the
  hosted commerce service, not here; this spec only reserves the `commerce` block
  and the download-time/offline-verify posture.
- **Version-range grammar** — `requires_flagpost` uses an inclusive-min/exclusive-max
  pair for now; a full npm-style range string is a possible future extension.
