"use client";

import { usePathname } from "next/navigation";
import * as React from "react";

// A thin top progress bar for immediate "your click registered" feedback on
// navigation. It covers two waits: the on-demand page compile you can hit in
// dev (a production build is fully precompiled, so real users don't see that),
// and data-fetch/transition latency in production. Dependency-free — it watches
// internal-link clicks to start and the committed pathname change to finish,
// with a short delay so instant (already-loaded) navigations never flash a bar.
export function RouteProgress() {
  const pathname = usePathname();
  const [progress, setProgress] = React.useState(0); // 0 = hidden
  const timers = React.useRef<ReturnType<typeof setTimeout>[]>([]);
  const trickle = React.useRef<ReturnType<typeof setInterval> | null>(null);

  const clearTimers = React.useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    if (trickle.current) {
      clearInterval(trickle.current);
      trickle.current = null;
    }
  }, []);

  const start = React.useCallback(() => {
    clearTimers();
    // Delay before showing so a fast navigation doesn't blink a bar.
    timers.current.push(
      setTimeout(() => {
        setProgress(8);
        // Trickle toward 90% while the route is pending; it can't reach 100
        // until the navigation actually commits (the pathname effect below).
        trickle.current = setInterval(() => {
          setProgress((p) => (p <= 0 || p >= 90 ? p : p + (90 - p) * 0.1));
        }, 200);
      }, 120),
    );
    // Never trickle forever if a navigation is cancelled.
    timers.current.push(setTimeout(() => finish(), 10_000));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clearTimers]);

  const finish = React.useCallback(() => {
    clearTimers();
    // If the bar never showed (instant nav within the start delay), stay hidden.
    setProgress((p) => (p <= 0 ? 0 : 100));
    timers.current.push(setTimeout(() => setProgress(0), 240));
  }, [clearTimers]);

  // Start on any left-click of an internal, same-origin link (Next <Link> renders
  // a plain <a>). Modified clicks and new-tab links open elsewhere — ignore them.
  React.useEffect(() => {
    function onClick(e: MouseEvent) {
      if (
        e.defaultPrevented ||
        e.button !== 0 ||
        e.metaKey ||
        e.ctrlKey ||
        e.shiftKey ||
        e.altKey
      ) {
        return;
      }
      const anchor = (e.target as Element | null)?.closest?.("a");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (
        !href ||
        anchor.getAttribute("target") === "_blank" ||
        !href.startsWith("/") ||
        href.startsWith("//")
      ) {
        return;
      }
      if (href.split(/[?#]/)[0] === pathname) return; // same route → no nav
      start();
    }
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [pathname, start]);

  // A committed pathname change means the navigation finished.
  React.useEffect(() => {
    finish();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  React.useEffect(() => clearTimers, [clearTimers]);

  if (progress <= 0) return null;
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-x-0 top-0 z-[200] h-0.5">
      <div
        className="h-full bg-primary transition-[width,opacity] duration-200 ease-out"
        style={{
          width: `${progress}%`,
          opacity: progress >= 100 ? 0 : 1,
          boxShadow: "0 0 8px hsl(var(--primary))",
        }}
      />
    </div>
  );
}
