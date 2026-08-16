"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences,
} from "@/lib/hooks/use-notifications";
import type { NotificationPreferences } from "@/lib/types";
import { toast } from "@/stores/toast";

type PrefKey = keyof NotificationPreferences;

// Labels/hints resolve through profile.notifications.inApp.<key>.* at render;
// this is just the row order (the keys are a subset of PrefKey).
const IN_APP_KEYS = [
  "inapp_tickets",
  "inapp_automations",
  "inapp_announcements",
] as const;

// Notification preferences (§4.4). In-app toggles gate whether a bell
// notification is created at all; browser + sound are client-honored delivery
// hints for the notifications you do receive.
export function NotificationPreferencesCard() {
  const t = useTranslations("profile.notifications");
  const { data, isLoading } = useNotificationPreferences();
  const update = useUpdateNotificationPreferences();
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);

  // Re-baseline the editable copy whenever the server data changes (initial
  // load, and the refetch after a save) — adjust-during-render, not an effect.
  const [seeded, setSeeded] = useState<NotificationPreferences | null>(null);
  if (data && data !== seeded) {
    setSeeded(data);
    setPrefs(data);
  }

  const dirty =
    prefs != null &&
    data != null &&
    (Object.keys(prefs) as PrefKey[]).some((k) => prefs[k] !== data[k]);

  function set(key: PrefKey, value: boolean) {
    setPrefs((p) => (p ? { ...p, [key]: value } : p));
  }

  // Enabling browser notifications needs an OS permission grant — request it
  // when the user first turns it on, and refuse the toggle if it's denied.
  async function onToggleBrowser(value: boolean) {
    if (value && typeof Notification !== "undefined") {
      if (Notification.permission === "denied") {
        toast(t("browserBlockedTitle"), {
          description: t("browserBlockedBody"),
          variant: "destructive",
        });
        return;
      }
      if (Notification.permission !== "granted") {
        const result = await Notification.requestPermission();
        if (result !== "granted") {
          toast(t("permissionDeniedTitle"), {
            description: t("permissionDeniedBody"),
          });
          return;
        }
      }
    }
    set("browser", value);
  }

  function onSave() {
    if (!prefs) return;
    update.mutate(prefs, {
      onSuccess: () => toast(t("savedToast"), { variant: "success" }),
      onError: (e) =>
        toast(t("saveError"), {
          description: (e as Error).message,
          variant: "destructive",
        }),
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        {isLoading || !prefs ? (
          <div className="grid max-w-md gap-3">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : (
          <>
            <section className="grid gap-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {t("inAppHeading")}
              </h3>
              <div className="grid max-w-md gap-3">
                {IN_APP_KEYS.map((key) => (
                  <PrefRow
                    key={key}
                    label={t(`inApp.${key}.label`)}
                    hint={t(`inApp.${key}.hint`)}
                    checked={prefs[key]}
                    onChange={(v) => set(key, v)}
                  />
                ))}
              </div>
            </section>

            <section className="grid gap-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {t("deliveryHeading")}
              </h3>
              <div className="grid max-w-md gap-3">
                <PrefRow
                  label={t("browser.label")}
                  hint={t("browser.hint")}
                  checked={prefs.browser}
                  onChange={onToggleBrowser}
                />
                <PrefRow
                  label={t("sound.label")}
                  hint={t("sound.hint")}
                  checked={prefs.sound}
                  onChange={(v) => set("sound", v)}
                />
              </div>
            </section>

            <div className="flex items-center gap-3">
              <Button className="w-fit" onClick={onSave} disabled={!dirty || update.isPending}>
                {update.isPending ? t("saving") : t("save")}
              </Button>
              {dirty && (
                <span className="text-xs text-muted-foreground">{t("unsaved")}</span>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function PrefRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex items-start justify-between gap-4">
      <span className="grid gap-0.5">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </span>
      <input
        type="checkbox"
        className="mt-1 h-4 w-4 flex-shrink-0 rounded border-border"
        style={{ accentColor: "hsl(var(--primary))" }}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
    </label>
  );
}
