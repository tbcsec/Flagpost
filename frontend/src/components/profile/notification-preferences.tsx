"use client";

import { useEffect, useState } from "react";

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

const IN_APP: { key: PrefKey; label: string; hint: string }[] = [
  {
    key: "inapp_tickets",
    label: "Support tickets",
    hint: "New tickets, replies, assignments, and resolutions.",
  },
  {
    key: "inapp_automations",
    label: "Automations & alerts",
    hint: "Notifications sent to you by competition automation rules.",
  },
];

// Notification preferences (§4.4). In-app toggles gate whether a bell
// notification is created at all; browser + sound are client-honored delivery
// hints for the notifications you do receive.
export function NotificationPreferencesCard() {
  const { data, isLoading } = useNotificationPreferences();
  const update = useUpdateNotificationPreferences();
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);

  useEffect(() => {
    if (data) setPrefs(data);
  }, [data]);

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
        toast("Browser notifications are blocked", {
          description: "Allow notifications for this site in your browser settings, then try again.",
          variant: "destructive",
        });
        return;
      }
      if (Notification.permission !== "granted") {
        const result = await Notification.requestPermission();
        if (result !== "granted") {
          toast("Permission not granted", {
            description: "Browser notifications stay off until you allow them.",
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
      onSuccess: () => toast("Preferences saved", { variant: "success" }),
      onError: (e) =>
        toast("Couldn't save", {
          description: (e as Error).message,
          variant: "destructive",
        }),
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Notification preferences</CardTitle>
        <CardDescription>
          Control what reaches your notification bell, and how you&apos;re alerted.
        </CardDescription>
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
                In-app notifications
              </h3>
              <div className="grid max-w-md gap-3">
                {IN_APP.map((row) => (
                  <PrefRow
                    key={row.key}
                    label={row.label}
                    hint={row.hint}
                    checked={prefs[row.key]}
                    onChange={(v) => set(row.key, v)}
                  />
                ))}
              </div>
            </section>

            <section className="grid gap-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Delivery
              </h3>
              <div className="grid max-w-md gap-3">
                <PrefRow
                  label="Browser notifications"
                  hint="Show a desktop notification when something arrives while Flagpost is open."
                  checked={prefs.browser}
                  onChange={onToggleBrowser}
                />
                <PrefRow
                  label="Sound for support tickets"
                  hint="Play a short cue when a new ticket or reply comes in."
                  checked={prefs.sound}
                  onChange={(v) => set("sound", v)}
                />
              </div>
            </section>

            <div className="flex items-center gap-3">
              <Button className="w-fit" onClick={onSave} disabled={!dirty || update.isPending}>
                {update.isPending ? "Saving…" : "Save preferences"}
              </Button>
              {dirty && (
                <span className="text-xs text-muted-foreground">Unsaved changes</span>
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
