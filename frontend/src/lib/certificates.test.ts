import { describe, expect, it } from "vitest";

import {
  CERT_DEFAULT_TEXT,
  certFontFaceCss,
  certFontFamily,
  certPresetUrl,
  customFontCssFamily,
  customFontFaceCss,
  newCertElement,
  snapElementPosition,
} from "@/lib/certificates";

// Editor↔render parity (ADR-0027) rides on these helpers building the same font
// set + coordinate defaults the server renderer uses.
describe("certificate helpers", () => {
  it("falls back to the matching generic font family", () => {
    expect(certFontFamily("serif")).toContain("serif");
    expect(certFontFamily("mono")).toContain("monospace");
    expect(certFontFamily("sans")).toContain("sans-serif");
    expect(certFontFamily(undefined)).toContain("serif");
  });

  it("emits four @font-face rules per bundled font", () => {
    const css = certFontFaceCss([
      { id: "serif", label: "Serif" },
      { id: "sans", label: "Sans" },
    ]);
    expect((css.match(/@font-face/g) ?? []).length).toBe(8);
    expect(css).toContain("/api/certificate-assets/fonts/serif/bolditalic");
    expect(css).toContain("font-weight:700");
    expect(css).toContain("font-style:italic");
  });

  it("builds a preset background url", () => {
    expect(certPresetUrl("classic")).toContain(
      "/api/certificate-assets/backgrounds/classic",
    );
  });

  it("new elements carry sane defaults; images have no text colour", () => {
    const token = newCertElement("token", "serif", { token: "points" });
    expect(token).toMatchObject({
      type: "token",
      token: "points",
      align: "center",
      color: CERT_DEFAULT_TEXT,
    });
    expect(token.x).toBeGreaterThanOrEqual(0);
    expect(newCertElement("image", "serif", { image_key: "k" }).color).toBeUndefined();
  });

  it("resolves a custom font ref to a CSS-safe family", () => {
    const ref = "custom:1e2d3c4b-5a69-4788-9abc-def012345678";
    expect(customFontCssFamily(ref)).toBe("cert-custom-1e2d3c4b-5a69-4788-9abc-def012345678");
    expect(certFontFamily(ref)).toContain(customFontCssFamily(ref));
    const css = customFontFaceCss(ref, "blob:x", "otf");
    expect((css.match(/@font-face/g) ?? []).length).toBe(4);
    expect(css).toContain("format('opentype')");
    expect(css).toContain("src:url('blob:x')");
  });
});

// Alignment snapping (MS-Word-lite): edges/centre of the dragged box snap to the
// canvas thirds and to other elements' anchors, within a % threshold.
describe("snapElementPosition", () => {
  it("snaps the horizontal centre to the canvas centre", () => {
    // width 40 → centre at x+20; near 50 means x≈30. Raw 30.8 → centre 50.8.
    const r = snapElementPosition(30.8, 10, 40, []);
    expect(r.x).toBeCloseTo(30, 5); // centre pulled to 50
    expect(r.guideX).toBe(50);
  });

  it("snaps the left edge to another element's left edge", () => {
    const r = snapElementPosition(20.5, 60, 30, [{ x: 20, y: 5, width: 10 }]);
    expect(r.x).toBeCloseTo(20, 5);
    expect(r.guideX).toBe(20);
  });

  it("snaps the top edge to the canvas middle", () => {
    const r = snapElementPosition(70, 49.4, 20, []);
    expect(r.y).toBeCloseTo(50, 5);
    expect(r.guideY).toBe(50);
  });

  it("passes the raw position through when nothing is within range", () => {
    const r = snapElementPosition(33, 27, 12, [{ x: 80, y: 80, width: 10 }]);
    expect(r.x).toBe(33);
    expect(r.y).toBe(27);
    expect(r.guideX).toBeNull();
    expect(r.guideY).toBeNull();
  });

  it("keeps snapped positions within the canvas", () => {
    const r = snapElementPosition(99.7, 0.2, 10, []); // left near 100, top near 0
    expect(r.x).toBeLessThanOrEqual(100);
    expect(r.y).toBeGreaterThanOrEqual(0);
  });
});
