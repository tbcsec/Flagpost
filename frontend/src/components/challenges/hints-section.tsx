"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { parseServerDate } from "@/lib/datetime";
import {
  useCreateHint,
  useDeleteHint,
  useHints,
  useUpdateHint,
} from "@/lib/hooks/use-hints";

// datetime-local -> stored ISO. The input is read as the author's *local* time
// and the badge renders it back in local time (parseServerDate + toLocaleString),
// so what you enter is what you see — unlike the UTC-in/UTC-out schedule form.
const fromInput = (v: string) => (v ? new Date(v).toISOString() : null);

// Hint authoring inside the challenge editor (Phase 9). Like attachments, this
// needs a persisted challenge id, so it only appears in edit mode. Editors see
// every hint body (the list endpoint returns them revealed for challenge_edit),
// plus the publish state — a hint can be authored hidden and released later,
// manually here, on a schedule, or by the publish_hint automation (#213).
export function HintsSection({
  competitionId,
  challengeId,
}: {
  competitionId: string;
  challengeId: string;
}) {
  const t = useTranslations("challenges.admin.hints");
  const hints = useHints(competitionId, challengeId);
  const create = useCreateHint(competitionId, challengeId);
  const update = useUpdateHint(competitionId, challengeId);
  const remove = useDeleteHint(competitionId, challengeId);
  const confirm = useConfirm();
  const [body, setBody] = useState("");
  const [cost, setCost] = useState("0");
  const [hidden, setHidden] = useState(false);
  const [releaseAt, setReleaseAt] = useState("");

  async function onRemove(id: string) {
    if (
      await confirm({
        title: t("deleteConfirmTitle"),
        description: t("deleteConfirmDescription"),
        confirmLabel: t("deleteConfirmLabel"),
      })
    ) {
      remove.mutate(id);
    }
  }

  function onAdd(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        body,
        cost: Number(cost) || 0,
        hidden,
        release_at: hidden ? fromInput(releaseAt) : null,
      },
      {
        onSuccess: () => {
          setBody("");
          setCost("0");
          setHidden(false);
          setReleaseAt("");
        },
      },
    );
  }

  return (
    <div className="grid gap-3">
      <Label>{t("title")}</Label>
      {hints.data && hints.data.length > 0 && (
        <ul className="grid gap-2">
          {hints.data.map((hint) => (
            <li
              key={hint.id}
              className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm"
            >
              <span className="min-w-0 flex-1 truncate">{hint.body}</span>
              {hint.hidden && (
                <Badge variant="warning" className="whitespace-nowrap">
                  {hint.release_at
                    ? t("releases", {
                        date: parseServerDate(hint.release_at).toLocaleString([], {
                          dateStyle: "medium",
                          timeStyle: "short",
                        }),
                      })
                    : t("hidden")}
                </Badge>
              )}
              <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                {t("cost", { cost: hint.cost })}
              </span>
              {hint.hidden && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={update.isPending}
                  onClick={() =>
                    update.mutate({ hintId: hint.id, patch: { hidden: false } })
                  }
                >
                  {t("publish")}
                </Button>
              )}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-destructive"
                disabled={remove.isPending}
                onClick={() => onRemove(hint.id)}
              >
                {t("remove")}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={onAdd} className="grid gap-2">
        <div className="flex items-end gap-2">
          <div className="grid flex-1 gap-1">
            <Input
              value={body}
              placeholder={t("bodyPlaceholder")}
              onChange={(e) => setBody(e.target.value)}
              required
            />
          </div>
          <div className="grid w-24 gap-1">
            <Input
              type="number"
              min={0}
              value={cost}
              aria-label={t("costAria")}
              onChange={(e) => setCost(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={create.isPending}>
            {t("add")}
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={hidden}
              onChange={(e) => setHidden(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            {t("hiddenUntilReleased")}
          </label>
          {hidden && (
            <label className="flex items-center gap-2">
              {t("releaseLabel")}
              <Input
                type="datetime-local"
                value={releaseAt}
                onChange={(e) => setReleaseAt(e.target.value)}
                className="h-8 w-auto"
                aria-label={t("releaseTimeAria")}
              />
            </label>
          )}
        </div>
      </form>
      {create.isError && (
        <p role="alert" className="text-sm text-destructive">
          {(create.error as Error).message}
        </p>
      )}
      {update.isError && (
        <p role="alert" className="text-sm text-destructive">
          {(update.error as Error).message}
        </p>
      )}
    </div>
  );
}
