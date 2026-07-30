# Flagpost — Logo Specification

**Version 1.0 · Sketch pass locked**

This document specifies the Flagpost logo: geometry, colour, typography, clear
space, and usage rules. It is written to be handed directly to a design tool or
a contributor, and to serve as the reference the design system builds on top of.

Scope note: this covers the **logo** only. The broader design system (component
tokens, spacing scale, type ramp for UI) is downstream of this and lives in the
design system spec, not here. Where the two touch — the accent colour token in
particular — this document defines the source value and the design system
consumes it.

---

## 1. The Mark

The Flagpost mark is a flag planted on a post: a vertical rounded stem with a
swallowtail pennant flying right from the top, and an elliptical ground shadow
at the base.

The idea it encodes: a flag driven into ground marks a position claimed. On a
CTF platform that reads two ways at once — the flag captured, and the point on
the board where a team now stands.

### 1.1 Geometry

All artwork is authored on a **64 × 64 viewBox**. Coordinates are absolute
within that box and must not be redrawn by eye.

| Element | Definition |
|---|---|
| Post | `rect x=19 y=6 width=6 height=49 rx=3` |
| Flag | `path M25 9 H46 L40.5 16 L46 23 H25 Z` |
| Ground | `ellipse cx=22 cy=55 rx=12 ry=3.2` at 16% opacity |

Derived proportions, for anyone rebuilding the mark at another scale:

- Post width is **6/64** of the canvas; post height is **49/64**.
- Flag depth (top to bottom of pennant) is **14/64**, starting 3 units below
  the top of the post.
- Flag reaches **46/64** across — it must not extend past the 46 line, or the
  mark stops fitting a square container cleanly.
- The swallowtail notch cuts **5.5 units** deep into the fly end. This notch is
  the identifying detail of the mark; it is never removed or softened.

### 1.2 Artwork variants

Five variants are authored. Do not create new ones without adding them here.

| File | Use |
|---|---|
| `flagpost-mark-primary.svg` | Default. Ink post, green flag, ground shadow. Light backgrounds, ≥ 32px. |
| `flagpost-mark-compact.svg` | Ground shadow removed. **Required** below 32px, and for favicons. |
| `flagpost-mark-mono.svg` | Single colour via `currentColor`. Certificates, print, embeds, anywhere the accent is overridden. |
| `flagpost-mark-reverse.svg` | Light post, lightened green flag. Dark backgrounds. |
| `flagpost-icon-container.svg` | Ink squircle, `rx=14`. App icon, GitHub org avatar, anywhere a bounded tile is required. |

The ground shadow is not optional styling — it is present in the primary mark
and absent in the compact mark, and the switch happens at 32px. Below that size
the ellipse renders as a grey smear rather than a shadow.

---

## 2. Colour

### 2.1 Core values

| Token | Hex | HSL | Role |
|---|---|---|---|
| `--fp-ink` | `#101720` | `hsl(214 33% 9%)` | Post, wordmark, default foreground |
| `--fp-green` | `#1F9E6B` | `hsl(156 67% 37%)` | **Signal green.** The flag. Brand accent. |
| `--fp-green-dark` | `#2CB57C` | `hsl(155 61% 44%)` | Green on dark backgrounds only |
| `--fp-green-text` | `#14795A` | `hsl(162 72% 28%)` | Green used as small text on light |
| `--fp-sheet` | `#E4E7E2` | `hsl(96 9% 90%)` | Reverse-out foreground, light surface |

Signal green is the brand. The other greens are not alternative brand colours —
they are the same colour corrected for context, and using them outside the
context they were defined for is a misuse.

### 2.2 Contrast, measured

These are computed WCAG 2.1 ratios, not estimates. They constrain where each
value may be used.

| Pair | Ratio | Verdict |
|---|---|---|
| `--fp-green` on white | **3.41:1** | Large text (≥24px bold) and graphics only. **Fails** normal body text. |
| `--fp-green` on `--fp-ink` | **5.37:1** | Passes AA for all text. |
| `--fp-green-dark` on `--fp-ink` | **6.90:1** | Passes AA for all text. Preferred on dark. |
| `--fp-green-text` on white | **5.41:1** | Passes AA for all text. Use this for green body copy. |

The practical rule: the wordmark's green "post" is set at 24px+ bold, which
clears the 3:1 graphics/large-text threshold with `--fp-green`. Anything
smaller or lighter than that must switch to `--fp-green-text`.

### 2.3 Relationship to product semantic colour

Flagpost's UI will use green for "flag accepted / challenge solved." The brand
accent and that semantic green are the **same hue family by intention** — the
brand means what the interface means.

Two consequences to hold to:

1. Do not introduce a second, different green for success states. Derive it
   from `--fp-green`.
2. The logo must never be placed adjacent to a solve/success indicator in a way
   that makes it look like a status badge. Keep brand and status in separate
   regions of any layout.

### 2.4 Per-competition accent override

The platform allows organisations to set a custom accent per competition. When
an override is active:

- The **logo does not take the override.** Flagpost's identity stays Flagpost's
  identity inside someone else's competition.
- Where a neutral mark is needed against an unknown accent, use
  `flagpost-mark-mono.svg` with `currentColor` set to the surface's foreground.

This is why the mono variant exists and why it is a first-class asset rather
than an afterthought.

---

## 3. Wordmark

**Typeface:** Space Grotesk, weight 700
**Tracking:** `-0.035em`
**Case:** Sentence case. "Flagpost" — never all-caps, never camel-case.

The wordmark is split at the syllable: **Flag** in `--fp-ink`, **post** in
`--fp-green`. On dark backgrounds, **Flag** takes `--fp-sheet` and **post**
takes `--fp-green-dark`.

The split is the wordmark's whole personality and it is not optional in colour
contexts. In mono contexts the split disappears and the word is set in one
colour — that is the only permitted exception.

```css
.flagpost-wordmark {
  font-family: 'Space Grotesk', system-ui, sans-serif;
  font-weight: 700;
  letter-spacing: -0.035em;
  color: var(--fp-ink);
}
.flagpost-wordmark .post { color: var(--fp-green); }
```

Distribution note: SVG lockups that use live `<text>` depend on the font being
installed. Any lockup shipped as a file (README, press kit, third-party embed)
must have the wordmark **converted to outlines** first.

---

## 4. Lockups

### 4.1 Horizontal (primary)

Mark left, wordmark right, vertically centred on the wordmark's cap height —
not on its bounding box.

- Gap between mark and wordmark: **0.28 × mark height**
- Mark height matches the wordmark's cap height **× 1.6**

This is the default lockup and should be used unless there is a specific reason
not to.

### 4.2 Stacked

Mark above, wordmark below, both centred on a shared vertical axis.
Gap: **0.3 × mark height**. Use only where horizontal space is genuinely
constrained — narrow sidebars, square social avatars.

### 4.3 Mark alone

Permitted once Flagpost is already established in context: app icons, favicons,
loading states, a nav bar where the product name appears elsewhere on screen.
Not for first-impression surfaces.

---

## 5. Clear Space

Minimum clear space on all four sides is **equal to the width of the post** —
6 units at the 64-unit scale, or **9.4% of the mark's height**.

For the horizontal lockup, clear space is measured from the outermost extent of
the combined artwork, including the flag's fly end and the wordmark's final
letterform.

Nothing enters this zone: no text, no rules, no other logos, no container
edges.

---

## 6. Minimum Sizes

| Context | Minimum | Variant required |
|---|---|---|
| Mark alone, screen | 16px | `compact` |
| Mark alone, print | 6mm | `compact` |
| Horizontal lockup, screen | 104px wide | `compact` mark below 32px mark height |
| Horizontal lockup, print | 28mm wide | — |
| App icon / avatar | 512px source | `icon-container` |

Below 16px the swallowtail notch closes up and the mark stops being itself. Do
not ship it smaller — use a single-colour flag glyph or the letter F instead.

---

## 7. Misuse

Do not:

- Recolour the flag to anything other than the defined green values.
- Apply the per-competition accent override to the logo.
- Remove or soften the swallowtail notch.
- Add a stroke, outline, drop shadow, glow, or bevel to any part of the mark.
- Rotate the mark, or angle the flag as though wind-blown.
- Stretch, condense, or otherwise alter the aspect ratio.
- Reposition the flag on the post, or lengthen the post.
- Set the wordmark in a typeface other than Space Grotesk 700.
- Place the primary or reverse mark on a background that leaves the flag below
  3:1 contrast — use mono instead.
- Use the mark as a bullet, a status icon, or a UI affordance. It is a logo.

> **White-labelling (Tier 3 Phase 9).** These rules govern the **Flagpost** mark.
> An installation may replace it site-wide with the operating organisation's own
> logo (Admin → Site settings → Appearance) — the guidance above then applies to *their* asset at
> their discretion, not ours. Flagpost's own attribution is preserved separately
> by the mandatory "Powered by Flagpost" footer, which always uses the primary
> mark per this spec and is not configurable.

---

## 8. Asset Manifest

```
/brand
  /svg
    flagpost-mark-primary.svg
    flagpost-mark-compact.svg
    flagpost-mark-mono.svg
    flagpost-mark-reverse.svg
    flagpost-icon-container.svg
  /motion
    flagpost-plant.css          canonical animation source
    flagpost-mark-animated.svg  self-contained, styles embedded
    FlagpostMark.jsx            React component, session-once
    flagpost-plant.html         vanilla reference implementation
  /lockups          (to produce — outlined text)
    flagpost-lockup-horizontal.svg
    flagpost-lockup-horizontal-reverse.svg
    flagpost-lockup-stacked.svg
  /raster           (to produce)
    favicon.ico         16 / 32 / 48
    icon-192.png
    icon-512.png
    social-card.png     1200 × 630
  LOGO-SPEC.md      (this file)
```

---

## 9. Source

### Primary mark

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Flagpost">
  <ellipse cx="22" cy="55" rx="12" ry="3.2" fill="#101720" opacity="0.16"/>
  <rect x="19" y="6" width="6" height="49" rx="3" fill="#101720"/>
  <path d="M25 9 H46 L40.5 16 L46 23 H25 Z" fill="#1F9E6B"/>
</svg>
```

### Compact mark

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Flagpost">
  <rect x="19" y="6" width="6" height="49" rx="3" fill="#101720"/>
  <path d="M25 9 H46 L40.5 16 L46 23 H25 Z" fill="#1F9E6B"/>
</svg>
```

### Mono mark

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Flagpost">
  <rect x="19" y="6" width="6" height="49" rx="3" fill="currentColor"/>
  <path d="M25 9 H46 L40.5 16 L46 23 H25 Z" fill="currentColor"/>
</svg>
```

### Reverse mark

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Flagpost">
  <rect x="19" y="6" width="6" height="49" rx="3" fill="#E4E7E2"/>
  <path d="M25 9 H46 L40.5 16 L46 23 H25 Z" fill="#2CB57C"/>
</svg>
```

### Icon container

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Flagpost">
  <rect width="64" height="64" rx="14" fill="#101720"/>
  <rect x="20" y="13" width="6" height="38" rx="3" fill="#E4E7E2"/>
  <path d="M26 16 H46 L40.5 22.5 L46 29 H26 Z" fill="#2CB57C"/>
</svg>
```

---

## 10. Token Export

For the design system's `@theme` layer:

```css
@theme {
  --color-fp-ink:        hsl(214 33% 9%);
  --color-fp-green:      hsl(156 67% 37%);
  --color-fp-green-dark: hsl(155 61% 44%);
  --color-fp-green-text: hsl(162 72% 28%);
  --color-fp-sheet:      hsl(96 9% 90%);
}
```

These are the **brand** values. The design system's semantic tokens
(`--color-primary`, `--color-success`, and so on) should reference these rather
than redeclaring hex values, so that the relationship between brand green and
success green stays explicit in code rather than being a coincidence someone
later "fixes."

---

## 11. Motion — "Plant"

The mark has one entrance animation. It is called **Plant**, and it is the only
sanctioned motion treatment of the logo.

The sequence: the post falls in and settles with a soft overshoot, the ground
takes it, and the flag unfurls from the post outward. It reads as a flag being
driven into ground and claiming a position — the same idea the static mark
encodes, played out in time.

### 11.1 Timing

| Element | Duration | Delay | Easing | Property |
|---|---|---|---|---|
| Post | 520ms | 0 | `cubic-bezier(0.34, 1.4, 0.5, 1)` | `translateY(-34px → 0)`, `opacity 0 → 1` |
| Ground | 340ms | 300ms | `ease-out` | `scale(0.2 → 1)`, `opacity 0 → 0.16` |
| Flag | 420ms | 420ms | `cubic-bezier(0.2, 0.9, 0.3, 1.15)` | `scaleX(0 → 1)` |

**Total runtime: 840ms.** This is a ceiling, not a target to grow into. Past
about a second on a sign-in screen, motion stops being personality and starts
being a wait.

Transform origins are load-bearing and must be set with
`transform-box: fill-box`:

- Post — `bottom center` (it settles onto the ground, not through it)
- Flag — `left center` (it unfurls away from the post, never toward it)
- Ground — `center`

### 11.2 Rules

- **Once per session, not once per page load.** A failed sign-in re-renders the
  page; nobody should watch the flag plant itself four times while fighting a
  password manager. Guard with a `sessionStorage` key (`fp:mark-played`).
- **Transform and opacity only.** No animated width, height, or layout
  properties — the mark reserves its full box from first paint and causes no
  layout shift.
- **Never gate content on it.** Form inputs are interactive immediately. The
  animation is decoration running alongside the page, not a loading state.
- **The ground fades to 16%, not to full.** It is a shadow. Below 32px it is
  dropped entirely and only the post and flag animate.
- **No looping, ever.** This is an entrance, not an idle state.
- **Not a status indicator.** The animation must never be reused to signal a
  solve, a submission, or any other event. It marks arrival at Flagpost and
  nothing else.

### 11.3 Reduced motion

Under `prefers-reduced-motion: reduce`, the mark renders in its **final state
with no movement at all** — not a shortened or gentler version of the same
motion. A user who has asked for no animation gets no animation.

This is implemented in CSS rather than JavaScript so it holds even if the
component's script fails to run.

### 11.4 Where it plays

Sanctioned: sign-in, registration, the marketing site hero, and the first paint
of the app shell after authentication.

Not sanctioned: navigation bars, favicons, loading spinners, empty states,
modals, or anywhere the mark appears more than once on a screen.

### 11.5 Implementation

Three artefacts ship with this spec:

| File | Use |
|---|---|
| `motion/flagpost-plant.css` | The keyframes and classes. Framework-agnostic. |
| `motion/FlagpostMark.tsx` | React component with the session guard and automatic compact-size handling. |
| `svg/flagpost-mark-animated.svg` | Self-contained animated SVG with the CSS inlined — for READMEs and anywhere a component can't be used. |

Markup contract for the CSS:

```html
<svg class="fp-mark fp-mark--plant fp-mark--play" viewBox="0 0 64 64">
  <ellipse class="fp-ground" cx="22" cy="55" rx="12" ry="3.2" fill="#101720" opacity="0.16"/>
  <rect    class="fp-post" x="19" y="6" width="6" height="49" rx="3" fill="#101720"/>
  <path    class="fp-flag" d="M25 9 H46 L40.5 16 L46 23 H25 Z" fill="#1F9E6B"/>
</svg>
```

Without `fp-mark--play` the mark renders in its final static state, so the same
markup serves both cases. To replay, remove the class, force a reflow
(`void el.offsetWidth`), then re-add it.

---

## 12. Open Items

Honest list of what this spec does not yet settle:

- **Stacked and horizontal lockup files** are specified but not yet produced as
  outlined SVG.
- **Space Grotesk licensing** for embedded/distributed use should be confirmed
  before the wordmark ships in a press kit. It is an open-licence face, but the
  specific terms should be read rather than assumed.
- **Favicon at 16px** needs visual testing in a real browser tab against both
  light and dark tab bars; the notch behaviour at that size is predicted here,
  not verified.
- **Motion at 42px** — the size the mark actually ships at on the sign-in
  screen — has been designed but not tested on a real display. Fast motion on a
  small mark can read as a flicker rather than a gesture. Verify before launch.
- **Wordmark motion** is deliberately unspecified. The mark plants; the
  wordmark currently does not move. If a treatment is wanted later it should be
  a fade, not a second competing gesture.
