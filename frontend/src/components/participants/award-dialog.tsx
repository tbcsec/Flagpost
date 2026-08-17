"use client";

import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateAward } from "@/lib/hooks/use-participants";
import type { Participant } from "@/lib/types";
import { toast } from "@/stores/toast";

const TEXTAREA_CLASS =
  "flex min-h-16 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

// Judges (score_override) grant a titled, point-bearing award to one or more
// competitors from the roster. Points fold into the scoreboard immediately.
export function AwardDialog({
  competitionId,
  roster,
  open,
  onOpenChange,
}: {
  competitionId: string;
  roster: Participant[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("participants.award");
  const create = useCreateAward(competitionId);
  // Starts blank on mount: the call site keys this dialog by open-state, so
  // every open remounts it as a fresh award form.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [points, setPoints] = useState("0");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q
      ? roster.filter((p) => p.display_name.toLowerCase().includes(q))
      : roster;
  }, [roster, query]);

  function toggle(userId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (selected.size === 0 || !title.trim()) return;
    create.mutate(
      {
        user_ids: [...selected],
        title: title.trim(),
        description: description.trim() || undefined,
        points: Number(points) || 0,
      },
      {
        onSuccess: (awards) => {
          toast(t("successToast", { count: awards.length }), { variant: "success" });
          onOpenChange(false);
        },
        onError: (err) =>
          toast(t("errorToast"), {
            description: (err as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-2">
            <Label htmlFor="award-title">{t("titleLabel")}</Label>
            <Input
              id="award-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("titlePlaceholder")}
              maxLength={200}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="award-desc">{t("descLabel")}</Label>
            <textarea
              id="award-desc"
              className={TEXTAREA_CLASS}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="award-points">{t("pointsLabel")}</Label>
            <Input
              id="award-points"
              type="number"
              value={points}
              onChange={(e) => setPoints(e.target.value)}
              min={-10000}
              max={10000}
              className="w-32"
            />
            <p className="text-xs text-muted-foreground">{t("pointsHint")}</p>
          </div>
          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label>{t("recipients")}</Label>
              <span className="text-xs text-muted-foreground">
                {t("selectedCount", { count: selected.size })}
              </span>
            </div>
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("searchPlaceholder")}
            />
            <div className="max-h-52 overflow-y-auto rounded-md border border-border">
              {filtered.length === 0 ? (
                <p className="p-3 text-sm text-muted-foreground">{t("noMatch")}</p>
              ) : (
                filtered.map((p) => (
                  <label
                    key={p.user_id}
                    className="flex cursor-pointer items-center gap-2.5 border-b border-border px-3 py-2 text-sm last:border-b-0 hover:bg-accent/40"
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-border"
                      style={{ accentColor: "hsl(var(--primary))" }}
                      checked={selected.has(p.user_id)}
                      onChange={() => toggle(p.user_id)}
                    />
                    <span className="flex-1">{p.display_name}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {t("pts", { points: p.points })}
                    </span>
                  </label>
                ))
              )}
            </div>
          </div>
          {create.error && (
            <p role="alert" className="text-sm text-destructive">{(create.error as Error).message}</p>
          )}
          <DialogFooter>
            <Button
              type="submit"
              disabled={create.isPending || selected.size === 0 || !title.trim()}
            >
              {create.isPending ? t("submitting") : t("submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
