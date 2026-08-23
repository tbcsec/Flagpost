"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EntityCombobox } from "@/components/ui/entity-combobox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { parseServerDate } from "@/lib/datetime";
import { useChallenges } from "@/lib/hooks/use-challenges";
import { useParticipants } from "@/lib/hooks/use-participants";
import {
  useExportSubmissions,
  useSubmissionBrowser,
} from "@/lib/hooks/use-submissions";
import { useTeams } from "@/lib/hooks/use-teams";
import type { SubmissionCorrectness, SubmissionQuery } from "@/lib/types";

const PAGE_SIZE = 25;

const EMPTY_DRAFT = {
  q: "",
  challenge_id: "",
  team_id: "",
  user_id: "",
  correctness: "" as SubmissionCorrectness | "",
  since: "",
  until: "",
};

// datetime-local (local time) → ISO UTC for the API; "" stays undefined.
const toIso = (local: string) => (local ? new Date(local).toISOString() : undefined);
const clean = (v: string) => (v ? v : undefined);

const CORRECTNESS_BADGE: Record<SubmissionCorrectness, "success" | "destructive" | "warning"> = {
  correct: "success",
  incorrect: "destructive",
  duplicate: "warning",
};

/** Staff submissions browser (ROADMAP #76): a filterable, paginated table of
 *  raw flag-submission attempts (correct/incorrect/duplicate) with the exact
 *  payload and timestamp, so a judge can resolve a dispute without
 *  triangulating between the audit log and aggregate analytics. Mirrors the
 *  admin audit-log page's filter UI + manual pagination (§3.3 precedent). */
export function SubmissionsBrowser({
  competitionId,
  mode,
}: {
  competitionId: string;
  mode: string;
}) {
  const t = useTranslations("analytics.submissions");
  const [draft, setDraft] = React.useState({ ...EMPTY_DRAFT });
  const [applied, setApplied] = React.useState<SubmissionQuery>({
    limit: PAGE_SIZE,
    offset: 0,
  });

  const challenges = useChallenges(competitionId);
  const teams = useTeams(mode === "team" ? competitionId : "");
  const participants = useParticipants(competitionId);
  const submissions = useSubmissionBrowser(competitionId, applied);
  const exportCsv = useExportSubmissions(competitionId);

  const challengeTitle = (id: string) =>
    challenges.data?.find((c) => c.id === id)?.title ?? id;
  const teamOptions = (teams.data ?? []).map((t) => ({ value: t.id, label: t.name }));
  const userOptions = (participants.data ?? []).map((p) => ({
    value: p.user_id,
    label: p.display_name,
  }));
  const subjectName = (id: string) =>
    participants.data?.find((p) => p.user_id === id)?.display_name ?? id;
  const teamName = (id: string) => teams.data?.find((t) => t.id === id)?.name ?? id;

  function set<K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  function applyFilters(e: React.FormEvent) {
    e.preventDefault();
    setApplied({
      q: clean(draft.q),
      challenge_id: clean(draft.challenge_id),
      team_id: clean(draft.team_id),
      user_id: clean(draft.user_id),
      correctness: draft.correctness || undefined,
      since: toIso(draft.since),
      until: toIso(draft.until),
      limit: PAGE_SIZE,
      offset: 0,
    });
  }

  function reset() {
    setDraft({ ...EMPTY_DRAFT });
    setApplied({ limit: PAGE_SIZE, offset: 0 });
  }

  const total = submissions.data?.total ?? 0;
  const offset = applied.offset ?? 0;
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + PAGE_SIZE, total);

  function page(delta: number) {
    setApplied((a) => ({
      ...a,
      offset: Math.max(0, (a.offset ?? 0) + delta * PAGE_SIZE),
    }));
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardContent className="pt-5">
          <form onSubmit={applyFilters} className="grid gap-3">
            <Input
              placeholder={t("searchPayload")}
              value={draft.q}
              onChange={(e) => set("q", e.target.value)}
            />
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
              <div className="grid gap-1.5">
                <Label htmlFor="f-challenge">{t("challenge")}</Label>
                <Select
                  id="f-challenge"
                  value={draft.challenge_id}
                  onChange={(e) => set("challenge_id", e.target.value)}
                >
                  <option value="">{t("allChallenges")}</option>
                  {challenges.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.title}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="f-correctness">{t("correctness")}</Label>
                <Select
                  id="f-correctness"
                  value={draft.correctness}
                  onChange={(e) =>
                    set("correctness", e.target.value as SubmissionCorrectness | "")
                  }
                >
                  <option value="">{t("all")}</option>
                  <option value="correct">{t("correct")}</option>
                  <option value="incorrect">{t("incorrect")}</option>
                  <option value="duplicate">{t("duplicate")}</option>
                </Select>
              </div>
              {mode === "team" && (
                <div className="grid gap-1.5">
                  <Label htmlFor="f-team">{t("team")}</Label>
                  <EntityCombobox
                    id="f-team"
                    options={teamOptions}
                    value={draft.team_id}
                    onChange={(v) => set("team_id", v)}
                    placeholder={t("anyTeam")}
                    emptyText={t("noTeams")}
                  />
                </div>
              )}
              <div className="grid gap-1.5">
                <Label htmlFor="f-user">{mode === "team" ? t("submittedBy") : t("competitor")}</Label>
                <EntityCombobox
                  id="f-user"
                  options={userOptions}
                  value={draft.user_id}
                  onChange={(v) => set("user_id", v)}
                  placeholder={t("anyUser")}
                  emptyText={t("noParticipants")}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="f-since">{t("from")}</Label>
                <Input
                  id="f-since"
                  type="datetime-local"
                  value={draft.since}
                  onChange={(e) => set("since", e.target.value)}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="f-until">{t("to")}</Label>
                <Input
                  id="f-until"
                  type="datetime-local"
                  value={draft.until}
                  onChange={(e) => set("until", e.target.value)}
                />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button type="submit">{t("apply")}</Button>
              <Button type="button" variant="ghost" onClick={reset}>
                {t("reset")}
              </Button>
              <Button
                type="button"
                variant="outline"
                className="ml-auto"
                disabled={exportCsv.isPending}
                onClick={() => exportCsv.mutate(applied)}
              >
                {exportCsv.isPending ? t("exporting") : t("exportCsv")}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          {submissions.isLoading
            ? t("loading")
            : t("range", { from: showingFrom, to: showingTo, total })}
        </span>
        <span className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => page(-1)} disabled={offset === 0}>
            {t("previous")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => page(1)}
            disabled={showingTo >= total}
          >
            {t("next")}
          </Button>
        </span>
      </div>

      {submissions.isError && (
        <p role="alert" className="text-sm text-destructive">
          {(submissions.error as Error).message}
        </p>
      )}

      <Card>
        <CardContent className="pt-2">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("colTime")}</TableHead>
                <TableHead>{t("challenge")}</TableHead>
                {mode === "team" && <TableHead>{t("team")}</TableHead>}
                <TableHead>{t("submittedBy")}</TableHead>
                <TableHead>{t("colPayload")}</TableHead>
                <TableHead>{t("colResult")}</TableHead>
                <TableHead className="text-right">{t("colPoints")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {submissions.data?.items.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                    {parseServerDate(row.created_at).toISOString().slice(0, 19).replace("T", " ")}
                  </TableCell>
                  <TableCell>{challengeTitle(row.challenge_id)}</TableCell>
                  {mode === "team" && (
                    <TableCell className="text-muted-foreground">
                      {row.team_id ? teamName(row.team_id) : "—"}
                    </TableCell>
                  )}
                  <TableCell className="text-muted-foreground">
                    {subjectName(row.user_id)}
                  </TableCell>
                  <TableCell className="max-w-xs">
                    <span className="line-clamp-1 break-all font-mono text-xs">
                      {row.value}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge variant={CORRECTNESS_BADGE[row.correctness]}>
                      {row.correctness}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono">{row.points_awarded}</TableCell>
                </TableRow>
              ))}
              {submissions.data && submissions.data.items.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={mode === "team" ? 7 : 6}
                    className="py-8 text-center text-sm text-muted-foreground"
                  >
                    {t("empty")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
