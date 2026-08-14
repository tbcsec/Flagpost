# ADR-0027: Certificate rendering — server-side compositing (Pillow → PNG), not a headless browser

**Status:** Proposed
**Date:** 2026-08-13
**Architecture reference:** `ARCHITECTURE.md` §11.3 (the optional `certificates` module — to be written when the feature is built)

## Context

The v1.5.0 certificate feature turns a per-competition template — a background
image plus drag-positioned tokens like `{competition_name}`, `{placement}`,
`{recipient_name}` — into a downloadable artefact, one per participant, once an
event ends. The artefact exists **to be shared on social media** (that's the
feature's whole point) and must carry an un-removable "Made with Flagpost"
footer. The template is authored in an in-app WYSIWYG editor, and the same
layout has to render identically for thousands of recipients.

So a renderer is needed, and the real options a builder would weigh are:

1. **Headless browser** (Playwright / Puppeteer) — author the certificate as
   HTML/CSS and render it to PNG/PDF with a real browser engine. Pixel-perfect
   CSS, and the editor preview *is* the renderer (same engine), so parity is
   free.
2. **Server-side image compositing** (Pillow) — composite the background plus
   positioned text/images into a PNG with an imaging library. No browser.
3. **Client-side rendering** (html2canvas / `<canvas>` in the participant's
   browser) — the browser that downloads also renders.

The tension is fidelity and ergonomics (option 1 wins) against deployment
footprint and determinism. Flagpost's headline install story is a single
`docker compose up`, and the backend deliberately carries no heavyweight runtime
beyond Python + Postgres/Redis/MinIO. A headless Chromium is a large binary, a
memory-hungry subprocess, and a real operational surface — a meaningful
departure from that story. Option 3 is worse for this feature specifically: the
client holds the un-branded pixels (so the footer is trivially strippable) and
output varies by the viewer's browser and installed fonts — unacceptable for a
marketing artefact whose branding must be persistent.

## Decision

Render certificates **server-side by compositing with Pillow, output PNG.** The
template stores element positions as **percentages** of a fixed landscape-A4
canvas; the renderer resolves each recipient's tokens and draws text/images at
those coordinates using a **bundled set of open-licensed (OFL) fonts**. PDF
output, if added later, uses ReportLab from the same layout data — still no
browser. The editor and the server renderer share the percentage coordinate
model and the *exact same font files*, and admins preview through the real
renderer rather than an HTML approximation, so the on-screen preview and the
downloaded PNG agree.

## Consequences

- **Positive:**
  - No headless browser — the `docker compose up` story and the backend's small
    footprint are preserved.
  - Deterministic output: a recipient's certificate is byte-stable regardless of
    their browser or installed fonts.
  - The server owns the pixels, so the branding footer is composited outside the
    editable region and the client never receives an un-branded image — the
    branding is *structurally* un-removable, which is the point of the marketing
    lever (and the hook for a future paid "remove branding" tier).
  - PNG is the native social-share format (inline previews on X / LinkedIn /
    Discord) — the reason the feature exists.
  - A certificate is a pure function of (template, recipient standing), so it
    renders on demand and nothing per-recipient is persisted.
- **Negative / cost:**
  - Editor↔render **parity is our responsibility now**, not the browser's. It's
    bought with the shared percentage-coordinate model, the shared font files,
    and a "preview = call the real renderer" endpoint — a real but bounded task,
    and the main risk to name up front.
  - Pillow text layout is manual (measure, wrap, align, rotate by hand) where CSS
    would be declarative. Fine for positioned tokens and short lines; it is not a
    rich-text engine.
  - Bulk export of "all participants" for a large event is N server-side renders,
    so it must run as an async batch job, never a synchronous request.
- **Forecloses:**
  - Templates are **not** arbitrary HTML/CSS. Flowing rich text, complex
    typography, or CSS-driven layout would need a different engine (WeasyPrint,
    or the very headless browser we're declining here) — a future ADR if that
    requirement ever genuinely lands.

## Later additions (v1.5.0)

Two capabilities were layered on the same model after the initial build; neither
changes the decision above.

- **Organiser-uploaded custom fonts.** Beyond the bundled OFL set, an organiser
  may upload a company/brand TTF/OTF (`CertificateFont`, stored per-competition
  in object storage). An element references it as `font="custom:<id>"`; the
  renderer resolves the bytes at render time (a new `font_bytes` map) and a
  missing/deleted/foreign ref falls back to a bundled default, so a font never
  breaks a render or leaks across tenants. Nothing is bundled or redistributed
  — the *operator* is responsible for holding a licence, surfaced in the upload
  UI. Editor↔render parity holds via a blob-loaded `@font-face` (auth'd, since a
  `@font-face` request can't carry the bearer token) declaring all four
  weight/style slots against the single uploaded file, matching Pillow (which
  does no faux bold/italic).
- **Portable template export/import.** A design exports as a **single
  self-contained JSON** that embeds every referenced binary (uploaded
  background, image elements, custom fonts) as base64, so a company can save a
  certificate one year and re-import it into a brand-new instance the next.
  Import re-uploads the assets into the target competition, rewrites the
  references to fresh in-scope keys/ids, and re-runs the *normal* template
  hardening — so an imported design is validated exactly like an authored one,
  and no foreign object key can survive into the saved template.
