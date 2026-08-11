"use client";

// The front-door animated background (#195). A fixed, click-through canvas
// behind the sign-in / register / setup / public pages — never the authenticated
// app shell (gated by pathname), so it costs nothing during live play. Only on
// dark palettes (glowing backdrops are a dark-mode aesthetic); a light palette
// falls back to the flat ground. Colours are read from the resolved
// `--background` / `--primary` tokens, so it tracks whatever palette + accent
// the operator picked. Motion is disabled under prefers-reduced-motion.

import { useEffect, useRef } from "react";

import { usePathname } from "next/navigation";

import {
  type BackgroundColors,
  type BackgroundScene,
  createBackgroundScene,
  isAnimatedBackground,
  parseHslChannels,
} from "@/lib/backgrounds";
import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";
import { paletteMode } from "@/lib/theme";
import { useAuthStore } from "@/stores/auth";

// The out-of-`(app)`-shell routes that get a branded backdrop. A prefix match
// covers nested routes (e.g. /public/[competitionId]).
const FRONT_DOOR = [
  "/login",
  "/register",
  "/setup",
  "/public",
  "/forgot-password",
  "/reset-password",
  "/verify-email",
];

function isFrontDoor(path: string): boolean {
  return FRONT_DOOR.some((f) => path === f || path.startsWith(`${f}/`));
}

// Fallbacks match the default "harbor" surface + brand green, used only if the
// tokens can't be read (they always can once the theme is applied).
function readColors(): BackgroundColors {
  const cs = getComputedStyle(document.documentElement);
  return {
    base: parseHslChannels(cs.getPropertyValue("--background"), { h: 213, s: 41, l: 11 }),
    accent: parseHslChannels(cs.getPropertyValue("--primary"), { h: 160, s: 84, l: 39 }),
  };
}

export function SiteBackground() {
  const { data } = useSiteSettings();
  const pathname = usePathname() ?? "";
  const settings = data ?? FALLBACK_SETTINGS;
  const { background_style: style, accent } = settings;
  // Effective palette = the per-user override ?? the site default — the SAME
  // resolution ThemeApplier paints <html> with. Gating on the raw site default
  // would let a light per-user override (which survives logout) draw a dark
  // animation over light theme tokens on a dark-default install.
  const paletteOverride = useAuthStore((s) => s.paletteOverride);
  const palette = paletteOverride ?? settings.default_palette;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const active =
    isAnimatedBackground(style) &&
    isFrontDoor(pathname) &&
    paletteMode(palette) === "dark";

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!active || !canvas || !isAnimatedBackground(style)) return;

    const root = document.documentElement;
    // Make the page ground transparent so the fixed z-index:-1 canvas shows
    // (the canvas repaints the palette base itself). Restored on unmount.
    root.classList.add("fp-animated-bg");

    const scene = createBackgroundScene(canvas, style, readColors());
    // Live media query, not a one-shot sample: toggling the OS motion setting
    // while the page is open must start/stop the loop without a reload.
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    let raf = 0;

    const frame = (t: number) => {
      scene.draw(t);
      raf = requestAnimationFrame(frame);
    };
    const stop = () => {
      cancelAnimationFrame(raf);
      raf = 0;
    };
    const start = () => {
      if (mq.matches) scene.draw(performance.now());
      else if (!raf && !document.hidden) raf = requestAnimationFrame(frame);
    };

    const onResize = () => {
      scene.resize();
      scene.setColors(readColors());
      // Unconditional repaint: with the loop stopped (hidden tab, reduced
      // motion) a resize reallocates the bitmap and would otherwise stay
      // blank until refocus; under a running loop the next tick overwrites it.
      scene.draw(performance.now());
    };
    const onMove = (e: MouseEvent) => scene.setPointer(e.clientX, e.clientY, true);
    // window "mouseout" bubbles from every element-boundary crossing; only a
    // genuine viewport exit has no relatedTarget. Without the guard the cursor
    // attraction flickers off while moving across the login card's DOM.
    const onOut = (e: MouseEvent) => {
      if (e.relatedTarget === null) scene.setPointer(-9999, -9999, false);
    };
    const pointerOff = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseout", onOut);
      scene.setPointer(-9999, -9999, false);
    };
    const syncPointer = () => {
      // No frames under reduced motion, so cursor bookkeeping would be dead
      // weight — only track the pointer while actually animating.
      if (style === "constellation" && !mq.matches) {
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseout", onOut);
      } else {
        pointerOff();
      }
    };
    const onVisibility = () => (document.hidden ? stop() : start());
    const onMotionChange = () => {
      stop();
      syncPointer();
      start();
    };

    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);
    mq.addEventListener("change", onMotionChange);
    syncPointer();
    start();

    return () => {
      stop();
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
      mq.removeEventListener("change", onMotionChange);
      pointerOff();
      root.classList.remove("fp-animated-bg");
    };
    // accent/palette are read via the tokens; re-run so a live theme change is
    // picked up (they change the resolved --primary/--background).
  }, [active, style, palette, accent]);

  if (!active) return null;
  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="fixed inset-0 h-full w-full"
      style={{ zIndex: -1, pointerEvents: "none" }}
    />
  );
}

/** A small live preview of a background style for the Appearance settings cards.
 *  Reads the same tokens as the full background, so it reflects the
 *  being-configured palette + accent (the panel live-previews those on <html>).
 *  `refreshKey` re-reads the colours when the previewed theme changes; `animate`
 *  is the tab-active flag, so off-screen previews don't burn frames. */
export function BackgroundPreview({
  style,
  animate = true,
  refreshKey,
  className,
}: {
  style: string;
  animate?: boolean;
  refreshKey?: string;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !isAnimatedBackground(style)) return;

    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    let raf = 0;
    let scene: BackgroundScene | null = null;

    const frame = (t: number) => {
      scene!.draw(t);
      raf = requestAnimationFrame(frame);
    };
    // Boot one frame late, deliberately: the panel live-previews the
    // being-configured palette/accent onto <html> from a PARENT effect, and
    // parent effects run after this child's — a synchronous readColors() here
    // would sample the previous theme and lag every change by one interaction.
    raf = requestAnimationFrame((t) => {
      scene = createBackgroundScene(canvas, style, readColors(), { thumb: true });
      if (animate && !mq.matches) frame(t);
      else scene.draw(t);
    });

    const onResize = () => {
      if (!scene) return;
      scene.resize();
      scene.setColors(readColors());
      scene.draw(performance.now());
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, [style, animate, refreshKey]);

  if (!isAnimatedBackground(style)) {
    // "none" (and any unknown value): the flat palette ground.
    return <div className={className} style={{ background: "hsl(var(--background))" }} />;
  }
  return <canvas ref={canvasRef} aria-hidden="true" className={className} />;
}
