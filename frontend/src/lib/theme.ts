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

// --- Applying to the DOM ----------------------------------------------------

export interface ThemeChoice {
  palette: string;
  accent: string;
}

/** The fully-resolved theme: palette id + mode, and the accent channel overrides
 *  (null when the default "signal" accent keeps each palette's own primary). This
 *  is what gets applied to <html> *and* cached for the no-flash inline script, so
 *  both paths apply identical values with no colour math at load. */
export interface AppliedTheme {
  palette: string;
  mode: PaletteMode;
  primary: string | null;
  primaryForeground: string | null;
  ring: string | null;
}

export function resolveTheme({ palette, accent }: ThemeChoice): AppliedTheme {
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

/** Apply a resolved theme to a root element (usually <html>): set the palette
 *  attributes and override / clear the accent channels. Idempotent. */
export function applyResolvedTheme(root: HTMLElement, t: AppliedTheme): void {
  root.dataset.palette = t.palette;
  root.dataset.mode = t.mode;
  if (t.primary === null) {
    // Default "signal": let each palette's own brand-green primary show through.
    root.style.removeProperty("--primary");
    root.style.removeProperty("--primary-foreground");
    root.style.removeProperty("--ring");
    return;
  }
  root.style.setProperty("--primary", t.primary);
  root.style.setProperty("--ring", t.ring ?? t.primary);
  root.style.setProperty("--primary-foreground", t.primaryForeground ?? "0 0% 100%");
}

/** Resolve + apply in one step. */
export function applyTheme(root: HTMLElement, choice: ThemeChoice): void {
  applyResolvedTheme(root, resolveTheme(choice));
}
