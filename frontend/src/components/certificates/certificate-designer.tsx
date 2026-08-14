"use client";

import { useEffect, useMemo, useState } from "react";

import { CertificateCanvas } from "@/components/certificates/certificate-canvas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { parseServerDate } from "@/lib/datetime";
import {
  CERT_DEFAULT_TEXT,
  certFontFaceCss,
  certFontFamily,
  certPresetUrl,
  customFontFaceCss,
  newCertElement,
} from "@/lib/certificates";
import {
  fetchCertificateFontBlob,
  useCertificateBackgroundImage,
  useCertificateExport,
  useCertificateFonts,
  useCertificateManifest,
  useCertificateTemplate,
  useCreateCertificateExport,
  useDeleteCertificateFont,
  useExportCertificateTemplate,
  useImportCertificateTemplate,
  usePreviewCertificate,
  useReleaseCertificates,
  useSaveCertificateTemplate,
  useUploadCertificateBackground,
  useUploadCertificateFont,
  useUploadCertificateImage,
} from "@/lib/hooks/use-certificates";
import type {
  CertElement,
  CertificateTemplate,
  CertificateTemplateInput,
} from "@/lib/types";
import { toast } from "@/stores/toast";

function toInput(t: CertificateTemplate): CertificateTemplateInput {
  return {
    background_kind: t.background_kind,
    background_preset: t.background_preset,
    background_color: t.background_color,
    preset_accent: t.preset_accent,
    preset_base: t.preset_base,
    elements: t.elements,
    recipient_rule: t.recipient_rule,
    release_mode: t.release_mode,
    release_delay_minutes: t.release_delay_minutes,
  };
}

export function CertificateDesigner({ competitionId }: { competitionId: string }) {
  const manifest = useCertificateManifest();
  const template = useCertificateTemplate(competitionId);
  const save = useSaveCertificateTemplate(competitionId);
  const uploadBg = useUploadCertificateBackground(competitionId);
  const uploadImg = useUploadCertificateImage(competitionId);
  const preview = usePreviewCertificate(competitionId);
  const release = useReleaseCertificates(competitionId);
  const createExport = useCreateCertificateExport(competitionId);
  const customFonts = useCertificateFonts(competitionId);
  const uploadFont = useUploadCertificateFont(competitionId);
  const deleteFont = useDeleteCertificateFont(competitionId);
  const exportTpl = useExportCertificateTemplate(competitionId);
  const importTpl = useImportCertificateTemplate(competitionId);
  const confirm = useConfirm();

  const [edited, setEdited] = useState<CertificateTemplateInput | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useCertificateExport(competitionId, jobId);

  // Load the bundled fonts so the canvas text matches the render (ADR-0027).
  useEffect(() => {
    if (!manifest.data) return;
    const style = document.createElement("style");
    style.textContent = certFontFaceCss(manifest.data.fonts);
    document.head.appendChild(style);
    return () => {
      document.head.removeChild(style);
    };
  }, [manifest.data]);

  // Load any custom fonts the same way — fetched as auth'd blobs (a @font-face
  // can't carry the bearer token), injected as object-URL faces so the canvas
  // previews the exact font the server renders with.
  useEffect(() => {
    const fonts = customFonts.data;
    if (!fonts || fonts.length === 0) return;
    let cancelled = false;
    const urls: string[] = [];
    let styleEl: HTMLStyleElement | null = null;
    void (async () => {
      // Per-font try/catch (not one Promise.all catch): a single failed fetch
      // must not abandon the URLs its siblings already minted — every created
      // object URL goes into `urls` so the cleanup below always revokes it.
      const faces = await Promise.all(
        fonts.map(async (f) => {
          try {
            const blob = await fetchCertificateFontBlob(competitionId, f.id);
            const url = URL.createObjectURL(blob);
            urls.push(url);
            return customFontFaceCss(`custom:${f.id}`, url, f.format);
          } catch {
            // A font that fails to load falls back to sans-serif on the canvas;
            // the server render still uses it from storage.
            return "";
          }
        }),
      );
      if (cancelled) {
        urls.forEach((u) => URL.revokeObjectURL(u));
        return;
      }
      styleEl = document.createElement("style");
      styleEl.textContent = faces.join("\n");
      document.head.appendChild(styleEl);
    })();
    return () => {
      cancelled = true;
      if (styleEl) document.head.removeChild(styleEl);
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [customFonts.data, competitionId]);

  // Revoke the server-preview object URL on unmount (the designer is unmounted
  // when the Settings tab switches away) — the manual revokes on replace/close
  // don't cover that path.
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const hasBgImage = Boolean(template.data?.has_background_image);
  const bgKind = edited?.background_kind ?? template.data?.background_kind;
  const bgImage = useCertificateBackgroundImage(
    competitionId,
    bgKind === "upload" && hasBgImage,
  );
  // Object-URL lifecycle: create in the effect and revoke on cleanup. (Not
  // useMemo — a memo can mint a URL on a render that never commits, leaking it.)
  const [bgUrl, setBgUrl] = useState<string | null>(null);
  useEffect(() => {
    const url = bgImage.data ? URL.createObjectURL(bgImage.data) : null;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing an external resource (object URL), the sanctioned effect+setState case
    setBgUrl(url);
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [bgImage.data]);

  const tokens = useMemo(
    () => Object.fromEntries((manifest.data?.tokens ?? []).map((t) => [t.key, t.sample])),
    [manifest.data],
  );

  if (manifest.isLoading || template.isLoading || !template.data || !manifest.data) {
    return <Skeleton className="h-96 w-full" />;
  }

  // The editable design: the server template until the user edits it. Derived in
  // render (not an init effect), so `draft` is always the current, non-null value.
  const draft = edited ?? toInput(template.data);
  const bounds = manifest.data.bounds;
  const defaultFont = manifest.data.default_font;
  const released = template.data.released;
  const sel = selected !== null ? draft.elements[selected] : null;
  const selectedPreset =
    draft.background_kind === "preset"
      ? (manifest.data.presets.find((p) => p.id === draft.background_preset) ?? null)
      : null;
  // Bundled fonts + this competition's uploaded custom fonts, for the picker.
  const fontOptions = [
    ...manifest.data.fonts,
    ...(customFonts.data ?? []).map((f) => ({ id: `custom:${f.id}`, label: f.name })),
  ];
  // Release uses the SAVED template, so guard against releasing a stale design
  // while the on-screen edits are unsaved.
  const isDirty =
    edited !== null && JSON.stringify(edited) !== JSON.stringify(toInput(template.data));

  function patch(p: Partial<CertificateTemplateInput>) {
    setEdited({ ...draft, ...p });
  }
  function patchElement(i: number, p: Partial<CertElement>) {
    setEdited({
      ...draft,
      elements: draft.elements.map((e, idx) => (idx === i ? { ...e, ...p } : e)),
    });
  }
  function addElement(el: CertElement) {
    setEdited({ ...draft, elements: [...draft.elements, el] });
    setSelected(draft.elements.length);
  }
  function removeElement(i: number) {
    setEdited({ ...draft, elements: draft.elements.filter((_, idx) => idx !== i) });
    setSelected(null);
  }

  function onSave() {
    save.mutate(draft, {
      onSuccess: () => toast("Certificate design saved", { variant: "success" }),
      onError: (e) =>
        toast("Couldn't save", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  function onPreview() {
    preview.mutate(draft, {
      onSuccess: (blob) => {
        setPreviewUrl((old) => {
          if (old) URL.revokeObjectURL(old);
          return URL.createObjectURL(blob);
        });
      },
      onError: (e) =>
        toast("Preview failed", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  async function onRelease() {
    if (
      !(await confirm({
        title: "Release certificates?",
        description:
          "Every eligible participant will be able to download their certificate (from the saved design) and will be notified. Save your design first if you have unsaved changes.",
        confirmLabel: "Release now",
        destructive: false,
      }))
    )
      return;
    release.mutate(undefined, {
      onSuccess: () => toast("Certificates released", { variant: "success" }),
      onError: (e) =>
        toast("Couldn't release", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  function onExport() {
    createExport.mutate(undefined, {
      onSuccess: (j) => setJobId(j.id),
      onError: (e) =>
        toast("Export failed to start", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  async function onDeleteFont(id: string) {
    if (
      !(await confirm({
        title: "Remove this font?",
        description: "Any element still using it will fall back to a default font.",
        confirmLabel: "Remove",
        destructive: true,
      }))
    )
      return;
    deleteFont.mutate(id, {
      onSuccess: () => toast("Font removed", { variant: "success" }),
      onError: (e) =>
        toast("Couldn't remove font", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  function onExportTemplate() {
    exportTpl.mutate("certificate-template.json", {
      onError: (e) =>
        toast("Export failed", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  async function onImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (
      !(await confirm({
        title: "Import this template?",
        description: template.data?.released
          ? "This certificate has already been released — importing will immediately change what participants download. Background, elements, colours and fonts are all replaced."
          : "This replaces the current design — background, elements, colours and fonts. Release status is left unchanged.",
        confirmLabel: "Import",
        destructive: true,
      }))
    )
      return;
    let doc: unknown;
    try {
      doc = JSON.parse(await file.text());
    } catch {
      toast("Import failed", { description: "That file isn't valid JSON.", variant: "destructive" });
      return;
    }
    importTpl.mutate(doc, {
      onSuccess: () => {
        setEdited(null);
        setSelected(null);
        toast("Template imported", { variant: "success" });
      },
      onError: (err) =>
        toast("Import failed", { description: (err as Error).message, variant: "destructive" }),
    });
  }

  const num = (v: string, fallback: number) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      {/* Canvas */}
      <div className="space-y-3">
        <CertificateCanvas
          competitionId={competitionId}
          aspectRatio={manifest.data.canvas.aspect_ratio}
          backgroundKind={draft.background_kind}
          backgroundColor={draft.background_color}
          backgroundPreset={draft.background_preset}
          presetAccent={draft.preset_accent}
          presetBase={draft.preset_base}
          backgroundImageUrl={bgUrl}
          elements={draft.elements}
          tokens={tokens}
          selectedIndex={selected}
          onSelect={setSelected}
          onMove={(i, x, y) => patchElement(i, { x, y })}
          editable
        />
        <p className="text-xs text-muted-foreground">
          Drag elements to position them — they snap to the canvas centre, edges,
          and other elements (hold Alt to move freely). A subtle Flagpost mark is
          added along the bottom of every certificate.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={onSave} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save design"}
          </Button>
          <Button size="sm" variant="outline" onClick={onPreview} disabled={preview.isPending}>
            {preview.isPending ? "Rendering…" : "Preview"}
          </Button>
        </div>
      </div>

      {/* Controls */}
      <div className="space-y-6">
        {released && template.data?.released_at && (
          <div className="rounded-md border border-success/40 bg-success/10 p-3 text-sm">
            <Badge variant="secondary" className="mb-1">Released</Badge>
            <p className="text-muted-foreground">
              Certificates were released on{" "}
              {parseServerDate(template.data.released_at).toLocaleString()}.
            </p>
          </div>
        )}

        {/* Add elements */}
        <section className="space-y-2">
          <Label>Add element</Label>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={draft.elements.length >= bounds.max_elements}
              onClick={() =>
                addElement(newCertElement("text", defaultFont, { text: "Text", font_size: 6 }))
              }
            >
              + Text
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={draft.elements.length >= bounds.max_elements}
              onClick={() =>
                addElement(
                  newCertElement("token", defaultFont, {
                    token: manifest.data!.tokens[0]?.key ?? "recipient_name",
                    font_size: 7,
                  }),
                )
              }
            >
              + Token
            </Button>
            <label className="inline-flex">
              <span className="sr-only">Add image element</span>
              <Button asChild size="sm" variant="outline" disabled={uploadImg.isPending}>
                <span className="cursor-pointer">{uploadImg.isPending ? "Uploading…" : "+ Image"}</span>
              </Button>
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  uploadImg.mutate(file, {
                    onSuccess: ({ image_key }) =>
                      addElement(newCertElement("image", defaultFont, { image_key, width: 25 })),
                    onError: (err) =>
                      toast("Image upload failed", {
                        description: (err as Error).message,
                        variant: "destructive",
                      }),
                  });
                }}
              />
            </label>
          </div>
        </section>

        {/* Selected element */}
        {sel && selected !== null && (
          <section className="space-y-3 rounded-md border border-border p-3">
            <div className="flex items-center justify-between">
              <Label>Selected {sel.type}</Label>
              <Button size="sm" variant="ghost" onClick={() => removeElement(selected!)}>
                Remove
              </Button>
            </div>

            {sel.type === "text" && (
              <Input
                value={sel.text ?? ""}
                maxLength={bounds.max_text_len}
                onChange={(e) => patchElement(selected!, { text: e.target.value })}
                placeholder="Certificate text"
              />
            )}
            {sel.type === "token" && (
              <Select
                value={sel.token ?? ""}
                onChange={(e) => patchElement(selected!, { token: e.target.value })}
              >
                {manifest.data.tokens.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.label}
                  </option>
                ))}
              </Select>
            )}

            {sel.type !== "image" && (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">Font</Label>
                    <Select
                      value={sel.font ?? defaultFont}
                      onChange={(e) => patchElement(selected!, { font: e.target.value })}
                    >
                      {fontOptions.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.label}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Colour</Label>
                    <input
                      type="color"
                      aria-label="Text colour"
                      className="h-10 w-full cursor-pointer rounded-md border border-input bg-background"
                      value={sel.color ?? CERT_DEFAULT_TEXT}
                      onChange={(e) => patchElement(selected!, { color: e.target.value })}
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">
                    Size ({sel.font_size?.toFixed(1)}% of height)
                  </Label>
                  <input
                    type="range"
                    className="w-full"
                    min={bounds.font_size_min}
                    max={bounds.font_size_max}
                    step={0.5}
                    value={sel.font_size ?? 6}
                    onChange={(e) => patchElement(selected!, { font_size: num(e.target.value, 6) })}
                  />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {(["left", "center", "right"] as const).map((a) => (
                    <Button
                      key={a}
                      size="sm"
                      variant={sel.align === a ? "default" : "outline"}
                      onClick={() => patchElement(selected!, { align: a })}
                    >
                      {a}
                    </Button>
                  ))}
                  <Button
                    size="sm"
                    variant={sel.bold ? "default" : "outline"}
                    onClick={() => patchElement(selected!, { bold: !sel.bold })}
                  >
                    Bold
                  </Button>
                  <Button
                    size="sm"
                    variant={sel.italic ? "default" : "outline"}
                    onClick={() => patchElement(selected!, { italic: !sel.italic })}
                  >
                    Italic
                  </Button>
                </div>
              </>
            )}

            <div className="space-y-1">
              <Label className="text-xs">Width ({sel.width.toFixed(0)}%)</Label>
              <input
                type="range"
                className="w-full"
                min={5}
                max={100}
                step={1}
                value={sel.width}
                onChange={(e) => patchElement(selected!, { width: num(e.target.value, 50) })}
              />
            </div>
          </section>
        )}

        {/* Background */}
        <section className="space-y-2">
          <Label>Background</Label>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant={draft.background_kind === "color" ? "default" : "outline"}
              onClick={() => patch({ background_kind: "color" })}
            >
              Colour
            </Button>
            <Button
              size="sm"
              variant={draft.background_kind === "preset" ? "default" : "outline"}
              onClick={() =>
                patch({
                  background_kind: "preset",
                  background_preset: draft.background_preset ?? manifest.data!.presets[0]?.id ?? null,
                })
              }
            >
              Preset
            </Button>
            <label className="inline-flex">
              <Button asChild size="sm" variant={draft.background_kind === "upload" ? "default" : "outline"} disabled={uploadBg.isPending}>
                <span className="cursor-pointer">{uploadBg.isPending ? "Uploading…" : "Upload"}</span>
              </Button>
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  uploadBg.mutate(file, {
                    onSuccess: () => {
                      patch({ background_kind: "upload" });
                      toast("Background uploaded", { variant: "success" });
                    },
                    onError: (err) =>
                      toast("Upload failed", {
                        description: (err as Error).message,
                        variant: "destructive",
                      }),
                  });
                }}
              />
            </label>
          </div>
          {draft.background_kind === "color" && (
            <input
              type="color"
              aria-label="Background colour"
              className="h-10 w-full cursor-pointer rounded-md border border-input bg-background"
              value={draft.background_color}
              onChange={(e) => patch({ background_color: e.target.value })}
            />
          )}
          {draft.background_kind === "preset" && (
            <div className="grid grid-cols-4 gap-2">
              {manifest.data.presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  // Reset colour overrides when switching preset (colours are
                  // preset-specific; each starts at its own defaults).
                  onClick={() =>
                    patch({ background_preset: p.id, preset_accent: null, preset_base: null })
                  }
                  className={
                    "overflow-hidden rounded-md border-2 " +
                    (draft.background_preset === p.id ? "border-primary" : "border-border")
                  }
                  title={p.label}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={certPresetUrl(p.id)} alt={p.label} className="aspect-[1.414] w-full object-cover" />
                </button>
              ))}
            </div>
          )}
          {selectedPreset && (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">Accent colour</Label>
                  <input
                    type="color"
                    aria-label="Preset accent colour"
                    className="h-10 w-full cursor-pointer rounded-md border border-input bg-background"
                    value={draft.preset_accent ?? selectedPreset.accent}
                    onChange={(e) => patch({ preset_accent: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Base colour</Label>
                  <input
                    type="color"
                    aria-label="Preset base colour"
                    className="h-10 w-full cursor-pointer rounded-md border border-input bg-background"
                    value={draft.preset_base ?? selectedPreset.base}
                    onChange={(e) => patch({ preset_base: e.target.value })}
                  />
                </div>
              </div>
              {(draft.preset_accent || draft.preset_base) && (
                <button
                  type="button"
                  className="text-xs text-muted-foreground underline"
                  onClick={() => patch({ preset_accent: null, preset_base: null })}
                >
                  Reset to preset default colours
                </button>
              )}
            </div>
          )}
          {draft.background_kind === "upload" && !hasBgImage && (
            <p className="text-xs text-muted-foreground">
              Upload a landscape, roughly A4-proportioned image (PNG/JPEG/WebP).
            </p>
          )}
        </section>

        {/* Recipients + release */}
        <section className="space-y-3">
          <div className="space-y-1">
            <Label>Recipients</Label>
            <Select
              value={draft.recipient_rule}
              onChange={(e) => patch({ recipient_rule: e.target.value as CertificateTemplateInput["recipient_rule"] })}
            >
              <option value="all">All participants</option>
              <option value="solvers">Only participants who scored</option>
            </Select>
          </div>
          <div className="space-y-1">
            <Label>Release timing</Label>
            <Select
              value={draft.release_mode}
              onChange={(e) => patch({ release_mode: e.target.value as CertificateTemplateInput["release_mode"] })}
            >
              <option value="manual">Manual — I&apos;ll release them</option>
              <option value="on_end">Automatically when the competition ends</option>
              <option value="end_delay">A set time after the competition ends</option>
            </Select>
          </div>
          {draft.release_mode === "end_delay" && (
            <div className="space-y-1">
              <Label className="text-xs">Minutes after end</Label>
              <Input
                type="number"
                min={0}
                value={draft.release_delay_minutes}
                onChange={(e) => patch({ release_delay_minutes: Math.max(0, num(e.target.value, 0)) })}
              />
            </div>
          )}
          {!released && (
            <div className="space-y-1">
              <Button
                size="sm"
                variant="secondary"
                onClick={onRelease}
                disabled={release.isPending || isDirty}
              >
                {release.isPending ? "Releasing…" : "Release certificates now"}
              </Button>
              {isDirty && (
                <p className="text-xs text-warning">Save your design before releasing.</p>
              )}
            </div>
          )}
        </section>

        {/* Bulk export */}
        <section className="space-y-2 border-t border-border pt-4">
          <Label>Bulk export</Label>
          <p className="text-xs text-muted-foreground">
            Render every recipient&apos;s certificate into a single ZIP.
          </p>
          <Button size="sm" variant="outline" onClick={onExport} disabled={createExport.isPending || job.data?.status === "pending" || job.data?.status === "running"}>
            {job.data?.status === "pending" || job.data?.status === "running"
              ? `Rendering… (${job.data?.rendered ?? 0}/${job.data?.total ?? 0})`
              : "Export all as ZIP"}
          </Button>
          {job.data?.status === "done" && job.data.download_url && (
            <Button asChild size="sm">
              <a href={job.data.download_url} download>
                Download ZIP ({job.data.rendered} certificates)
              </a>
            </Button>
          )}
          {job.data?.status === "failed" && (
            <p className="text-xs text-destructive">Export failed: {job.data.error}</p>
          )}
        </section>

        {/* Custom fonts */}
        <section className="space-y-2 border-t border-border pt-4">
          <Label>Custom fonts</Label>
          <p className="text-xs text-muted-foreground">
            Upload a company or brand font (TTF or OTF) to use on text and token
            elements. Only upload fonts you are licensed to use — they are stored
            with this competition and used solely to render its certificates.
          </p>
          <label className="inline-flex">
            <span className="sr-only">Upload custom font</span>
            <Button asChild size="sm" variant="outline" disabled={uploadFont.isPending}>
              <span className="cursor-pointer">
                {uploadFont.isPending ? "Uploading…" : "Upload font"}
              </span>
            </Button>
            <input
              type="file"
              accept=".ttf,.otf,font/ttf,font/otf"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (!file) return;
                uploadFont.mutate(
                  { file },
                  {
                    onSuccess: () => toast("Font uploaded", { variant: "success" }),
                    onError: (err) =>
                      toast("Font upload failed", {
                        description: (err as Error).message,
                        variant: "destructive",
                      }),
                  },
                );
              }}
            />
          </label>
          {(customFonts.data?.length ?? 0) > 0 && (
            <ul className="space-y-1">
              {customFonts.data!.map((f) => (
                <li
                  key={f.id}
                  className="flex items-center justify-between rounded-md border border-border px-2 py-1 text-sm"
                >
                  <span className="truncate" style={{ fontFamily: certFontFamily(`custom:${f.id}`) }}>
                    {f.name}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onDeleteFont(f.id)}
                    disabled={deleteFont.isPending}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Reusable template (export / import) */}
        <section className="space-y-2 border-t border-border pt-4">
          <Label>Reusable template</Label>
          <p className="text-xs text-muted-foreground">
            Save this design — including uploaded images and fonts — as a single
            file, then import it into another competition or a future event.
            Exports the last saved design; importing replaces the current one.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={onExportTemplate}
              disabled={exportTpl.isPending || !template.data?.id}
            >
              {exportTpl.isPending ? "Exporting…" : "Export template"}
            </Button>
            <label className="inline-flex">
              <span className="sr-only">Import template file</span>
              <Button asChild size="sm" variant="outline" disabled={importTpl.isPending}>
                <span className="cursor-pointer">
                  {importTpl.isPending ? "Importing…" : "Import template"}
                </span>
              </Button>
              <input
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={onImportFile}
              />
            </label>
          </div>
        </section>
      </div>

      {/* Server-rendered preview */}
      <Dialog
        open={Boolean(previewUrl)}
        onOpenChange={(o) => {
          if (!o) {
            setPreviewUrl((old) => {
              if (old) URL.revokeObjectURL(old);
              return null;
            });
          }
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Certificate preview</DialogTitle>
          </DialogHeader>
          {previewUrl && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img src={previewUrl} alt="Certificate preview" className="w-full rounded-md border border-border" />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
