# Translations

How Flagpost's UI gets translated, and how to help. Decision record:
[ADR-0029](adr/0029-frontend-i18n-next-intl-crowdin.md). Scope today:
**frontend UI chrome only** — backend API messages and emails are a later
phase, and organizer-authored content (challenges, announcements, rules) is
never translated by the platform; it belongs to the organizer in whatever
language they write it.

## The pipeline

```
frontend/messages/en.json          Crowdin (crowdin.com/project/flagpost)
        │                                   │
        │  push to main ──────────────────▶ │  new strings appear for translators
        │                                   │  machine pre-translation drafts them
        │                                   │  a human reviews/approves
        │ ◀────────────── pull request ──── │  Crowdin opens a PR with
        │                                   │  frontend/messages/<locale>.json
        ▼
   CI validates (frontend/src/i18n/messages.test.ts) → maintainer merges
```

- **`frontend/messages/en.json` is the single source of truth**, edited only
  through normal code PRs alongside the components that use the strings.
- **Translation files are generated artifacts.** Never hand-edit
  `frontend/messages/<locale>.json` — Crowdin overwrites them on its next
  sync. Fix a bad translation *in Crowdin*; it comes back via the next PR.
- **Files are always complete.** Crowdin exports untranslated strings as the
  English source text, so a partially-translated locale degrades to English
  per-string instead of showing raw key paths (the runtime loads exactly one
  catalog — there is no merge with English).
- **CI gates every translation PR**: the messages test asserts each catalog
  has exactly the source's keys, no empty strings, and that every ICU
  placeholder (`{name}`) and rich-text tag (`<link>…</link>`) survived
  translation — the failure modes machine translation actually produces.
- Crowdin is a **development-time** service. A deployed Flagpost instance
  never talks to it (`PRIVACY.md` still holds: nothing phones home).

## For translators

Join the project at <https://crowdin.com/project/flagpost> — no repo access
or Git knowledge needed. Machine translation drafts new strings; your review
and corrections are what actually ship. String context: keys are namespaced
by app area (`auth.login.*` is the sign-in screen, and so on), and
`{placeholders}` / `<tags>` must be kept intact — reposition them freely for
your language's grammar, but don't translate or delete them.

Want a language that isn't listed yet? Open a GitHub issue (or ask in the
Crowdin project) and a maintainer will add the target language.

## Shipping a language (maintainers)

A locale appears in the product only when it's added to the code — Crowdin
merging translations does *not* enable it by itself:

1. Wait until the locale's review coverage is respectable (the demo pages at
   minimum: `common.*`, `auth.*`).
2. Add it to `LOCALES` and `LOCALE_LABELS` (its **endonym**) in
   [frontend/src/i18n/config.ts](../frontend/src/i18n/config.ts) — two lines.
3. That's the whole change. The language picker appears on the auth screens,
   the app shell and the public boards by itself; `Accept-Language`
   negotiation starts offering the locale to first-time visitors; the
   messages test starts requiring the catalog to exist.

## One-time Crowdin setup (maintainers)

Recorded so the setup is reproducible; already-done steps are just history.

1. Create the **Crowdin project** (`flagpost`), source language English.
2. Apply for the **Open Source plan** (free): crowdin.com → Open Source
   Program. Needs the public repo URL and the OSI license.
3. Install the **Crowdin GitHub integration** (the GitHub App) on the repo,
   sync branch `main`, and set the file mapping — source
   `/frontend/messages/en.json`, translations
   `/frontend/messages/%locale%.json`. The App **owns and maintains**
   [crowdin.yml](../crowdin.yml) at the repo root (it commits changes there
   itself); treat that file as generated — configure paths in the Crowdin
   UI, not by hand-editing it. Use **Language Mapping** in the UI so each
   language's `%locale%` value equals the exact slug in
   [`config.ts`](../frontend/src/i18n/config.ts) `LOCALES` (e.g. German →
   `de`), since `%locale%` otherwise expands region-qualified (`de-DE`).
4. In the project settings, enable **machine pre-translation** for new
   source strings, with human proofreading before export.
5. Set the export policy to include untranslated strings as source text
   (Crowdin's default) — the "files are always complete" invariant above
   depends on it.
