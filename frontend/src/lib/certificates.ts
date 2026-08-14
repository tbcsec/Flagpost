// Certificate editor helpers + constants (#219, ADR-0027). Lives in lib/ (not a
// component) so the literal hex defaults here don't trip the §9 no-raw-hex rule,
// and so the @font-face / preset URLs are built in one place. Imports apiAssetUrl
// one-way (lib/api never imports this) — no cycle.

import { apiAssetUrl } from "@/lib/api";
import type { CertElement, CertManifestFont } from "@/lib/types";

// Editor defaults (data values, not component style literals).
export const CERT_DEFAULT_BG = "#ffffff";
export const CERT_DEFAULT_TEXT = "#111827";
export const CERT_ACCENT = "#b8985a";

// Bumped whenever the bundled presets or fonts change. The asset routes are
// long-cached (they're static per build), so this query param busts a browser's
// stale — or transiently-broken — cached copy without a hard reload.
export const CERT_ASSET_VERSION = 4;

const GENERIC_FALLBACK: Record<string, string> = {
  serif: "serif",
  sans: "sans-serif",
  mono: "monospace",
};

/** A CSS-safe @font-face family token for an organiser-uploaded font ref
 *  (`custom:<uuid>` → `cert-custom-<uuid>`). */
export function customFontCssFamily(id: string): string {
  return `cert-${id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

/** CSS font-family for a bundled or custom font id, falling back to the matching
 *  generic if the face fails to load (e.g. cross-origin in dev). */
export function certFontFamily(id: string | undefined): string {
  const fid = id ?? "serif";
  if (fid.startsWith("custom:")) return `'${customFontCssFamily(fid)}', sans-serif`;
  return `'cert-${fid}', ${GENERIC_FALLBACK[fid] ?? "sans-serif"}`;
}

/** @font-face CSS for a custom font, loaded from an (auth'd) object URL. All four
 *  weight/style slots point at the single uploaded file, so the browser uses its
 *  real glyphs for bold/italic too — matching Pillow, which does no faux styling
 *  (one file per custom font; parity with the render, ADR-0027). */
export function customFontFaceCss(id: string, url: string, format: string): string {
  const family = customFontCssFamily(id);
  const cssFormat = format === "otf" ? "opentype" : "truetype";
  return FONT_VARIANTS.map(
    ([, weight, style]) =>
      `@font-face{font-family:'${family}';` +
      `src:url('${url}') format('${cssFormat}');` +
      `font-weight:${weight};font-style:${style};font-display:swap;}`,
  ).join("\n");
}

const FONT_VARIANTS: [string, number, string][] = [
  ["regular", 400, "normal"],
  ["bold", 700, "normal"],
  ["italic", 400, "italic"],
  ["bolditalic", 700, "italic"],
];

/** @font-face CSS loading the *same* bundled TTFs the server renders with, so
 *  the editor canvas approximates the downloaded PNG (ADR-0027 parity). */
export function certFontFaceCss(fonts: CertManifestFont[]): string {
  return fonts
    .flatMap((f) =>
      FONT_VARIANTS.map(
        ([variant, weight, style]) =>
          `@font-face{font-family:'cert-${f.id}';` +
          `src:url('${apiAssetUrl(`/api/certificate-assets/fonts/${f.id}/${variant}?v=${CERT_ASSET_VERSION}`)}') format('truetype');` +
          `font-weight:${weight};font-style:${style};font-display:swap;}`,
      ),
    )
    .join("\n");
}

/** A code-drawn preset background, served as a PNG by the backend (one source of
 *  truth with the renderer). */
export function certPresetUrl(
  id: string,
  accent?: string | null,
  base?: string | null,
): string {
  const params = new URLSearchParams({ v: String(CERT_ASSET_VERSION) });
  if (accent) params.set("accent", accent);
  if (base) params.set("base", base);
  return apiAssetUrl(`/api/certificate-assets/backgrounds/${id}?${params.toString()}`);
}

// --- Alignment snapping (MS-Word-lite) --------------------------------------

export interface SnapBox {
  x: number;
  y: number;
  width: number;
}

export interface SnapResult {
  x: number;
  y: number;
  /** Canvas-% position of the active vertical / horizontal guide line, or null. */
  guideX: number | null;
  guideY: number | null;
}

const snapClamp = (v: number) => Math.max(0, Math.min(100, v));

/** Snap a dragged element's proposed position to nearby alignment targets: the
 *  canvas left/centre/right + top/middle/bottom, and other elements' edges. Its
 *  left/centre/right edges snap on X; its top edge snaps on Y (text height is
 *  unknown at edit time). Pure, so it's unit-tested directly. Thresholds are in
 *  canvas %; a separate ``thresholdY`` lets the caller scale the vertical zone by
 *  the aspect ratio so the *pixel* tolerance matches X (the canvas isn't square).
 *  When nothing is within range the raw position passes through. */
export function snapElementPosition(
  rawX: number,
  rawY: number,
  width: number,
  others: SnapBox[],
  threshold = 1.2,
  thresholdY = threshold,
): SnapResult {
  const xTargets = [0, 50, 100];
  for (const o of others) xTargets.push(o.x, o.x + o.width / 2, o.x + o.width);
  const xAnchors = [rawX, rawX + width / 2, rawX + width];
  let bestDX: number | null = null;
  let guideX: number | null = null;
  for (const anchor of xAnchors) {
    for (const t of xTargets) {
      const d = t - anchor;
      if (Math.abs(d) <= threshold && (bestDX === null || Math.abs(d) < Math.abs(bestDX))) {
        bestDX = d;
        guideX = t;
      }
    }
  }

  const yTargets = [0, 50, 100];
  for (const o of others) yTargets.push(o.y);
  let bestDY: number | null = null;
  let guideY: number | null = null;
  for (const t of yTargets) {
    const d = t - rawY;
    if (Math.abs(d) <= thresholdY && (bestDY === null || Math.abs(d) < Math.abs(bestDY))) {
      bestDY = d;
      guideY = t;
    }
  }

  return {
    x: snapClamp(bestDX === null ? rawX : rawX + bestDX),
    y: snapClamp(bestDY === null ? rawY : rawY + bestDY),
    guideX: bestDX === null ? null : guideX,
    guideY: bestDY === null ? null : guideY,
  };
}

/** A fresh, correctly-defaulted element for the "add element" actions. */
export function newCertElement(
  type: CertElement["type"],
  defaultFont: string,
  extra: Partial<CertElement> = {},
): CertElement {
  return {
    type,
    x: 25,
    y: 45,
    width: 50,
    font: defaultFont,
    font_size: 6,
    color: type === "text" || type === "token" ? CERT_DEFAULT_TEXT : undefined,
    align: "center",
    bold: false,
    italic: false,
    ...extra,
  };
}
