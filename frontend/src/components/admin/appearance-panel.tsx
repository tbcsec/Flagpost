"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { SkeletonCards } from "@/components/ui/skeleton";
import { FlagpostMark } from "@/components/brand/flagpost-mark";
import { BackgroundPreview } from "@/components/theme/site-background";
import { richTextToPlain } from "@/lib/rich-text";
import type { RichTextDoc } from "@/lib/types";
import {
  FALLBACK_SETTINGS,
  useDeleteLogo,
  useSiteSettings,
  useUpdateSiteSettings,
  useUploadLogo,
} from "@/lib/hooks/use-site-settings";
import {
  ACCENTS,
  BACKGROUNDS,
  PALETTES,
  accentSwatchHex,
  applyTheme,
  isCustomAccent,
  paletteMode,
} from "@/lib/theme";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

// Admin → Site settings → Appearance (§9 site-wide theming). Sets the platform
// name, the default palette (surface colours) and the accent (action colours)
// for the whole install. Palette selection live-previews on <html> so the admin
// sees the whole surface recolour before saving; the mark never takes the accent
// (LOGO-SPEC §7).
//
// `active` is whether the Appearance tab is the one on screen. The settings page
// keeps every panel mounted so unsaved edits survive tab switches, so this panel
// can't use unmount to end its live preview — see the two effects below.
export function AppearancePanel({ active }: { active: boolean }) {
  const t = useTranslations("admin.appearance");
  const { data, isLoading } = useSiteSettings();
  const update = useUpdateSiteSettings();
  const uploadLogo = useUploadLogo();
  const confirm = useConfirm();
  const deleteLogo = useDeleteLogo();
  const paletteOverride = useAuthStore((s) => s.paletteOverride);

  const saved = data ?? FALLBACK_SETTINGS;
  const [platformName, setPlatformName] = useState(saved.platform_name);
  const [palette, setPalette] = useState(saved.default_palette);
  const [accent, setAccent] = useState(saved.accent);
  const [background, setBackground] = useState(saved.background_style);
  const [notice, setNotice] = useState<RichTextDoc>(saved.login_notice ?? {});
  const [showWordmark, setShowWordmark] = useState(saved.show_wordmark);

  // Seed the form once the settings load (they arrive async).
  const seeded = useRef(false);
  useEffect(() => {
    if (data && !seeded.current) {
      seeded.current = true;
      setPlatformName(data.platform_name);
      setPalette(data.default_palette);
      setAccent(data.accent);
      setBackground(data.background_style);
      setNotice(data.login_notice ?? {});
      setShowWordmark(data.show_wordmark);
    }
  }, [data]);

  // Live preview: apply the *being-configured* palette + accent directly — but
  // only while this tab is on screen, so an unsaved preview never bleeds across
  // the rest of the admin UI. Re-applies when the tab is re-entered, since
  // `active` is a dependency.
  useEffect(() => {
    if (active) applyTheme(document.documentElement, { palette, accent });
  }, [active, palette, accent]);

  // On leaving without saving — switching tabs *or* navigating away — restore
  // what the viewer actually sees (their own palette override, if any, over the
  // saved site default). The cleanup needs the *latest* saved settings and
  // override, but must not re-run on every keystroke, so those are mirrored into
  // refs from an effect (refs are written outside render) and read here.
  //
  // Keyed on `active` alone, deliberately: including palette/accent would make
  // the cleanup fire on every preview change, restoring then instantly
  // re-applying — a visible flicker on each click.
  const savedRef = useRef(saved);
  const overrideRef = useRef(paletteOverride);
  useEffect(() => {
    savedRef.current = saved;
    overrideRef.current = paletteOverride;
  });
  useEffect(() => {
    if (!active) return;
    return () => {
      const s = savedRef.current;
      applyTheme(document.documentElement, {
        palette: overrideRef.current ?? s.default_palette,
        accent: s.accent,
      });
    };
  }, [active]);

  // An editor doc with no text normalizes to null — "delete everything" means
  // "no notice", the rules-settings precedent.
  const noticeValue = richTextToPlain(notice).trim() ? notice : null;
  const dirty =
    platformName !== saved.platform_name ||
    palette !== saved.default_palette ||
    accent !== saved.accent ||
    background !== saved.background_style ||
    JSON.stringify(noticeValue) !== JSON.stringify(saved.login_notice) ||
    showWordmark !== saved.show_wordmark;

  function onSave() {
    update.mutate(
      {
        platform_name: platformName.trim(),
        default_palette: palette,
        accent,
        background_style: background,
        login_notice: noticeValue,
        show_wordmark: showWordmark,
      },
      {
        onSuccess: () => toast(t("appearanceSaved"), { variant: "success" }),
        onError: (e) => toast(t("couldntSave"), { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  function onLogoFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file after a failure
    if (!file) return;
    uploadLogo.mutate(file, {
      onSuccess: () => toast(t("logoUpdated"), { variant: "success" }),
      onError: (err) =>
        toast(t("couldntUploadLogo"), {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  async function onRemoveLogo() {
    if (
      !(await confirm({
        title: t("removeLogoTitle"),
        description: t("removeLogoDescription"),
        confirmLabel: t("removeLogoConfirm"),
      }))
    ) {
      return;
    }
    deleteLogo.mutate(undefined, {
      onSuccess: () => toast(t("logoRemoved"), { variant: "success" }),
      onError: (err) =>
        toast(t("couldntRemoveLogo"), {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  if (isLoading) return <SkeletonCards count={3} />;

  const customActive = isCustomAccent(accent);

  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-8">
          <div className="grid max-w-md gap-2">
            <Label htmlFor="platform-name">{t("platformName")}</Label>
            <Input
              id="platform-name"
              value={platformName}
              maxLength={64}
              onChange={(e) => setPlatformName(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">{t("platformNameHint")}</p>
          </div>

          <section className="grid gap-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("paletteHeading")}</h3>
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
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("accentHeading")}</h3>
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
                    aria-label={t("customAccentAria")}
                  />
                  {!customActive && (
                    <span className="flex h-full items-center justify-center text-xs text-muted-foreground">{t("pick")}</span>
                  )}
                </span>
                <div className="flex items-center justify-between gap-1">
                  <span className="text-sm font-semibold">{t("custom")}</span>
                  {customActive && <CheckIcon />}
                </div>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {customActive ? accent : t("anyHex")}
                </span>
              </label>
            </div>
          </section>

          <section className="grid gap-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {t("backgroundHeading")}
            </h3>
            <p className="max-w-prose text-xs text-muted-foreground">
              {t("backgroundDescription")}
            </p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {BACKGROUNDS.map((b) => (
                <button
                  key={b.id}
                  onClick={() => setBackground(b.id)}
                  className={cn(
                    "grid gap-2 rounded-lg border p-3 text-left transition-colors",
                    background === b.id ? "border-primary ring-1 ring-primary" : "border-border hover:border-primary/40",
                  )}
                >
                  <BackgroundPreview
                    style={b.id}
                    animate={active}
                    refreshKey={`${palette}:${accent}`}
                    className="h-16 w-full overflow-hidden rounded-md border border-border"
                  />
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-sm font-semibold">{b.label}</span>
                    {background === b.id && <CheckIcon />}
                  </div>
                  <span className="text-[11px] leading-snug text-muted-foreground">
                    {b.interactive ? t("reactsToCursor") : b.description}
                  </span>
                </button>
              ))}
            </div>
            {paletteMode(palette) === "light" && background !== "none" && (
              <p className="text-xs text-warning">{t("lightPaletteWarning")}</p>
            )}
          </section>

          <section className="grid gap-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {t("noticeHeading")}
            </h3>
            <p className="max-w-prose text-xs text-muted-foreground">
              {t("noticeDescription")}
            </p>
            <RichTextEditor value={notice} onChange={setNotice} />
          </section>

          <section className="grid gap-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("logoHeading")}</h3>
            <p className="max-w-prose text-xs text-muted-foreground">
              {t("logoDescription")}
            </p>
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex h-16 min-w-[8rem] items-center justify-center rounded-lg border border-border bg-background px-4">
                {saved.logo_url ? (
                  // eslint-disable-next-line @next/next/no-img-element -- dynamic brand asset from the API origin
                  <img src={saved.logo_url} alt={t("currentLogoAlt")} className="h-10 w-auto object-contain" />
                ) : (
                  <FlagpostMark size={40} theme="dark" />
                )}
              </div>
              <div className="flex items-center gap-2">
                <label>
                  <span className={cn(
                    "inline-flex h-9 cursor-pointer items-center rounded-md border border-border px-3 text-sm font-medium hover:bg-accent/60",
                    uploadLogo.isPending && "pointer-events-none opacity-60",
                  )}>
                    {uploadLogo.isPending ? t("uploading") : saved.logo_url ? t("replaceLogo") : t("uploadLogo")}
                  </span>
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
                    className="hidden"
                    onChange={onLogoFile}
                    disabled={uploadLogo.isPending}
                  />
                </label>
                {saved.logo_url && (
                  <Button variant="ghost" size="sm" onClick={onRemoveLogo} disabled={deleteLogo.isPending}>
                    {deleteLogo.isPending ? t("removing") : t("remove")}
                  </Button>
                )}
              </div>
            </div>
            <label className="mt-1 flex items-center gap-2.5">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-border"
                style={{ accentColor: "hsl(var(--primary))" }}
                checked={showWordmark}
                onChange={(e) => setShowWordmark(e.target.checked)}
              />
              <span className="text-sm">
                {t("showWordmark")}
                <span className="ml-1 text-xs text-muted-foreground">
                  {t("showWordmarkHint")}
                </span>
              </span>
            </label>
          </section>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={onSave} disabled={!dirty || update.isPending}>
          {update.isPending ? t("saving") : t("saveChanges")}
        </Button>
        {dirty && (
          <span className="text-xs text-muted-foreground">{t("previewing")}</span>
        )}
      </div>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-primary">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}
