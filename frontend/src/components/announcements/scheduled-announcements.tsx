"use client";

// The staff management list for scheduled announcements (#349): every pending
// draft with its go-live time, and the two things the issue asks for — edit
// (reschedule / publish now) and cancel — while it's still scheduled. Manager-
// only (the route gates on announcement_create); renders nothing when empty, so
// it stays out of the way until an organiser actually schedules something.

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import { Input } from "@/components/ui/input";
import { parseServerDate } from "@/lib/datetime";
import {
  useDeleteAnnouncement,
  useScheduledAnnouncements,
  useUpdateAnnouncement,
} from "@/lib/hooks/use-announcements";
import type { Announcement } from "@/lib/types";
import { toast } from "@/stores/toast";

// datetime-local (author's local time) <-> stored ISO, matching the composer.
const fromInput = (v: string) => (v ? new Date(v).toISOString() : null);
function toInput(iso: string | null): string {
  if (!iso) return "";
  const d = parseServerDate(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

export function ScheduledAnnouncements({
  competitionId,
}: {
  competitionId: string;
}) {
  const t = useTranslations("announcements.scheduled");
  const { data } = useScheduledAnnouncements(competitionId);
  if (!data || data.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {data.map((a) => (
          <ScheduledRow
            key={a.id}
            competitionId={competitionId}
            announcement={a}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function ScheduledRow({
  competitionId,
  announcement,
}: {
  competitionId: string;
  announcement: Announcement;
}) {
  const t = useTranslations("announcements.scheduled");
  const [when, setWhen] = useState(toInput(announcement.publish_at));
  const update = useUpdateAnnouncement(competitionId);
  const remove = useDeleteAnnouncement(competitionId);
  const confirm = useConfirm();

  const scheduledLabel = announcement.publish_at
    ? parseServerDate(announcement.publish_at).toLocaleString([], {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "";

  function reschedule() {
    if (!when) return;
    update.mutate(
      { id: announcement.id, patch: { publish_at: fromInput(when) } },
      { onSuccess: () => toast(t("rescheduledToast"), { variant: "success" }) },
    );
  }

  function publishNow() {
    update.mutate(
      { id: announcement.id, patch: { publish_at: null } },
      { onSuccess: () => toast(t("publishedToast"), { variant: "success" }) },
    );
  }

  async function cancel() {
    if (
      !(await confirm({
        title: t("cancelConfirmTitle"),
        description: t("cancelConfirmDescription"),
        confirmLabel: t("cancelConfirm"),
        destructive: true,
      }))
    ) {
      return;
    }
    remove.mutate(announcement.id, {
      onSuccess: () => toast(t("cancelledToast"), { variant: "success" }),
    });
  }

  const busy = update.isPending || remove.isPending;

  return (
    <div className="grid gap-2 rounded-md border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate font-medium">{announcement.title}</span>
        <Badge variant="secondary" className="flex-shrink-0">
          {t("scheduledFor", { date: scheduledLabel })}
        </Badge>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="datetime-local"
          aria-label={t("rescheduleLabel")}
          value={when}
          onChange={(e) => setWhen(e.target.value)}
          className="h-8 w-auto"
        />
        <Button
          size="sm"
          variant="outline"
          onClick={reschedule}
          disabled={busy || !when}
        >
          {t("reschedule")}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={publishNow}
          disabled={busy}
        >
          {t("publishNow")}
        </Button>
        <Button size="sm" variant="ghost" onClick={cancel} disabled={busy}>
          {t("cancel")}
        </Button>
      </div>
    </div>
  );
}
