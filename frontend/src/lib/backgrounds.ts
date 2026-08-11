// Canvas engine for the front-door animated backgrounds (#195). Pure logic, no
// React — mirroring the lib/live.ts split, so the colour math and the style
// registry are unit-testable without mounting a canvas.
//
// Colours arrive as CSS HSL channel triples ("H S% L%") read at runtime from
// the resolved `--background` (base) and `--primary` (accent) custom
// properties, so a background tracks whatever palette + accent the operator
// chose — the default "signal" green and any custom accent alike — with no raw
// hex in a component (§9 / the no-raw-hex ESLint rule).

export const BACKGROUND_IDS = ["aurora", "gradient", "constellation"] as const;
export type BackgroundId = (typeof BACKGROUND_IDS)[number];

/** Whether a stored `background_style` slug is one we animate ("none" and any
 *  unknown value are flat — the frontend is the allowlist). */
export function isAnimatedBackground(style: string): style is BackgroundId {
  return (BACKGROUND_IDS as readonly string[]).includes(style);
}

export interface Hsl {
  h: number;
  s: number;
  l: number;
}

/** Parse a `"H S% L%"` channel triple (the shape our `--…` colour tokens hold)
 *  into numbers, falling back when the value is missing or malformed. */
export function parseHslChannels(triple: string, fallback: Hsl): Hsl {
  const m = /(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)%\s+(-?\d+(?:\.\d+)?)%/.exec(
    (triple ?? "").trim(),
  );
  if (!m) return fallback;
  return { h: +m[1], s: +m[2], l: +m[3] };
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** An `hsla()` string from a base colour with optional lightness/hue deltas —
 *  legacy comma syntax for the widest canvas support. */
function col(c: Hsl, a: number, dl = 0, dh = 0): string {
  const h = (((c.h + dh) % 360) + 360) % 360;
  const l = clamp(c.l + dl, 0, 100);
  return `hsla(${Math.round(h)}, ${Math.round(c.s)}%, ${Math.round(l)}%, ${a})`;
}

export interface BackgroundColors {
  base: Hsl;
  accent: Hsl;
}

export interface BackgroundScene {
  draw(t: number): void;
  resize(): void;
  setColors(colors: BackgroundColors): void;
  setPointer(x: number, y: number, on: boolean): void;
}

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

/** Build a background renderer over a canvas. Stateful (owns particles, DPR and
 *  pointer) but framework-free; the caller drives `draw(t)` from rAF and feeds
 *  fresh colours via `setColors` when the theme changes. `thumb` shrinks the
 *  work for the settings-page previews. */
export function createBackgroundScene(
  canvas: HTMLCanvasElement,
  style: BackgroundId,
  colors: BackgroundColors,
  opts: { thumb?: boolean } = {},
): BackgroundScene {
  const ctx = canvas.getContext("2d")!;
  const thumb = !!opts.thumb;
  let w = 0;
  let h = 0;
  let dpr = 1;
  let cols = colors;
  let parts: Particle[] = [];
  const pointer = { x: -9999, y: -9999, on: false };
  const seed = ((canvas.width * 31 + canvas.height * 7) % 997) / 100;

  function resize(): void {
    const r = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = Math.max(1, r.width);
    h = Math.max(1, r.height);
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (style === "constellation" && parts.length === 0) initParticles();
  }

  function initParticles(): void {
    const n = thumb ? 14 : clamp(Math.round(w / 22), 20, 70);
    parts = Array.from({ length: n }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.28,
      vy: (Math.random() - 0.5) * 0.28,
    }));
  }

  function fillBase(): void {
    // Opaque base every frame: the page's html/body are made transparent while
    // a background is active, so the canvas is what paints the palette ground.
    ctx.fillStyle = col(cols.base, 1);
    ctx.fillRect(0, 0, w, h);
  }

  function drawAurora(t: number): void {
    fillBase();
    ctx.globalCompositeOperation = "lighter";
    const blobs = thumb ? 3 : 5;
    for (let i = 0; i < blobs; i++) {
      const ph = seed + i * 1.7;
      const x = w * (0.5 + 0.42 * Math.sin(t * 0.00016 * (1 + i * 0.15) + ph));
      const y = h * (0.42 + 0.3 * Math.cos(t * 0.00013 * (1 + i * 0.2) + ph * 1.3));
      const rad = Math.max(w, h) * (thumb ? 0.34 : 0.3);
      const dh = i % 2 ? 150 : 0;
      const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
      g.addColorStop(0, col(cols.accent, 0.3, 10, dh));
      g.addColorStop(0.4, col(cols.accent, 0.1, 0, dh));
      g.addColorStop(1, col(cols.accent, 0, 0, dh));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, rad, 0, 7);
      ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
  }

  function drawGradient(t: number): void {
    fillBase();
    const specs = [
      { cx: 0.32, cy: 0.34, fx: 0.14, fy: 0.16, dh: 0, a: 0.34, dl: 6 },
      { cx: 0.72, cy: 0.66, fx: 0.14, fy: 0.14, dh: 150, a: 0.26, dl: 0 },
    ];
    for (let i = 0; i < specs.length; i++) {
      const s = specs[i];
      const x = w * (s.cx + s.fx * Math.sin(t * 0.00013 * (1 + i) + seed + i));
      const y = h * (s.cy + s.fy * Math.cos(t * 0.00015 * (1 + i) + seed));
      const rad = Math.max(w, h) * 0.7;
      const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
      g.addColorStop(0, col(cols.accent, s.a, s.dl, s.dh));
      g.addColorStop(0.55, col(cols.accent, 0.05, 0, s.dh));
      g.addColorStop(1, col(cols.accent, 0, 0, s.dh));
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    }
  }

  function drawConstellation(): void {
    fillBase();
    const D = thumb ? 46 : 132;
    const D2 = D * D;
    for (const p of parts) {
      p.x += p.vx;
      p.y += p.vy;
      if (pointer.on) {
        const dx = p.x - pointer.x;
        const dy = p.y - pointer.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < 14000 && d2 > 1) {
          const f = 0.35 / Math.sqrt(d2);
          p.vx += dx * f * 0.02;
          p.vy += dy * f * 0.02;
        }
      }
      p.vx *= 0.996;
      p.vy *= 0.996;
      if (p.x < -5) p.x = w + 5;
      if (p.x > w + 5) p.x = -5;
      if (p.y < -5) p.y = h + 5;
      if (p.y > h + 5) p.y = -5;
    }
    ctx.lineWidth = 1;
    for (let i = 0; i < parts.length; i++) {
      for (let j = i + 1; j < parts.length; j++) {
        const a = parts[i];
        const b = parts[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < D2) {
          ctx.strokeStyle = col(cols.accent, (1 - Math.sqrt(d2) / D) * 0.5, 8);
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }
    if (pointer.on) {
      for (const p of parts) {
        const dx = p.x - pointer.x;
        const dy = p.y - pointer.y;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < D * 1.18) {
          ctx.strokeStyle = col(cols.accent, (1 - d / (D * 1.18)) * 0.6, 16);
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(pointer.x, pointer.y);
          ctx.stroke();
        }
      }
    }
    ctx.fillStyle = col(cols.accent, 0.9, 12);
    for (const p of parts) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, thumb ? 1.4 : 2, 0, 7);
      ctx.fill();
    }
  }

  function draw(t: number): void {
    if (style === "aurora") drawAurora(t);
    else if (style === "gradient") drawGradient(t);
    else drawConstellation();
  }

  resize();
  return {
    draw,
    resize,
    setColors(next) {
      cols = next;
    },
    setPointer(x, y, on) {
      pointer.x = x;
      pointer.y = y;
      pointer.on = on;
    },
  };
}
