# ADR-0030: Post-event report rendering — HTML + WeasyPrint (not Pillow, not a headless browser)

**Status:** Accepted
**Date:** 2026-08-18
**Architecture reference:** `ARCHITECTURE.md` §11.3 (the optional `reports` module); supersedes nothing, extends ADR-0027.

## Context

The v1.5.0 post-event report feature (#134) turns a finished competition into a
downloadable, branded document aimed at two audiences at once — an executive
read (how the event went, at a glance) and a technical debrief (per-challenge
solve breakdowns, support load, difficulty calibration). The deliverable is
required in **both PDF and HTML**, must **inherit site branding** (platform
name, accent colour, logo — from `SiteSetting`), and must carry a subtle,
un-removable "Powered by Flagpost" footer on every page.

Structurally this artefact is the opposite of a certificate. A certificate
(ADR-0027) is a **fixed-canvas image** with a handful of drag-positioned tokens,
rendered to PNG for social sharing. A report is a **flowing, multi-page
document**: headings, paragraphs of auto-generated narrative, data tables that
break across pages, charts, running headers/footers, and page numbers.

ADR-0027 chose Pillow for certificates and **explicitly foreclosed exactly this
case**, naming the successor decision in advance:

> "Templates are **not** arbitrary HTML/CSS. Flowing rich text, complex
> typography, or CSS-driven layout would need a different engine (WeasyPrint, or
> the very headless browser we're declining here) — a future ADR if that
> requirement ever genuinely lands."

It has landed. This is that ADR.

The options a builder would actually weigh:

1. **Pillow** (ADR-0027's certificate engine) — reuse what we have. But Pillow
   is a raster compositor: text layout is manual (measure, wrap, align by hand),
   there is no concept of flow, pagination, or tables. Building a multi-page
   report in it means re-implementing a document engine by hand. Wrong tool.
2. **ReportLab / Platypus** — pure-Python, real flowables and pagination, **no
   system libraries**. But the layout is hand-built in Python (not declarative),
   it produces **no HTML** (an explicit deliverable here), and charts need a
   separate drawing path. We would maintain report layout twice and still owe an
   HTML renderer.
3. **Headless browser** (Playwright/Puppeteer) — pixel-perfect HTML/CSS and PDF
   from one engine. But it reintroduces precisely the large-binary,
   memory-hungry subprocess and operational surface ADR-0027 declined, against
   Flagpost's single-`docker compose up` story.
4. **HTML (Jinja2) → WeasyPrint → PDF** — author one HTML template; it *is* the
   HTML deliverable, and WeasyPrint converts the same HTML to PDF. WeasyPrint is
   a pure-Python renderer (with system C libraries — Pango, cairo,
   gdk-pixbuf — but **no browser**) that implements CSS Paged Media: page
   breaks, running headers/footers, page numbers, and repeating table headers
   come free from CSS.

## Decision

Render post-event reports with **Jinja2 → HTML → WeasyPrint → PDF (option 4).**
One authored template yields both required artefacts; the HTML string is the HTML
deliverable, and WeasyPrint renders that same HTML to the PDF.

Specifics that make this deterministic and safe:

- **Charts are server-rendered inline SVG** from a small, fixed vocabulary
  (area, line/race, donut, hour-of-day heatmap, horizontal bar), produced by
  pure-Python helpers that emit SVG strings. No JavaScript, no charting runtime,
  and no matplotlib/numpy dependency — the footprint stays small and output is
  byte-deterministic.
- **Branding is threaded from `SiteSetting`** at render time (`platform_name`,
  `accent`, `logo_data` → embedded as a `data:` URI). This is a deliberate
  departure from the certificates renderer, which hard-codes the flagpost.io
  mark. The "Powered by Flagpost" footer is composited by the template into the
  `@page` running footer — present on every page, outside the report's data,
  subtle by design.
- **Fonts are bundled OFL faces** (reuse the set the certificates module already
  ships), referenced via `@font-face` with `file:` URLs so WeasyPrint embeds
  them. Output does not depend on system-installed fonts.
- **A restricted `url_fetcher` is passed to WeasyPrint.** The report embeds
  user-supplied strings (challenge titles, team/participant names). WeasyPrint
  can otherwise resolve `url()`/`<img src>`/`@font-face` against the network and
  local filesystem — an SSRF and local-file-read surface. Our fetcher serves
  **only** bundled assets and the in-DB logo bytes and refuses every network and
  `file:` request, so no report content can trigger an outbound fetch or read a
  local file. Report templates are ours, never user-authored — no user HTML is
  ever fed to WeasyPrint.
- **Rendering runs off the request path.** WeasyPrint is synchronous CPU work;
  generation is an async job (the background/scheduler lane, ADR-0025/0026) and
  the render itself runs via `asyncio.to_thread`, never inline in a request —
  the same discipline ADR-0027 required for bulk certificate export.
- **The finished file is streamed back through the API, not presigned.** A ready
  report downloads via `GET …/reports/{id}/download/{fmt}`, which reads the
  object with the backend's *internal* storage client and streams it to the
  browser. It is deliberately **not** a presigned object-store URL, for two
  reasons. First, topology: on a single-origin deployment — the default
  `docker compose` behind Caddy, and the public demo behind a Cloudflare Tunnel
  that only exposes Caddy — MinIO is not browser-reachable at all, so a signed
  `minio:9000` URL resolves nowhere; proxying needs no object-store exposure and
  works everywhere. Second, access: a report aggregates whole-competition data
  and is gated on `generate_report`, so re-checking that permission on every
  fetch is stronger than a bearer URL that grants read for its whole TTL. This
  mirrors the ticket-attachment `/content` and per-user certificate download
  routes; the certificates **bulk ZIP export** keeps presigning because it can be
  large, and challenge attachments likewise presign and expect an exposed object
  store on multi-host deploys (README → "Deploying to production"). The split is
  by artefact size and exposure model, not inconsistency.

This does **not** change ADR-0027 for certificates. Flagpost now has two
renderers, each fit to its artefact: a **fixed-canvas social image** stays Pillow
→ PNG; a **flowing document** is HTML → WeasyPrint → PDF. The split is by
artefact shape, not a reversal.

## Consequences

- **Positive:**
  - One template produces both deliverables the feature requires; CSS is
    declarative where Pillow layout is manual.
  - Deterministic output — bundled fonts, inline SVG, no JS engine — so a report
    renders identically regardless of host or installed fonts.
  - Branding is genuinely inherited from site settings, and the "Powered by
    Flagpost" footer is structurally on every page.
  - CSS Paged Media gives pagination, running headers/footers, page numbers, and
    repeating table headers for free — the hard parts of a printable document.
- **Negative / cost:**
  - WeasyPrint pulls **system C libraries** (Pango, cairo, gdk-pixbuf, libffi)
    into the backend image and CI. A real footprint increase and the main cost to
    name — but far smaller than a bundled Chromium, with no subprocess or
    browser-security surface, and it keeps the "no headless browser" stance.
  - Charts are a **bounded, hand-authored vocabulary**, not arbitrary
    visualisation. New chart types are backend work.
  - Layout parity is CSS's job now, but WeasyPrint's CSS support, while broad, is
    not a full browser's — exotic CSS may not render. Templates stay within its
    documented support.
- **Forecloses:**
  - Interactive or JS-driven charts inside the artefact.
  - User-authored report templates / arbitrary HTML into WeasyPrint (kept closed
    for the SSRF/file-read reasons above). A future WYSIWYG report designer would
    need a new ADR and a hardened template model, as certificates have.

## Alternatives revisited

If the system-library footprint ever proves unacceptable on a target platform,
ReportLab (option 2) remains the fallback for PDF — at the cost of a second,
hand-built layout and a separately maintained HTML renderer. We accept the
WeasyPrint dependency now because a single HTML source for both deliverables is
worth more than avoiding the libraries, and because the alternative doubles the
layout surface for a document this section-rich.
