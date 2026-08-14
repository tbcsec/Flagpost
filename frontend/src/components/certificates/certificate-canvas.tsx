"use client";

import { useEffect, useRef, useState } from "react";

import { useCertificateMedia } from "@/lib/hooks/use-certificates";
import { certFontFamily, certPresetUrl, snapElementPosition } from "@/lib/certificates";
import type { CertBackgroundKind, CertElement } from "@/lib/types";
import { cn } from "@/lib/utils";

interface CanvasProps {
  competitionId: string;
  aspectRatio: number;
  backgroundKind: CertBackgroundKind;
  backgroundColor: string;
  backgroundPreset: string | null;
  presetAccent: string | null;
  presetBase: string | null;
  backgroundImageUrl: string | null;
  elements: CertElement[];
  tokens: Record<string, string>;
  selectedIndex: number | null;
  onSelect?: (index: number | null) => void;
  onMove?: (index: number, x: number, y: number) => void;
  editable?: boolean;
}

const clamp = (v: number) => Math.max(0, Math.min(100, v));

/** A stored element image, loaded (auth'd) as a blob and shown via an object URL
 *  that is revoked on unmount. Its own component so the media hook is called once
 *  per image, not in a parent loop (React hook rules). */
function CertElementImage({ competitionId, imageKey }: { competitionId: string; imageKey: string }) {
  const media = useCertificateMedia(competitionId, imageKey || null);
  // Object-URL lifecycle in the effect (create + revoke), not useMemo — a memo
  // can mint a URL on a render that never commits, leaking it.
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const objectUrl = media.data ? URL.createObjectURL(media.data) : null;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing an external resource (object URL), the sanctioned effect+setState case
    setUrl(objectUrl);
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [media.data]);
  if (!url) {
    return (
      <div className="flex aspect-video items-center justify-center bg-muted/60 text-xs text-muted-foreground">
        image
      </div>
    );
  }
  /* eslint-disable-next-line @next/next/no-img-element */
  return <img src={url} alt="" className="block w-full" />;
}

/** The WYSIWYG A4 canvas. Positions are % of the canvas and font size is % of
 *  canvas height (via container-query `cqh`), matching the server renderer so
 *  the editor approximates the download (ADR-0027). A subtle Flagpost mark sits
 *  along the bottom — the server render draws the real one on every certificate. */
export function CertificateCanvas({
  competitionId,
  aspectRatio,
  backgroundKind,
  backgroundColor,
  backgroundPreset,
  presetAccent,
  presetBase,
  backgroundImageUrl,
  elements,
  tokens,
  selectedIndex,
  onSelect,
  onMove,
  editable = false,
}: CanvasProps) {
  const areaRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ index: number; startClientX: number; startClientY: number; startX: number; startY: number } | null>(
    null,
  );
  // Active alignment guide lines (canvas %) while dragging; cleared on release.
  const [guides, setGuides] = useState<{ x: number | null; y: number | null }>({
    x: null,
    y: null,
  });

  function backgroundStyle(): React.CSSProperties {
    if (backgroundKind === "upload" && backgroundImageUrl) {
      return { backgroundImage: `url(${backgroundImageUrl})`, backgroundSize: "cover", backgroundPosition: "center" };
    }
    if (backgroundKind === "preset" && backgroundPreset) {
      return {
        backgroundImage: `url(${certPresetUrl(backgroundPreset, presetAccent, presetBase)})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      };
    }
    return { backgroundColor };
  }

  function onPointerDown(e: React.PointerEvent, index: number) {
    onSelect?.(index);
    if (!editable) return;
    e.preventDefault();
    const el = elements[index];
    drag.current = {
      index,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startX: el.x,
      startY: el.y,
    };
    // Capture on the element div (stable), not e.target — an image element's
    // inner <img> can be swapped in mid-drag when its blob resolves, which would
    // drop capture and freeze the drag.
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    const rect = areaRef.current?.getBoundingClientRect();
    if (!d || !rect || !onMove) return;
    const dx = ((e.clientX - d.startClientX) / rect.width) * 100;
    const dy = ((e.clientY - d.startClientY) / rect.height) * 100;
    const rawX = clamp(d.startX + dx);
    const rawY = clamp(d.startY + dy);
    // Hold Alt to move freely (bypass snapping), like most design tools.
    if (e.altKey) {
      onMove(d.index, rawX, rawY);
      setGuides({ x: null, y: null });
      return;
    }
    const others = elements.filter((_, i) => i !== d.index);
    // Scale the vertical snap zone by the aspect ratio so its pixel tolerance
    // matches the horizontal one on the (non-square) landscape canvas.
    const snapped = snapElementPosition(
      rawX,
      rawY,
      elements[d.index]?.width ?? 0,
      others,
      1.2,
      1.2 * aspectRatio,
    );
    onMove(d.index, snapped.x, snapped.y);
    setGuides({ x: snapped.guideX, y: snapped.guideY });
  }

  function onPointerUp() {
    drag.current = null;
    setGuides({ x: null, y: null });
  }

  return (
    <div className="w-full select-none">
      <div
        ref={areaRef}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onClick={(e) => {
          if (e.target === areaRef.current) onSelect?.(null);
        }}
        className="relative overflow-hidden border border-border"
        style={{ aspectRatio: String(aspectRatio), containerType: "size", ...backgroundStyle() }}
      >
        {elements.map((el, i) => {
          const isText = el.type === "token" || el.type === "text";
          const content =
            el.type === "token"
              ? (tokens[el.token ?? ""] ?? `{${el.token}}`)
              : el.type === "text"
                ? el.text
                : null;
          return (
            <div
              key={i}
              onPointerDown={(e) => onPointerDown(e, i)}
              className={cn(
                "absolute",
                editable && "cursor-move",
                selectedIndex === i && "outline-dashed outline-2 outline-offset-2 outline-primary",
              )}
              style={{
                left: `${el.x}%`,
                top: `${el.y}%`,
                width: `${el.width}%`,
                textAlign: el.align,
                ...(isText
                  ? {
                      fontFamily: certFontFamily(el.font),
                      fontSize: `${el.font_size}cqh`,
                      color: el.color,
                      fontWeight: el.bold ? 700 : 400,
                      fontStyle: el.italic ? "italic" : "normal",
                      lineHeight: 1.25,
                      wordBreak: "break-word",
                    }
                  : {}),
              }}
            >
              {el.type === "image" ? (
                <CertElementImage competitionId={competitionId} imageKey={el.image_key ?? ""} />
              ) : (
                content
              )}
            </div>
          );
        })}
        {/* Alignment guides — shown only while a snap is active during a drag. */}
        {guides.x !== null && (
          <div
            className="pointer-events-none absolute inset-y-0 w-px bg-primary/70"
            style={{ left: `${guides.x}%` }}
          />
        )}
        {guides.y !== null && (
          <div
            className="pointer-events-none absolute inset-x-0 h-px bg-primary/70"
            style={{ top: `${guides.y}%` }}
          />
        )}
        {/* Subtle, always-present Flagpost mark along the bottom. mix-blend keeps
            it legible on any background; the server render draws the real flag. */}
        <div
          className="pointer-events-none absolute inset-x-0 flex items-center justify-center gap-[0.35em]"
          style={{
            bottom: "1.5%",
            mixBlendMode: "difference",
            color: "white",
            opacity: 0.72,
            fontSize: "2cqh",
          }}
        >
          <span aria-hidden>⚑</span>
          <span>flagpost.io</span>
        </div>
      </div>
    </div>
  );
}
