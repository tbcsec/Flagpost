"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  SEVERITY_ORDER,
  severityStyle,
} from "@/lib/announcement-severity";
import { useCreateAnnouncement } from "@/lib/hooks/use-announcements";
import { useCompetition } from "@/lib/hooks/use-competitions";
import { useParticipants } from "@/lib/hooks/use-participants";
import { useTeams } from "@/lib/hooks/use-teams";
import type { AnnouncementAudience, AnnouncementSeverity } from "@/lib/types";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast";

// Feature component (§14). Posts through the domain hook; RBAC
// (announcement_create) is server-enforced — a non-organiser's POST 403s,
// surfaced inline. Whole-competition announcements are pushed live over the
// announcements room; targeted ones reach only their recipients (#40).

const SEVERITY_HELP: Record<AnnouncementSeverity, string> = {
  info: "Routine news. Sits in the banner briefly, then tucks into the bell.",
  warning: "Needs attention — stands out in the banner.",
  critical:
    "Stays on screen until dismissed and reaches everyone, even competitors who muted announcement notifications.",
};

export function NewAnnouncementDialog({ competitionId }: { competitionId: string }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [severity, setSeverity] = useState<AnnouncementSeverity>("info");
  const [audience, setAudience] = useState<AnnouncementAudience>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const create = useCreateAnnouncement(competitionId);

  const { data: competition } = useCompetition(competitionId);
  const isTeamMode = competition?.participation_mode !== "individual";
  // Only fetch the roster that the chosen audience actually needs.
  const teams = useTeams(competitionId);
  const participants = useParticipants(competitionId, !isTeamMode);

  const options = isTeamMode
    ? (teams.data ?? []).map((t) => ({ id: t.id, name: t.name }))
    : (participants.data ?? []).map((p) => ({ id: p.user_id, name: p.display_name }));

  function reset() {
    setTitle("");
    setBody("");
    setSeverity("info");
    setAudience("all");
    setSelected(new Set());
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const needsRecipients = audience !== "all";
  const canSubmit =
    title.trim() && body.trim() && (!needsRecipients || selected.size > 0);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    create.mutate(
      {
        title,
        body,
        severity,
        audience_type: audience,
        audience_ids: audience === "all" ? [] : [...selected],
      },
      {
        onSuccess: () => {
          reset();
          setOpen(false);
          toast("Announcement posted", { variant: "success" });
        },
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) create.reset();
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline">New announcement</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New announcement</DialogTitle>
          <DialogDescription>
            {audience === "all"
              ? "Posts to everyone in this competition, live."
              : `Reaches only the ${selected.size} selected ${
                  isTeamMode ? "team(s)" : "competitor(s)"
                }.`}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="announcement-title">Title</Label>
            <Input
              id="announcement-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="announcement-body">Message</Label>
            <textarea
              id="announcement-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              required
              rows={4}
              className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="announcement-severity">Urgency</Label>
            <Select
              id="announcement-severity"
              value={severity}
              onChange={(e) => setSeverity(e.target.value as AnnouncementSeverity)}
            >
              {SEVERITY_ORDER.map((s) => (
                <option key={s} value={s}>
                  {severityStyle(s).label}
                </option>
              ))}
            </Select>
            <p
              className={cn(
                "text-xs",
                severity === "critical"
                  ? severityStyle(severity).accent
                  : "text-muted-foreground",
              )}
            >
              {SEVERITY_HELP[severity]}
            </p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="announcement-audience">Send to</Label>
            <Select
              id="announcement-audience"
              value={audience}
              onChange={(e) => {
                setAudience(e.target.value as AnnouncementAudience);
                setSelected(new Set());
              }}
            >
              <option value="all">Everyone in the competition</option>
              {/* Team targeting only exists in team mode. */}
              {isTeamMode ? (
                <option value="teams">Specific teams</option>
              ) : (
                <option value="users">Specific competitors</option>
              )}
            </Select>
          </div>

          {needsRecipients && (
            <div className="grid gap-2">
              <div className="flex items-center justify-between">
                <Label>{isTeamMode ? "Teams" : "Competitors"}</Label>
                <span className="text-xs text-muted-foreground">
                  {selected.size} selected
                </span>
              </div>
              <div className="max-h-44 overflow-y-auto rounded-md border border-border">
                {options.length === 0 ? (
                  <p className="px-3 py-4 text-sm text-muted-foreground">
                    {isTeamMode ? "No teams yet." : "No competitors yet."}
                  </p>
                ) : (
                  options.map((o) => (
                    <label
                      key={o.id}
                      className="flex cursor-pointer items-center gap-2 border-b border-border px-3 py-2 text-sm last:border-b-0 hover:bg-muted/50"
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(o.id)}
                        onChange={() => toggle(o.id)}
                      />
                      <span className="min-w-0 truncate">{o.name}</span>
                    </label>
                  ))
                )}
              </div>
            </div>
          )}

          {create.isError && (
            <p role="alert" className="text-sm text-destructive">
              {(create.error as Error).message}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={create.isPending || !canSubmit}>
              {create.isPending ? "Posting…" : "Post announcement"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
