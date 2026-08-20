# ADR-0034: Custom pages store rich text and render as a React tree, never as HTML

**Status:** Accepted
**Date:** 2026-08-20
**Architecture reference:** `ARCHITECTURE.md` §7.1 (permissions), §11.3 (modules); extends ADR-0011 (theming scope) and the rich-text renderer introduced for the sign-in notice (#197).

## Context

Custom pages (#198) let an administrator author site-level content — About,
Sponsors, Contact, a Discord invite — that appears in the sidebar and renders at
`/p/{slug}`. The obvious reference implementation is CTFd, whose Pages feature
accepts **raw HTML, CSS and `<script>`**, and that is exactly the design decision
worth recording, because Flagpost cannot copy it.

Two facts make raw markup unsafe here specifically:

1. **The shipped CSP permits inline script.** `Caddyfile:34` sets
   `script-src 'self' 'unsafe-inline'`. A stored `<script>` in page content is
   therefore not inert markup that a browser might sanitise — it executes.
2. **Authoring is a *lesser* grant than administration.** `manage_pages` is a
   content-editor permission, the kind an organiser hands to a comms volunteer.
   If holding it allowed script injection into a page an administrator later
   views, it would escalate silently into session theft — the same
   grant-separation reasoning that keeps `manage_auth_providers` distinct from
   `manage_site_settings` (§7.1).

So the real options were:

- **Raw HTML plus a sanitiser** (bleach/DOMPurify-style allowlist). Rejected:
  sanitisers are a permanent maintenance liability — the allowlist has to be
  re-argued on every dependency bump, and a bypass is a full account-takeover
  bug rather than a rendering glitch. It also means the server or client
  produces an HTML string that something must eventually inject, which is the
  hazard we are trying not to have.
- **Markdown.** Safer than HTML, but most markdown renderers pass raw HTML
  through by default, so it re-opens the same hole unless carefully disabled —
  and it would introduce a second authoring model alongside the rich-text
  editor #197 already shipped.
- **Structured rich text rendered as a React tree.** Chosen.

## Decision

Page content is stored as **ProseMirror JSON** (the same shape and editor as the
sign-in notice) and rendered **only** through the read-only `RichTextView`
component, which mounts a non-editable TipTap instance. Concretely:

- **No HTML string is ever produced from page content, on the server or the
  client, and `dangerouslySetInnerHTML` is never used for it.** The document
  becomes a React element tree under the same schema that wrote it, so markup
  smuggled into stored JSON renders as inert text or not at all, without a
  sanitiser in the path.

  Precisely what "not at all" means, since it was measured rather than assumed:
  an **undeclared attribute** (`onclick`, `style`) is dropped by ProseMirror's
  serializer, while an **unknown node type** makes `Node.fromJSON` raise and
  TipTap fall back to an empty document — so one bad node blanks the *whole
  body* rather than just itself. Either way the failure direction is "renders
  less", never "renders more", which is what the security argument needs; but
  the availability consequence is real and is why the renderer is wrapped in an
  error boundary (below).

  **One caveat, found while building this and worth stating precisely:** "no
  markup" does not by itself mean "no script", because the schema *does* include
  a **link mark** (StarterKit bundles `extension-link`), and a `javascript:`
  href in stored JSON would be a clickable script rather than inert text. TipTap
  neutralises hostile schemes — `javascript:`, `data:`, `vbscript:`, including
  case- and whitespace-variants — to an empty href, which was verified
  empirically rather than taken on trust. But that is a **third-party default**,
  not a property this codebase states, so it is pinned by a regression test
  (`rich-text-view.test.tsx`, "RichTextView link hrefs") in the same spirit as
  the Y.js singleton check: an upgrade that relaxes it fails the build instead of
  silently turning `manage_pages` into session theft. This applies equally to the
  sign-in notice (#197), which shares the renderer.
- **Write-time validation is shape-only.** The server checks that the payload
  looks like a document (`type == "doc"`, a list `content`) and enforces a size
  cap; it never interprets or rewrites the tree. That check is shared with the
  sign-in notice rather than duplicated, so the two cannot drift on what a valid
  document is.
- **Availability is part of the threat model, not just confidentiality.**
  `manage_pages` is delegable, so a page author must not be able to break the
  application for everyone — an adversarial review of this feature found exactly
  that, twice, and both are now closed:
  - The sidebar **icon** is a name from a fixed catalog, validated against an
    allowlist server-side *and* looked up with an own-property check client-side.
    A bare `ICON_PATHS[name] ?? default` is wrong: names like `__proto__` and
    `constructor` are inherited `Object.prototype` keys, so the lookup returns a
    non-element, the fallback never fires, and React throws — in the sidebar,
    which every authenticated route renders, including the admin screen needed
    to undo it. Both layers are checked because backup import writes rows
    directly and never passes through the schemas.
  - The renderer sits behind an **error boundary**. The doc-shape guard is only
    one level deep, so shapes that throw inside TipTap (a link mark whose `href`
    is a number reaches `uri.replace`) would otherwise take down the embedding
    page — and the sign-in notice embeds the same component on `/login`, the one
    page an operator needs in order to fix anything.

- **A hidden page is a 404, and it is decided in the query.** Filtering after
  loading the row leaks existence through timing, because fetching a hidden
  page's body costs measurably more than missing the index — on an endpoint that
  is unauthenticated and unthrottled.

- **Pages are site-level for v1**, not per-competition — consistent with
  ADR-0011 keeping theming site-wide. A nullable `competition_id` is
  deliberately *not* added "for later": it would imply a tenancy story (§6.2)
  that isn't implemented.
- **Visibility is a three-state matrix**, and a hidden page is a 404 rather than
  a 403, so page existence doesn't leak to visitors who may not see it:

  | | anonymous | authenticated | `manage_pages` |
  |---|---|---|---|
  | `draft` | 404 | 404 | visible |
  | `visibility: public` | visible | visible | visible |
  | `visibility: authenticated` | 404 | visible | visible |

## Consequences

- **Positive:** the dangerous capability simply does not exist in the codebase —
  there is no injection sink to audit, no sanitiser allowlist to maintain, and
  `manage_pages` can be delegated without it being a latent path to an
  administrator's session. Authoring reuses the editor, the renderer and the
  validation that #197 already shipped, so pages add content surface rather than
  new machinery.
- **Negative / cost:** authors get what the schema allows and nothing more — no
  embedded HTML, no custom CSS, no `<iframe>` for a Discord widget or a sponsor
  embed, which are things CTFd users do today. Images are excluded from v1 as
  well (the same CSP line is `img-src 'self' data: blob:`, so external URLs
  would not render anyway; adding them means routing through the MinIO
  attachment pipeline). Anyone wanting those must extend the schema
  deliberately, which is the point.
- **Negative, accepted:** because `RichTextView` is a client component, a public
  page's body is **not in the server-rendered HTML**, so it is invisible to
  search engines and link unfurlers. The fix — TipTap's server-side
  `generateHTML` — would hand us an HTML string to inject, reintroducing exactly
  the sink this ADR removes. Owner decision (2026-08-20): accept the SEO cost.
- **Forecloses nothing, but deliberately does not build:** per-locale page
  content. Page titles and bodies are **operator-authored data, not UI strings**,
  and are therefore outside the next-intl catalog (ADR-0029) — the same stance
  challenge names and descriptions take. A multilingual install shows the same
  page to every locale, and choosing an appropriate language is the operator's
  responsibility (owner decision, 2026-08-20).
