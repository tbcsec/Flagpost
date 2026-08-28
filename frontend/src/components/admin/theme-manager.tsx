"use client";

/* eslint-disable no-restricted-syntax --
   This is the custom-theme *editor*: raw #RRGGBB values are its domain data (the
   brand colours an admin authors), not hardcoded UI colours. The design-token
   rule (§9) that bans inline hex in components doesn't apply here, the same way
   the brand mark is excepted. All surrounding UI still uses tokens. */

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  useCreateTheme,
  useDeleteTheme,
  useThemes,
  useUpdateTheme,
} from "@/lib/hooks/use-themes";
import { THEME_TOKENS } from "@/lib/theme";
import type { ThemeMode, ThemePreset } from "@/lib/types";
import { toast } from "@/stores/toast";

// Admin → Appearance → Custom themes (#323, ADR-0011). Curates the site-wide
// theme library the palette picker selects the active theme from. A theme is a
// complete pack of the design tokens; the editor previews it in a scoped card
// (not the whole admin — that's what *selecting* the active theme does).

const HEX = /^#[0-9a-fA-F]{6}$/;

// A neutral dark starting point so "New theme" never opens blank; the token
// format matches the backend (all THEME_TOKENS, #RRGGBB).
const STARTER: Record<string, string> = {
  background: "#0f1420", foreground: "#e6ebf5",
  card: "#151b2b", "card-foreground": "#e6ebf5",
  popover: "#151b2b", "popover-foreground": "#e6ebf5",
  primary: "#4f8cff", "primary-foreground": "#0f1420",
  secondary: "#1e2740", "secondary-foreground": "#e6ebf5",
  muted: "#1a2233", "muted-foreground": "#8a99b8",
  accent: "#1e2740", "accent-foreground": "#e6ebf5",
  destructive: "#f2555a", "destructive-foreground": "#0f1420",
  success: "#34d399", "success-foreground": "#0f1420",
  warning: "#fbbf24", "warning-foreground": "#0f1420",
  border: "#263149", input: "#263149", ring: "#4f8cff",
};

// Editor layout — the tokens grouped by role. Every THEME_TOKENS key appears once.
type GroupKey = "surfaces" | "text" | "actions" | "status" | "borders";
const GROUPS: { key: GroupKey; tokens: string[] }[] = [
  { key: "surfaces", tokens: ["background", "card", "popover", "secondary", "muted", "accent"] },
  { key: "text", tokens: ["foreground", "card-foreground", "popover-foreground", "secondary-foreground", "muted-foreground", "accent-foreground"] },
  { key: "actions", tokens: ["primary", "primary-foreground", "ring"] },
  { key: "status", tokens: ["destructive", "destructive-foreground", "success", "success-foreground", "warning", "warning-foreground"] },
  { key: "borders", tokens: ["border", "input"] },
];

interface Draft {
  id: string;
  name: string;
  mode: ThemeMode;
  tokens: Record<string, string>;
  isNew: boolean;
}

function download(preset: ThemePreset) {
  const doc = { id: preset.id, name: preset.name, mode: preset.mode, tokens: preset.tokens };
  const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${preset.id}.theme.json`;
  a.click();
  URL.revokeObjectURL(url);
}

export function ThemeManager() {
  const t = useTranslations("admin.themes");
  const { data: themes, isLoading } = useThemes();
  const create = useCreateTheme();
  const update = useUpdateTheme();
  const remove = useDeleteTheme();
  const confirm = useConfirm();

  const [draft, setDraft] = useState<Draft | null>(null);

  function startNew() {
    setDraft({ id: "", name: "", mode: "dark", tokens: { ...STARTER }, isNew: true });
  }
  function startEdit(p: ThemePreset) {
    setDraft({ id: p.id, name: p.name, mode: p.mode, tokens: { ...p.tokens }, isNew: false });
  }

  function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    file.text().then((text) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(text);
      } catch {
        toast(t("badFile"), { variant: "destructive" });
        return;
      }
      const doc = parsed as Partial<Draft>;
      const tokens = (doc.tokens ?? {}) as Record<string, string>;
      const missing = THEME_TOKENS.filter((tok) => !HEX.test(tokens[tok] ?? ""));
      if (missing.length) {
        toast(t("badFileTokens", { count: missing.length }), { variant: "destructive" });
        return;
      }
      setDraft({
        id: typeof doc.id === "string" ? doc.id : "",
        name: typeof doc.name === "string" ? doc.name : "",
        mode: doc.mode === "light" ? "light" : "dark",
        tokens: Object.fromEntries(THEME_TOKENS.map((tok) => [tok, tokens[tok]])),
        isNew: true,
      });
    });
  }

  function onSave() {
    if (!draft) return;
    if (draft.isNew && !/^[a-z][a-z0-9-]{1,31}$/.test(draft.id)) {
      toast(t("invalidId"), { variant: "destructive" });
      return;
    }
    if (!draft.name.trim()) {
      toast(t("nameRequired"), { variant: "destructive" });
      return;
    }
    const bad = THEME_TOKENS.find((tok) => !HEX.test(draft.tokens[tok] ?? ""));
    if (bad) {
      toast(t("invalidColor", { token: bad }), { variant: "destructive" });
      return;
    }
    const onError = (e: unknown) =>
      toast(t("couldntSave"), { description: (e as Error).message, variant: "destructive" });
    const onSuccess = () => {
      toast(t("saved"), { variant: "success" });
      setDraft(null);
    };
    if (draft.isNew) {
      create.mutate(
        { id: draft.id, name: draft.name.trim(), mode: draft.mode, tokens: draft.tokens },
        { onSuccess, onError },
      );
    } else {
      update.mutate(
        { id: draft.id, input: { name: draft.name.trim(), mode: draft.mode, tokens: draft.tokens } },
        { onSuccess, onError },
      );
    }
  }

  async function onDelete(p: ThemePreset) {
    if (!(await confirm({ title: t("deleteTitle", { name: p.name }), description: t("deleteDescription"), confirmLabel: t("delete") }))) {
      return;
    }
    remove.mutate(p.id, {
      onSuccess: () => toast(t("deleted"), { variant: "success" }),
      onError: (e) => toast(t("couldntDelete"), { description: (e as Error).message, variant: "destructive" }),
    });
  }

  const saving = create.isPending || update.isPending;

  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {t("heading")}
        </h3>
        {!draft && (
          <div className="flex items-center gap-2">
            <label>
              <span className="inline-flex h-9 cursor-pointer items-center rounded-md border border-border px-3 text-sm font-medium hover:bg-accent/60">
                {t("upload")}
              </span>
              <input type="file" accept="application/json,.json" className="hidden" onChange={onUpload} />
            </label>
            <Button size="sm" onClick={startNew}>{t("newTheme")}</Button>
          </div>
        )}
      </div>
      <p className="max-w-prose text-xs text-muted-foreground">{t("description")}</p>

      {draft ? (
        <ThemeEditor
          draft={draft}
          setDraft={setDraft}
          onSave={onSave}
          onCancel={() => setDraft(null)}
          saving={saving}
        />
      ) : isLoading ? (
        <p className="text-sm text-muted-foreground">{t("loading")}</p>
      ) : (themes ?? []).length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <ul className="grid gap-2">
          {(themes ?? []).map((p) => (
            <li
              key={p.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3"
            >
              <div className="flex items-center gap-3">
                <span
                  className="h-8 w-8 shrink-0 rounded-md border border-border"
                  style={{ backgroundColor: p.tokens.background }}
                >
                  <span className="m-1 block h-2 w-4 rounded-sm" style={{ backgroundColor: p.tokens.primary }} />
                </span>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{p.name}</span>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                      {t(`source.${p.source}`)}
                    </span>
                  </div>
                  <span className="font-mono text-[11px] text-muted-foreground">{p.id} · {t(`mode.${p.mode}`)}</span>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="sm" onClick={() => startEdit(p)}>{t("edit")}</Button>
                <Button variant="ghost" size="sm" onClick={() => download(p)}>{t("download")}</Button>
                <Button variant="ghost" size="sm" className="text-destructive" onClick={() => onDelete(p)} disabled={remove.isPending}>
                  {t("delete")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ThemeEditor({
  draft,
  setDraft,
  onSave,
  onCancel,
  saving,
}: {
  draft: Draft;
  setDraft: (d: Draft) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const t = useTranslations("admin.themes");
  const setToken = (token: string, value: string) =>
    setDraft({ ...draft, tokens: { ...draft.tokens, [token]: value } });

  return (
    <div className="grid gap-5 rounded-lg border border-border p-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="grid gap-1.5">
          <Label htmlFor="theme-id">{t("id")}</Label>
          <Input
            id="theme-id"
            value={draft.id}
            disabled={!draft.isNew}
            placeholder="acme-dark"
            onChange={(e) => setDraft({ ...draft, id: e.target.value.toLowerCase() })}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="theme-name">{t("name")}</Label>
          <Input id="theme-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="theme-mode">{t("mode.label")}</Label>
          <Select id="theme-mode" value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value as ThemeMode })}>
            <option value="dark">{t("mode.dark")}</option>
            <option value="light">{t("mode.light")}</option>
          </Select>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_16rem]">
        <div className="grid gap-4">
          {GROUPS.map((g) => (
            <div key={g.key} className="grid gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t(`group.${g.key}`)}</span>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {g.tokens.map((token) => (
                  <div key={token} className="flex items-center gap-2">
                    <input
                      type="color"
                      value={/^#[0-9a-fA-F]{6}$/.test(draft.tokens[token] ?? "") ? draft.tokens[token] : "#000000"}
                      onChange={(e) => setToken(token, e.target.value)}
                      className="h-8 w-8 shrink-0 cursor-pointer rounded border border-border bg-transparent p-0"
                      aria-label={token}
                    />
                    <div className="min-w-0">
                      <div className="truncate font-mono text-[10px] text-muted-foreground">{token}</div>
                      <input
                        value={draft.tokens[token] ?? ""}
                        onChange={(e) => setToken(token, e.target.value)}
                        className="w-full bg-transparent font-mono text-[11px] outline-none"
                        spellCheck={false}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <ThemePreview tokens={draft.tokens} label={t("previewLabel")} />
      </div>

      <div className="flex items-center gap-2">
        <Button onClick={onSave} disabled={saving}>{saving ? t("saving") : t("save")}</Button>
        <Button variant="ghost" onClick={onCancel} disabled={saving}>{t("cancel")}</Button>
      </div>
    </div>
  );
}

// A scoped, self-contained preview of the theme-being-edited — reads the hex
// tokens straight into inline styles so it can't recolour the surrounding admin.
function ThemePreview({ tokens, label }: { tokens: Record<string, string>; label: string }) {
  const c = (k: string) => tokens[k] ?? "#000000";
  return (
    <div className="grid gap-2">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</span>
      <div className="rounded-lg border p-3" style={{ backgroundColor: c("background"), borderColor: c("border") }}>
        <div className="rounded-md border p-3" style={{ backgroundColor: c("card"), borderColor: c("border") }}>
          <div className="text-sm font-medium" style={{ color: c("card-foreground") }}>{label}</div>
          <div className="mt-0.5 text-xs" style={{ color: c("muted-foreground") }}>Aa · the quick brown fox</div>
          <div className="mt-2 flex items-center gap-2">
            <span className="rounded px-2 py-1 text-xs font-medium" style={{ backgroundColor: c("primary"), color: c("primary-foreground") }}>
              Primary
            </span>
            <span className="rounded px-2 py-1 text-xs" style={{ backgroundColor: c("accent"), color: c("accent-foreground") }}>
              Accent
            </span>
            <span className="h-3 w-3 rounded-full" style={{ backgroundColor: c("success") }} />
            <span className="h-3 w-3 rounded-full" style={{ backgroundColor: c("warning") }} />
            <span className="h-3 w-3 rounded-full" style={{ backgroundColor: c("destructive") }} />
          </div>
        </div>
      </div>
    </div>
  );
}
