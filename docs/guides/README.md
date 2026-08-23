# User guides

Official, role-split user documentation, built as branded PDFs: one guide per
system role (**Competitor**, **Judge**, **Admin**), mirroring the RBAC scope
split — competition-scoped staff features belong to the Judge guide, global
administration to the Admin guide, and deployment/ops docs stay on the docs
site (they are not user guides).

The PDFs are published on docs.flagpost.io **and** bundled into the frontend
image (`frontend/public/guides/`) so airgapped installs have them and every
install ships guides matching its own version.

## Layout

```
guides/
  build.py            # Markdown → branded PDF (WeasyPrint)
  requirements.txt    # build tooling (see backend image notes for system libs)
  theme/              # print theme: stylesheet, page template, mark, fonts
  <slug>/guide.yaml   # one directory per guide: metadata + chapter order
  <slug>/chapters/    # Markdown chapters
  dist/               # build output (gitignored)
```

## Authoring rules

- Chapters start at `##` — the build renders each chapter's `H1` (and the
  "Chapter N" kicker) from `guide.yaml`, so the TOC can't drift from the body.
- Callouts are Markdown admonitions: `!!! tip "Title"` (green) and
  `!!! note "Title"` (amber) with the body indented four spaces.
- Keep colours out of the content — the theme owns all styling. The palette
  mirrors the app's Harbor tokens (`frontend/src/app/globals.css`); change
  them together or not at all.
- Guides are English-only for now; the Crowdin pipeline covers UI strings
  (`frontend/messages/`), not these documents.

## Building

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python build.py            # all guides → dist/
.venv/bin/python build.py competitor # one guide
.venv/bin/python build.py --deploy   # + copy into frontend/public/guides/
```

WeasyPrint needs system Pango/cairo/gdk-pixbuf (the same libraries the
reports module documents; present in the backend image). The cover's version
stamp is read from `SOURCE_BUILD_VERSION` in `backend/config.py` — rebuild the
guides when cutting a release (CONTRIBUTING → "Cutting a release").
