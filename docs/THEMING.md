# Custom brand themes

Flagpost ships a set of built-in palettes and a custom-accent colour, and lets an
administrator upload a **custom theme** — a complete pack of the design tokens the
UI runs on — so an organisation can make the whole surface (backgrounds, cards,
text, brand colour, status colours) feel like *theirs*. Custom themes are
**additive**: they appear alongside the built-in palettes, they don't replace
them, and selecting one is a one-click change with no rebuild or redeploy.

This is **site-wide** (ADR-0011) and **admin-only**: themes are managed under
**Admin → Site settings → Appearance → Custom themes**, and the active theme is
whatever the site's *default palette* is set to (a built-in palette id or a
custom theme id). Members' per-user palette override still works and can pick a
built-in over the brand default.

> A theme is **a token pack only** — a fixed set of colours. It is deliberately
> *not* arbitrary CSS, JavaScript, fonts, or markup. That boundary is what keeps
> it safe (no injection surface) and keeps every install's layout consistent.

## Authoring a theme

Two ways, both feeding the same validated model:

- **In-app editor** — *New theme* opens a colour editor grouped by role
  (Surfaces / Text / Actions / Status / Borders) with a live preview. Give it a
  slug **id** (immutable, e.g. `acme-dark`), a display **name**, and a **mode**
  (`dark` or `light`), then set each colour.
- **Upload a theme file** — author a JSON file offline (below) and upload it;
  it loads into the editor for review before saving. **Download** exports any
  theme to the same format to share or version it.

Then set it as the site default in the palette picker to apply it.

## Theme file format

A theme file is JSON with four fields:

```json
{
  "id": "acme-dark",
  "name": "Acme — Dark",
  "mode": "dark",
  "tokens": {
    "background": "#0f1420",
    "foreground": "#e6ebf5",
    "card": "#151b2b",
    "card-foreground": "#e6ebf5",
    "popover": "#151b2b",
    "popover-foreground": "#e6ebf5",
    "primary": "#4f8cff",
    "primary-foreground": "#0f1420",
    "secondary": "#1e2740",
    "secondary-foreground": "#e6ebf5",
    "muted": "#1a2233",
    "muted-foreground": "#8a99b8",
    "accent": "#1e2740",
    "accent-foreground": "#e6ebf5",
    "destructive": "#f2555a",
    "destructive-foreground": "#0f1420",
    "success": "#34d399",
    "success-foreground": "#0f1420",
    "warning": "#fbbf24",
    "warning-foreground": "#0f1420",
    "border": "#263149",
    "input": "#263149",
    "ring": "#4f8cff"
  }
}
```

Rules (enforced on save — the server rejects anything else):

- `id` — a lowercase slug (`^[a-z][a-z0-9-]{1,31}$`), immutable, and not one of
  the reserved built-in palette ids (`harbor`, `eclipse`, `umbra`, `daybreak`,
  `sandstone`).
- `mode` — `dark` or `light`. It sets the `data-mode` on the page, so pick the
  one your surfaces actually are.
- `tokens` — **every** token below, each a `#RRGGBB` hex value. No extra keys,
  no other value forms.

## Token reference

Each token is a colour; foreground tokens are the text/icon colour that sits on
the matching surface, so keep them high-contrast against it.

| Token | Colours |
|---|---|
| `background` / `foreground` | The page canvas and its body text. |
| `card` / `card-foreground` | Raised surfaces (panels, cards) and their text. |
| `popover` / `popover-foreground` | Menus, dropdowns, tooltips and their text. |
| `primary` / `primary-foreground` | The brand action colour (buttons, active nav, links) and text on it. |
| `secondary` / `secondary-foreground` | Secondary surfaces/controls and their text. |
| `muted` / `muted-foreground` | Subtle fills; muted/secondary text (captions, hints). |
| `accent` / `accent-foreground` | Hover/selected tints and their text. |
| `destructive` / `destructive-foreground` | Danger actions/badges and their text. |
| `success` / `success-foreground` | Success/solve states and their text. |
| `warning` / `warning-foreground` | Warnings and their text. |
| `border` | Hairline borders and dividers. |
| `input` | Form-control borders. |
| `ring` | Focus rings (usually your `primary`). |

Tips: aim for WCAG-AA contrast between each surface and its foreground; the mode
you pick should match your `background` (dark surfaces → `mode: "dark"`). The
editor's preview shows a card, primary/accent chips, and the status colours so
you can sanity-check contrast before saving.

## Notes

- **Portability** — themes are carried by the export/import backup (branding is
  portable), so moving an install keeps its themes.
- **Deleting** — you can't delete the *active* theme (switch first). The 2–3
  example themes that ship are ordinary editable/deletable rows.
- **Not in scope (yet)** — per-competition themes (theming is site-wide,
  ADR-0011), custom fonts, and letting members pick a custom theme as a personal
  override.
