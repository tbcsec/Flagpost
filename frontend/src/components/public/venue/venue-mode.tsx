"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Lockup } from "@/components/brand/flagpost-mark";
import { Highlights, StatTiles } from "@/components/public/insights-cards";
import { PointsTimeline } from "@/components/public/points-timeline";
import { FirstBloodIcon } from "@/components/ui/first-blood-icon";
import type { PublicActivity, PublicInsights, PublicScoreboard } from "@/lib/types";
import { nextIndex, pickNewFirstBloods } from "@/lib/venue";
import { cn } from "@/lib/utils";

// Venue/projector mode (#77): a full-viewport, unauthenticated big-screen display
// that auto-rotates the scoreboard, insights and points timeline, with a
// first-blood takeover splash. Data comes from the same freeze-aware public
// endpoints the static spectator page uses, so it discloses nothing extra; the
// splash is driven by the recent-solves feed and stays silent during a freeze.

const SPLASH_MS = 5000;

interface Brand {
  platform_name: string;
  logo_url: string | null;
  show_wordmark: boolean;
}

export function VenueMode({
  scoreboard,
  insights,
  activity,
  brand,
  intervalSeconds,
  onExit,
}: {
  scoreboard: PublicScoreboard;
  insights: PublicInsights | undefined;
  activity: PublicActivity | undefined;
  brand: Brand;
  intervalSeconds: number;
  onExit: () => void;
}) {
  // Build the rotation from whatever data is loaded: the board always, insights
  // and timeline once their fetch lands (and the timeline only if anyone has
  // scored, matching the component's own empty guard).
  const slides: { key: string; node: React.ReactNode }[] = [
    { key: "board", node: <VenueBoard scoreboard={scoreboard} /> },
  ];
  if (insights) {
    slides.push({ key: "insights", node: <VenueInsights insights={insights} /> });
    if (insights.timeline.series.length > 0) {
      slides.push({
        key: "timeline",
        node: (
          <VenueSlide title="Points over time">
            <PointsTimeline
              series={insights.timeline.series}
              start={insights.timeline.start}
              end={insights.timeline.end}
              frozen={insights.frozen}
            />
          </VenueSlide>
        ),
      });
    }
  }

  const [idx, setIdx] = useState(0);
  const [paused, setPaused] = useState(false);
  const count = slides.length;
  const current = idx % count;

  const advance = useCallback(
    (dir: 1 | -1) => setIdx((i) => (dir === 1 ? nextIndex(i, count) : (i - 1 + count) % count)),
    [count],
  );

  // First-blood splash queue. Prime `seen` from the first feed so pre-existing
  // first bloods don't all splash on load; thereafter, a newly-tagged first
  // blood enqueues one takeover.
  const seenRef = useRef<Set<string>>(new Set());
  const primedRef = useRef(false);
  const [queue, setQueue] = useState<PublicActivity["recent_solves"]>([]);
  // The current takeover is simply the head of the queue — derived, not a second
  // piece of state to keep in sync.
  const splash = queue[0] ?? null;

  useEffect(() => {
    const solves = activity?.recent_solves;
    if (!solves) return;
    if (!primedRef.current) {
      for (const s of solves) if (s.is_first_blood) seenRef.current.add(s.challenge_id);
      primedRef.current = true;
      return;
    }
    const fresh = pickNewFirstBloods(solves, seenRef.current);
    if (fresh.length === 0) return;
    for (const s of fresh) seenRef.current.add(s.challenge_id);
    setQueue((q) => [...q, ...fresh]);
  }, [activity]);

  // After SPLASH_MS the head is dropped, revealing the next takeover or clearing
  // the overlay when the queue empties. The setState is in the timeout callback,
  // not the effect body, so it doesn't cascade renders.
  useEffect(() => {
    if (!splash) return;
    const id = setTimeout(() => setQueue((q) => q.slice(1)), SPLASH_MS);
    return () => clearTimeout(id);
  }, [splash]);

  // Auto-rotate — held while paused or while a splash is up (so the board
  // underneath doesn't jump the instant the takeover clears).
  useEffect(() => {
    if (paused || splash || count <= 1) return;
    const id = setInterval(() => setIdx((i) => nextIndex(i, count)), intervalSeconds * 1000);
    return () => clearInterval(id);
  }, [paused, splash, count, intervalSeconds]);

  const [isFullscreen, setIsFullscreen] = useState(false);
  useEffect(() => {
    const onChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);
  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else document.documentElement.requestFullscreen().catch(() => {});
  }, []);

  // Keyboard: arrows advance, space pauses, f toggles fullscreen, Esc exits.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") advance(1);
      else if (e.key === "ArrowLeft") advance(-1);
      else if (e.key === " ") {
        e.preventDefault();
        setPaused((p) => !p);
      } else if (e.key === "f" || e.key === "F") toggleFullscreen();
      else if (e.key === "Escape") onExit();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [advance, toggleFullscreen, onExit]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background text-foreground">
      <header className="flex items-center gap-4 border-b border-border px-8 py-4">
        <span className="flex items-center gap-2 text-sm font-medium text-primary">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-primary" />
          LIVE
        </span>
        <span className="truncate text-xl font-semibold">{scoreboard.name}</span>
        <Countdown startAt={scoreboard.start_at} endAt={scoreboard.end_at} />
        {scoreboard.frozen && (
          <span className="rounded-full bg-secondary px-3 py-1 text-xs font-medium text-secondary-foreground">
            Frozen
          </span>
        )}
        <Lockup
          size={28}
          label={brand.platform_name}
          logoUrl={brand.logo_url}
          showWordmark={brand.show_wordmark}
        />
      </header>

      <main className="relative flex-1 overflow-hidden px-8 py-6">
        {slides[current].node}
        {splash && <FirstBloodSplash solve={splash} />}
      </main>

      <footer className="flex items-center gap-4 px-8 py-4">
        <div className="flex flex-1 items-center gap-2" role="tablist" aria-label="Slides">
          {slides.map((s, i) => (
            <button
              key={s.key}
              type="button"
              role="tab"
              aria-selected={i === current}
              aria-label={s.key}
              onClick={() => setIdx(i)}
              className={cn(
                "h-2 rounded-full transition-all",
                i === current ? "w-6 bg-primary" : "w-2 bg-muted-foreground/40",
              )}
            />
          ))}
        </div>
        <VenueControls
          paused={paused}
          isFullscreen={isFullscreen}
          onPrev={() => advance(-1)}
          onNext={() => advance(1)}
          onTogglePause={() => setPaused((p) => !p)}
          onToggleFullscreen={toggleFullscreen}
          onExit={onExit}
        />
      </footer>
    </div>
  );
}

function VenueSlide({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex h-full flex-col">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}

function VenueBoard({ scoreboard }: { scoreboard: PublicScoreboard }) {
  const top = scoreboard.entries.slice(0, 12);
  return (
    <VenueSlide title="Scoreboard">
      {top.length === 0 ? (
        <div className="grid h-full place-items-center text-2xl text-muted-foreground">
          No scores yet — the board fills in on the first solve.
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {top.map((e) => (
            <div
              key={e.subject_id}
              className={cn(
                "flex items-center gap-5 rounded-lg px-5 py-2.5",
                e.rank === 1 && "bg-primary/10",
              )}
            >
              <span
                className={cn(
                  "w-12 text-right font-mono text-2xl font-semibold tabular-nums",
                  e.rank === 1 ? "text-primary" : "text-muted-foreground",
                )}
              >
                {e.rank}
              </span>
              <span className="flex-1 truncate text-2xl font-medium">{e.name}</span>
              <span className="font-mono text-2xl font-semibold tabular-nums text-primary">
                {e.points.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </VenueSlide>
  );
}

function VenueInsights({ insights }: { insights: PublicInsights }) {
  return (
    <div className="flex h-full flex-col justify-center gap-6">
      <StatTiles stats={insights.stats} />
      <Highlights highlights={insights.highlights} variant="row" />
    </div>
  );
}

/** The first-blood takeover — the amber lightning glyph the app uses everywhere
 *  for first blood, blown up to full screen. */
function FirstBloodSplash({
  solve,
}: {
  solve: PublicActivity["recent_solves"][number];
}) {
  return (
    <div
      role="alert"
      className="anim-toast absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 bg-warning/95 px-8 text-center text-warning-foreground"
    >
      <FirstBloodIcon size={72} className="text-warning-foreground" />
      <div className="text-sm font-semibold uppercase tracking-widest">First blood</div>
      <div className="text-5xl font-semibold">{solve.subject_name}</div>
      <div className="text-2xl">
        first to solve <span className="font-semibold">{solve.title}</span>
      </div>
    </div>
  );
}

function Countdown({
  startAt,
  endAt,
}: {
  startAt: string | null;
  endAt: string | null;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const start = startAt ? new Date(startAt).getTime() : null;
  const end = endAt ? new Date(endAt).getTime() : null;

  let label: string | null = null;
  let value: string | null = null;
  if (start !== null && now < start) {
    label = "starts in";
    value = formatDuration(Math.floor((start - now) / 1000));
  } else if (end !== null) {
    label = now >= end ? null : "remaining";
    value = now >= end ? "Ended" : formatDuration(Math.floor((end - now) / 1000));
  }
  if (value === null) return null;

  return (
    <span className="ml-auto font-mono text-lg tabular-nums">
      {value}
      {label && <span className="ml-2 text-xs text-muted-foreground">{label}</span>}
    </span>
  );
}

function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, totalSeconds);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  const clock = `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
  return days > 0 ? `${days}d ${clock}` : clock;
}

function VenueControls({
  paused,
  isFullscreen,
  onPrev,
  onNext,
  onTogglePause,
  onToggleFullscreen,
  onExit,
}: {
  paused: boolean;
  isFullscreen: boolean;
  onPrev: () => void;
  onNext: () => void;
  onTogglePause: () => void;
  onToggleFullscreen: () => void;
  onExit: () => void;
}) {
  const btn =
    "rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground";
  return (
    <div className="flex items-center gap-2 opacity-60 transition-opacity hover:opacity-100">
      <button type="button" className={btn} onClick={onPrev} aria-label="Previous slide">
        ←
      </button>
      <button
        type="button"
        className={btn}
        onClick={onTogglePause}
        aria-pressed={paused}
      >
        {paused ? "Play" : "Pause"}
      </button>
      <button type="button" className={btn} onClick={onNext} aria-label="Next slide">
        →
      </button>
      <button
        type="button"
        className={btn}
        onClick={onToggleFullscreen}
        aria-pressed={isFullscreen}
      >
        {isFullscreen ? "Exit full screen" : "Full screen"}
      </button>
      <button type="button" className={btn} onClick={onExit}>
        Exit venue
      </button>
    </div>
  );
}
