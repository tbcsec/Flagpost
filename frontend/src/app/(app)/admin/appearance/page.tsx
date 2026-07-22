"use client";

import { useEffect, useRef, useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SkeletonCards } from "@/components/ui/skeleton";
import {
  FALLBACK_SETTINGS,
  useSiteSettings,
  useUpdateSiteSettings,
} from "@/lib/hooks/use-site-settings";
import {
  ACCENTS,
  PALETTES,
  accentSwatchHex,
  applyTheme,
  isCustomAccent,
} from "@/lib/theme";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

// Admin → Appearance (§9 site-wide theming). Sets the platform name, the default
// palette (surface colours) and the accent (action colours) for the whole
// install. Palette selection live-previews on <html> so the admin sees the whole
// surface recolour before saving; the mark never takes the accent (LOGO-SPEC §7).
export default function AdminAppearancePage() {
  const { data, isLoading } = useSiteSettings();
  const update = useUpdateSiteSettings();
  const paletteOverride = useAuthStore((s) => s.paletteOverride);

  const saved = data ?? FALLBACK_SETTINGS;
  const [platformName, setPlatformName] = useState(saved.platform_name);
  const [palette, setPalette] = useState(saved.default_palette);
  const [accent, setAccent] = useState(saved.accent);

  // Seed the form once the settings load (they arrive async).
  const seeded = useRef(false);
  useEffect(() => {
    if (data && !seeded.current) {
      seeded.current = true;
      setPlatformName(data.platform_name);
      setPalette(data.default_palette);
      setAccent(data.accent);
    }
  }, [data]);

  // Live preview: apply the *being-configured* default palette + accent directly.
  useEffect(() => {
    applyTheme(document.documentElement, { palette, accent });
  }, [palette, accent]);

  // On leaving without saving, restore what the viewer actually sees (their own
  // palette override, if any, over the saved site default).
  const savedRef = useRef(saved);
  savedRef.current = saved;
  const overrideRef = useRef(paletteOverride);
  overrideRef.current = paletteOverride;
  useEffect(() => {
    return () => {
      const s = savedRef.current;
      applyTheme(document.documentElement, {
        palette: overrideRef.current ?? s.default_palette,
        accent: s.accent,
      });
    };
  }, []);

  const dirty =
    platformName !== saved.platform_name ||
    palette !== saved.default_palette ||
    accent !== saved.accent;

  function onSave() {
    update.mutate(
      { platform_name: platformName.trim(), default_palette: palette, accent },
      {
        onSuccess: () => toast("Appearance saved", { variant: "success" }),
        onError: (e) => toast("Couldn't save", { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  if (isLoading) {
    return (
      <>
        <SectionHeader title="Admin — Appearance" subtitle="Global — platform-wide, not scoped to a competition" />
        <SkeletonCards count={3} />
      </>
    );
  }

  const customActive = isCustomAccent(accent);

  return (
    <>
      <SectionHeader
        title="Admin — Appearance"
        subtitle="Global — platform-wide, not scoped to a competition"
      />

      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
          <CardDescription>
            Palette controls surface colours; accent controls action colours. Mix freely.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-8">
          <div className="grid max-w-md gap-2">
            <Label htmlFor="platform-name">Platform name</Label>
            <Input
              id="platform-name"
              value={platformName}
              maxLength={64}
              onChange={(e) => setPlatformName(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Shown in the sidebar, on the sign-in screen, and in the browser tab.
            </p>
          </div>

          <section className="grid gap-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Palette</h3>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {PALETTES.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPalette(p.id)}
                  className={cn(
                    "grid gap-2 rounded-lg border p-3 text-left transition-colors",
                    palette === p.id ? "border-primary ring-1 ring-primary" : "border-border hover:border-primary/40",
                  )}
                >
                  <div
                    className="flex h-16 items-end gap-1 rounded-md border p-2"
                    style={{ backgroundColor: p.swatch.bg, borderColor: p.swatch.border }}
                  >
                    <span className="h-6 flex-1 rounded" style={{ backgroundColor: p.swatch.card }} />
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: p.swatch.text }} />
                  </div>
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-sm font-semibold">{p.label}</span>
                    {palette === p.id && <CheckIcon />}
                  </div>
                  <span className="text-[11px] leading-snug text-muted-foreground">{p.description}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="grid gap-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Accent</h3>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {ACCENTS.map((a) => (
                <button
                  key={a.id}
                  onClick={() => setAccent(a.id)}
                  className={cn(
                    "grid gap-2 rounded-lg border p-3 text-left transition-colors",
                    accent === a.id ? "border-primary ring-1 ring-primary" : "border-border hover:border-primary/40",
                  )}
                >
                  <span className="h-10 w-full rounded-md" style={{ backgroundColor: a.hex }} />
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-sm font-semibold">{a.label}</span>
                    {accent === a.id && <CheckIcon />}
                  </div>
                  <span className="text-[11px] leading-snug text-muted-foreground">{a.description}</span>
                </button>
              ))}

              {/* Custom hex accent — full custom colour, like a theme tool. */}
              <label
                className={cn(
                  "grid cursor-pointer gap-2 rounded-lg border p-3 text-left transition-colors",
                  customActive ? "border-primary ring-1 ring-primary" : "border-border hover:border-primary/40",
                )}
              >
                <span
                  className="relative h-10 w-full overflow-hidden rounded-md border border-border"
                  style={{ backgroundColor: customActive ? accent : "transparent" }}
                >
                  <input
                    type="color"
                    value={customActive ? accent : accentSwatchHex(accent)}
                    onChange={(e) => setAccent(e.target.value.toUpperCase())}
                    className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                    aria-label="Custom accent colour"
                  />
                  {!customActive && (
                    <span className="flex h-full items-center justify-center text-xs text-muted-foreground">Pick…</span>
                  )}
                </span>
                <div className="flex items-center justify-between gap-1">
                  <span className="text-sm font-semibold">Custom</span>
                  {customActive && <CheckIcon />}
                </div>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {customActive ? accent : "any hex"}
                </span>
              </label>
            </div>
          </section>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={onSave} disabled={!dirty || update.isPending}>
          {update.isPending ? "Saving…" : "Save changes"}
        </Button>
        {dirty && (
          <span className="text-xs text-muted-foreground">Previewing — save to apply site-wide.</span>
        )}
      </div>
    </>
  );
}

function CheckIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-primary">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}
