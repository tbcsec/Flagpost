// Theme registry + colour math for site-wide theming (ARCHITECTURE.md §9).
//
// Source of visual truth for the palettes/accents the Admin → Site settings → Appearance page
// offers and the ThemeApplier applies. A PALETTE owns surface colours (defined
// as full token sets in globals.css, keyed by `data-palette`); the ACCENT owns
// action colours — one hue written only into `--primary` / `--ring` (+ their
// foreground) at the root, leaving surfaces and the brand `--success` green
// alone (the logo never takes the accent — LOGO-SPEC §7).

export type PaletteMode = "dark" | "light";

export interface PalettePreset {
  id: string;
  label: string;
  description: string;
  mode: PaletteMode;
  // Small swatch used by the picker card (resolved CSS colours, not tokens).
  swatch: { bg: string; card: string; border: string; text: string };
}

// Keep these ids in sync with the `[data-palette="…"]` blocks in globals.css and
// the backend's format validation (a slug). Order = display order.
export const PALETTES: PalettePreset[] = [
  {
    id: "harbor",
    label: "Harbor",
    description: "Deep blue-slate — calm and professional (default)",
    mode: "dark",
    swatch: { bg: "hsl(213 41% 11%)", card: "hsl(213 38% 14%)", border: "hsl(213 30% 23%)", text: "hsl(210 34% 96%)" },
  },
  {
    id: "eclipse",
    label: "Eclipse",
    description: "Near-black with a faint violet cast — minimal",
    mode: "dark",
    swatch: { bg: "hsl(250 12% 8%)", card: "hsl(250 11% 11%)", border: "hsl(250 9% 19%)", text: "hsl(250 14% 95%)" },
  },
  {
    id: "umbra",
    label: "Umbra",
    description: "Warm graphite — softer than navy",
    mode: "dark",
    swatch: { bg: "hsl(28 9% 9%)", card: "hsl(28 8% 12%)", border: "hsl(28 8% 20%)", text: "hsl(30 12% 94%)" },
  },
  {
    id: "daybreak",
    label: "Daybreak",
    description: "Crisp cool white with slate text",
    mode: "light",
    swatch: { bg: "hsl(210 40% 99%)", card: "hsl(0 0% 100%)", border: "hsl(214 32% 88%)", text: "hsl(213 40% 12%)" },
  },
  {
    id: "sandstone",
    label: "Sandstone",
    description: "Warm paper — easy on the eyes",
    mode: "light",
    swatch: { bg: "hsl(40 36% 96%)", card: "hsl(42 44% 98%)", border: "hsl(40 24% 85%)", text: "hsl(28 24% 15%)" },
  },
];

export interface AccentPreset {
  id: string;
  label: string;
  description: string;
  hex: string; // shown as the swatch; "signal" also resolves to the palette default
}

// The default accent ("signal") is the brand green each palette already ships as
// its `--primary`; selecting it means "no override" so the palette's mode-correct
// green shows through. Every other accent overrides `--primary`/`--ring`.
export const DEFAULT_ACCENT = "signal";
export const DEFAULT_PALETTE = "harbor";
export const DEFAULT_PLATFORM_NAME = "Flagpost";

export const ACCENTS: AccentPreset[] = [
  { id: "signal", label: "Signal", description: "Flagpost brand green (default)", hex: "#1F9E6B" },
  { id: "ultraviolet", label: "Ultraviolet", description: "Electric purple", hex: "#7C5CFF" },
  { id: "azure", label: "Azure", description: "Clear blue", hex: "#3B82F6" },
  { id: "ember", label: "Ember", description: "Warm red-orange", hex: "#F0553B" },
  { id: "gold", label: "Gold", description: "Bright amber", hex: "#E0A500" },
];

export interface BackgroundPreset {
  id: string;
  label: string;
  description: string;
  // Whether it responds to the cursor — surfaced on the picker card.
  interactive: boolean;
}

// The front-door animated backgrounds (#195) — a third theming axis alongside
// palette + accent, shown only on the out-of-shell pages and only on dark
// palettes. "none" (the default) is today's flat ground. Each id maps to a
// renderer in lib/backgrounds.ts; keep the two in sync.
export const DEFAULT_BACKGROUND = "none";
export const BACKGROUNDS: BackgroundPreset[] = [
  { id: "none", label: "None", description: "Flat brand ground (default)", interactive: false },
  { id: "aurora", label: "Aurora", description: "Soft ribbons of light drifting behind the card", interactive: false },
  { id: "gradient", label: "Gradient wash", description: "A slow, calm colour field from your accent", interactive: false },
  { id: "constellation", label: "Constellation", description: "A living particle network that reacts to the cursor", interactive: true },
];

const ACCENTS_BY_ID = new Map(ACCENTS.map((a) => [a.id, a]));
const PALETTE_IDS = new Set(PALETTES.map((p) => p.id));

export function paletteMode(id: string): PaletteMode {
  return PALETTES.find((p) => p.id === id)?.mode ?? "dark";
}

export function isKnownPalette(id: string | null | undefined): id is string {
  return typeof id === "string" && PALETTE_IDS.has(id);
}

/** True for a custom hex accent like `#A855F7` (vs. a preset id). */
export function isCustomAccent(accent: string): boolean {
  return /^#[0-9a-fA-F]{6}$/.test(accent);
}

/** The swatch colour to show for any stored accent value (preset or custom). */
export function accentSwatchHex(accent: string): string {
  if (isCustomAccent(accent)) return accent;
  return ACCENTS_BY_ID.get(accent)?.hex ?? ACCENTS_BY_ID.get(DEFAULT_ACCENT)!.hex;
}

/** Resolve a stored accent to the hex we override with, or `null` when it's the
 *  default "signal" (palette keeps its own brand-green primary — no override). */
export function resolveAccentHex(accent: string): string | null {
  if (accent === DEFAULT_ACCENT) return null;
  if (isCustomAccent(accent)) return accent.toUpperCase();
  return ACCENTS_BY_ID.get(accent)?.hex ?? null;
}

// --- Colour math (pure, unit-tested) ---------------------------------------

/** Parse `#RRGGBB` → [r,g,b] in 0..1. Returns null on a malformed hex. */
function parseHex(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => c / 255) as [
    number,
    number,
    number,
  ];
}

/** `#RRGGBB` → an `"H S% L%"` channel triple for a `--…` HSL token. */
export function hexToHslChannels(hex: string): string {
  const rgb = parseHex(hex);
  if (!rgb) return "0 0% 0%";
  const [r, g, b] = rgb;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let h = 0;
  let s = 0;
  const d = max - min;
  if (d !== 0) {
    s = d / (1 - Math.abs(2 * l - 1));
    switch (max) {
      case r:
        h = ((g - b) / d) % 6;
        break;
      case g:
        h = (b - r) / d + 2;
        break;
      default:
        h = (r - g) / d + 4;
    }
    h *= 60;
    if (h < 0) h += 360;
  }
  return `${Math.round(h)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
}

// Foreground candidates as channel triples: near-white, or the brand ink.
const FG_WHITE = "0 0% 100%";
const FG_INK = "222 47% 11%";

/** Pick the on-accent text colour (white or ink) by YIQ perceived brightness.
 *  This matches the button convention — white on saturated blue/purple/green,
 *  dark only on genuinely light accents (gold, pastels) — better than a raw
 *  max-contrast rule, which would put dark text on a mid-tone blue. */
export function accentForegroundChannels(hex: string): string {
  const rgb = parseHex(hex);
  if (!rgb) return FG_WHITE;
  const [r, g, b] = rgb.map((c) => c * 255);
  const brightness = (r * 299 + g * 587 + b * 114) / 1000;
  return brightness > 150 ? FG_INK : FG_WHITE;
}

// --- Custom brand themes (#323) --------------------------------------------

// The complete design-token set a custom theme defines — must match the backend
// utils.theme_tokens.THEME_TOKENS and the [data-palette] blocks in globals.css.
export const THEME_TOKENS = [
  "background", "foreground",
  "card", "card-foreground",
  "popover", "popover-foreground",
  "primary", "primary-foreground",
  "secondary", "secondary-foreground",
  "muted", "muted-foreground",
  "accent", "accent-foreground",
  "destructive", "destructive-foreground",
  "success", "success-foreground",
  "warning", "warning-foreground",
  "border", "input", "ring",
] as const;

export const THEME_TOKEN_VARS = THEME_TOKENS.map((t) => `--${t}`);

/** A custom theme preset's runtime shape — the active theme embedded in the
 *  public site-settings payload, or one being previewed in the editor. `tokens`
 *  maps each THEME_TOKENS key to a `#RRGGBB` value. */
export interface CustomTheme {
  id: string;
  mode: PaletteMode;
  tokens: Record<string, string>;
}

// --- Applying to the DOM ----------------------------------------------------

export interface ThemeChoice {
  palette: string;
  accent: string;
  /** The active custom theme (if any). Applied when the selected `palette` is
   *  this theme's id — i.e. a preset is the active choice, not a built-in. */
  customTheme?: CustomTheme | null;
}

/** The fully-resolved theme: palette id + mode, plus either the accent channel
 *  overrides (built-in palette) or a full `vars` token map (custom theme). This
 *  is applied to <html> by ThemeApplier *and* carried in the `fp_brand` cookie
 *  the server layout paints the initial HTML from (#362), so both paths apply
 *  identical values with no colour math at load. */
export interface AppliedTheme {
  palette: string;
  mode: PaletteMode;
  primary: string | null;
  primaryForeground: string | null;
  ring: string | null;
  /** `--token` → `"H S% L%"` for every design token, set when a custom theme is
   *  active. Undefined for a built-in palette. */
  vars?: Record<string, string>;
}

export function resolveTheme({ palette, accent, customTheme }: ThemeChoice): AppliedTheme {
  // A custom theme is active only when the selected palette *is* that preset —
  // a per-user override to a built-in still wins (its id won't match).
  if (customTheme && customTheme.id === palette) {
    const vars: Record<string, string> = {};
    for (const token of THEME_TOKENS) {
      const hex = customTheme.tokens[token];
      if (hex) vars[`--${token}`] = hexToHslChannels(hex);
    }
    return {
      palette: customTheme.id,
      mode: customTheme.mode,
      // The theme's own primary/ring tokens are authoritative — the accent
      // control doesn't compose over a custom theme.
      primary: null,
      primaryForeground: null,
      ring: null,
      vars,
    };
  }
  const paletteId = isKnownPalette(palette) ? palette : DEFAULT_PALETTE;
  const hex = resolveAccentHex(accent);
  return {
    palette: paletteId,
    mode: paletteMode(paletteId),
    primary: hex === null ? null : hexToHslChannels(hex),
    primaryForeground: hex === null ? null : accentForegroundChannels(hex),
    ring: hex === null ? null : hexToHslChannels(hex),
  };
}

/** The inline CSS custom-properties a resolved theme sets on the root — the
 *  single mapping shared by the client applier below and the server-rendered
 *  `<html style>` (#362), so the two can never drift. */
export function appliedThemeVars(t: AppliedTheme): Record<string, string> {
  if (t.vars) return { ...t.vars };
  if (t.primary === null || t.primary === undefined) {
    // Default "signal": let the palette's own brand-green primary show through.
    return {};
  }
  return {
    "--primary": t.primary,
    "--ring": t.ring ?? t.primary,
    "--primary-foreground": t.primaryForeground ?? "0 0% 100%",
  };
}

/** Apply a resolved theme to a root element (usually <html>). Idempotent: every
 *  managed token is cleared first, so switching between a custom theme and a
 *  built-in palette never leaves stale inline vars behind. */
export function applyResolvedTheme(root: HTMLElement, t: AppliedTheme): void {
  root.dataset.palette = t.palette;
  root.dataset.mode = t.mode;
  // Reset all managed token vars → the [data-palette] CSS block governs again.
  for (const v of THEME_TOKEN_VARS) root.style.removeProperty(v);
  for (const [k, val] of Object.entries(appliedThemeVars(t))) {
    root.style.setProperty(k, val);
  }
}

/** Resolve + apply in one step. */
export function applyTheme(root: HTMLElement, choice: ThemeChoice): void {
  applyResolvedTheme(root, resolveTheme(choice));
}
