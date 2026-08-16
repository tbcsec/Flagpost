# ADR-0029: Frontend i18n — next-intl with a cookie locale, translations managed in Crowdin

**Status:** Accepted
**Date:** 2026-08-16
**Architecture reference:** `ARCHITECTURE.md` §2 (stack), §8 (frontend data access)

## Context

Flagpost's UI is English-only, and every string is a hardcoded literal: ~145
`.tsx` files with several hundred user-facing strings, ~150 `toast()` calls,
plus ~286 backend `detail=` API messages. Issue #78 asks for
internationalization. Deployers run CTFs for non-English audiences today;
they currently can't offer the platform chrome in their language at all.

Decisions that had to be made, and the real options for each:

**1. What gets translated.** Three string populations exist: frontend UI
chrome, backend API/error/email strings, and organizer-authored content
(challenge text, announcements, rules). Translating everything at once is a
platform-wide rewrite; translating nothing of the backend means some API
errors surface in English inside a translated UI.

**2. Library.** The App Router candidates: **next-intl** (built for App
Router, works in server and client components, ICU messages),
**react-i18next** (mature, client-oriented, App Router server-component
support is bolted on), **FormatJS/react-intl** (ICU-native but
extraction-toolchain-heavy), or a hand-rolled `t()` over JSON (no plural
rules, no ICU, a guaranteed rewrite later).

**3. Locale routing.** next-intl's canonical setup puts the locale in the
URL (`/en/...`, `/de/...`) via middleware and a `[locale]` segment. The
alternative is its documented **non-routed** mode: locale resolved
per-request in `getRequestConfig` from a cookie, no URL changes, no
middleware, no route restructuring.

**4. Locale persistence.** A `users.locale` column (migration, API surface,
profile UI, and a value the login/setup screens can't see because the user
isn't authenticated yet) versus a plain cookie with an `Accept-Language`
default — the same client-side posture the theme system already uses
(localStorage + pre-hydration script, no backend involvement). The cookie
must be a cookie rather than localStorage because server components render
strings on the server, where localStorage doesn't exist.

**5. Who translates, and where.** Flagpost has no volunteer translator base
yet. Options: translations as hand-edited JSON PRs (no tooling, no memory,
merge conflicts as files grow), self-hosted **Weblate** (another service to
operate, against a project that keeps its own infra footprint minimal), or
hosted **Crowdin** (free open-source plan, GitHub sync, machine-translation
pre-translate with human review, opens translation PRs against the repo).

## Decision

**Scope: frontend UI chrome only, extracted incrementally.** Backend strings
(API `detail=`, emails) are explicitly deferred to a follow-up effort;
organizer-authored content is never machine-owned by the platform — it is
the organizer's content in whatever language they write it. Extraction
proceeds domain-by-domain (mirroring the one-hook-per-domain layout, §8);
untranslated keys fall back to English, so the app is shippable at every
intermediate step.

**Library: next-intl, in non-routed mode.** One `messages/en.json` is the
in-repo source of truth, namespaced per domain, ICU MessageFormat for
plurals/interpolation. The locale comes from a cookie read in
`getRequestConfig`; first visit defaults from `Accept-Language`. No
`[locale]` URL segment, no middleware: Flagpost is an auth-gated app, not a
content site — per-locale URLs buy SEO we don't need and would churn every
route, link, and deep-link in the process. The user picks a language in the
UI; the choice is device-local (cookie), not account-persisted — consistent
with how theme preference works. `<html lang>` follows the resolved locale.

**Translations: managed in Crowdin** (hosted, free open-source plan). GitHub
integration syncs `messages/en.json` up on merge; machine translation
pre-translates new strings; reviewed translations come back as PRs adding
`messages/<locale>.json`. Translated files are generated artifacts that
still land through normal PR review. Crowdin is a **development-time**
service: nothing in a deployed Flagpost instance talks to it — the runtime
outbound-call posture (`PRIVACY.md`, §13.4) is unchanged.

**Directionality: LTR-first.** RTL (Arabic, Hebrew) is deferred — it
requires a logical-properties audit of the whole component library and
`dir` flipping, and is an extension of this decision, not a revision.

## Consequences

- **Positive:**
  - Server and client components translate through one API; ICU gives real
    plural/gender rules instead of string concatenation.
  - No URL churn: every existing route, bookmark, and deep-link survives.
    No middleware in a stack that deliberately has none.
  - No backend surface at all in phase one — no migration, no API change,
    nothing for export/import (ADR-0016) to carry.
  - Crowdin gives MT + review + sync without operating another service, and
    without waiting for a volunteer base that doesn't exist yet.
  - English-only deployments see zero behavior change; fallback-to-English
    makes partial translations usable rather than broken.
- **Negative / cost:**
  - **String discipline becomes permanent.** Every future PR must add UI
    strings through `t()`/messages, not literals — a review burden until an
    ESLint guard against raw JSX text is added (planned once extraction
    settles; premature during it).
  - The extraction itself is a long mechanical tail across ~145 files,
    landed as many small PRs.
  - Cookie locale doesn't follow the account across devices. Acceptable
    now; a `users.locale` column can layer on later without reworking the
    resolution order (explicit choice → cookie → `Accept-Language`).
  - Pages that render translated strings on the server read the locale
    cookie at request time and therefore render dynamically. Most of the
    app is already dynamic (auth-gated, client-heavy); static shells keep
    working by passing messages through the client provider. CI's
    `npm run build` will catch any prerender regression.
  - A translated UI over an untranslated backend shows English API errors
    until the deferred backend phase happens — visible seam, called out
    rather than hidden.
  - Crowdin is a third-party dependency for the *translation workflow* (not
    the product); if it goes away, the JSON files in-repo are the canonical
    state and another tool can pick them up.
- **Forecloses:**
  - Nothing hard. URL-based locales could be added later if public pages
    (`/public/*` spectator boards) ever need per-locale SEO — next-intl
    supports migrating from cookie mode to routed mode. RTL and backend
    translation are extensions. Per-competition language forcing (an
    organizer pinning the UI language for an event) is not designed here
    and would need its own decision.
