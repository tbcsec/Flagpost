"use client";

// Fit-to-screen for venue mode (#513): a slide is left on a big screen with
// nobody at the keyboard, so it must never scroll and never overflow. A list
// shows as many of its equal-height rows as fit the space it's given — rows
// are in priority order, so what's dropped is the least important — and the
// chart sizes itself to the box it sits in.

import { useCallback, useLayoutEffect, useRef, useState } from "react";

import { fitCount } from "@/lib/venue-race";

/** How many of up to `max` rows fit in the container. Attach `containerRef`
 *  to the scrolling parent and `probeRef` to the first row, which must always
 *  be rendered (hide it visually when `count` is 0) so there's something to
 *  measure when space comes back. Re-measures on container and row resizes —
 *  the latter is what the venue zoom keys change. */
export function useFitCount<
  Container extends HTMLElement = HTMLDivElement,
  Probe extends HTMLElement = HTMLDivElement,
>(max: number) {
  const containerRef = useRef<Container>(null);
  const probeEl = useRef<Probe | null>(null);
  const observer = useRef<ResizeObserver | null>(null);
  const [count, setCount] = useState(max);

  // A callback ref, not an object ref: the first row is a different element
  // whenever the list's head changes (a new solve, a new leader), and the
  // observer has to follow it or it watches a detached node.
  const probeRef = useCallback((el: Probe | null) => {
    if (observer.current && probeEl.current) observer.current.unobserve(probeEl.current);
    probeEl.current = el;
    if (observer.current && el) observer.current.observe(el);
  }, []);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const measure = () => {
      const probe = probeEl.current;
      const gap = parseFloat(getComputedStyle(container).rowGap) || 0;
      const rowHeight = probe ? probe.getBoundingClientRect().height : 0;
      setCount(fitCount(container.clientHeight, rowHeight, gap, max));
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const ro = new ResizeObserver(measure);
    observer.current = ro;
    ro.observe(container);
    if (probeEl.current) ro.observe(probeEl.current);
    return () => {
      ro.disconnect();
      observer.current = null;
    };
  }, [max]);

  return { containerRef, probeRef, count: Math.min(count, max) };
}

/** The pixel size of a box, kept current as it resizes; 0×0 until measured. */
export function useBoxSize() {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      setSize((prev) =>
        prev.width === rect.width && prev.height === rect.height
          ? prev
          : { width: rect.width, height: rect.height },
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return { ref, ...size };
}

/** The measured pixel heights (margin box) of a few named elements, kept
 *  current as they resize — for a column that hands space to its blocks explicitly, in
 *  priority order, instead of letting flex shrink them all at once. `ref(key)`
 *  gives a stable callback ref for each element; an element that unmounts
 *  drops out of `heights`. */
export function useHeights<K extends string>() {
  const els = useRef(new Map<K, HTMLElement>());
  const probes = useRef(new Map<K, (el: HTMLElement | null) => void>());
  const observer = useRef<ResizeObserver | null>(null);
  const [heights, setHeights] = useState<Partial<Record<K, number>>>({});

  // A stable callback ref per key. Observing an element makes the observer
  // report it straight away, so (re)attaching needs no explicit measure.
  const probe = useCallback((key: K) => {
    let fn = probes.current.get(key);
    if (!fn) {
      fn = (el) => {
        const prev = els.current.get(key);
        if (prev && observer.current) observer.current.unobserve(prev);
        if (el) {
          els.current.set(key, el);
          observer.current?.observe(el);
        } else {
          els.current.delete(key);
        }
      };
      probes.current.set(key, fn);
    }
    return fn;
  }, []);

  useLayoutEffect(() => {
    const measure = () => {
      const next: Partial<Record<K, number>> = {};
      // Margin-box height: a heading's bottom margin is part of what it costs.
      for (const [key, el] of els.current) {
        const style = getComputedStyle(el);
        next[key] =
          el.getBoundingClientRect().height +
          (parseFloat(style.marginTop) || 0) +
          (parseFloat(style.marginBottom) || 0);
      }
      setHeights((prev) => {
        const keys = new Set([...Object.keys(prev), ...Object.keys(next)] as K[]);
        for (const key of keys) if (prev[key] !== next[key]) return next;
        return prev;
      });
    };
    if (typeof ResizeObserver === "undefined") {
      measure();
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const ro = new ResizeObserver(measure);
    observer.current = ro;
    for (const el of els.current.values()) ro.observe(el);
    return () => {
      ro.disconnect();
      observer.current = null;
    };
  }, []);

  return { probe, heights };
}
