"use client";

import { useTranslations } from "next-intl";
import {
  useId,
  useMemo,
  useState,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
} from "react";

import { AttachmentsSection } from "@/components/challenges/attachments-section";
import { ChallengeGuessesSection } from "@/components/challenges/challenge-guesses-section";
import { DeploymentSection } from "@/components/challenges/deployment-section";
import { HintsSection } from "@/components/challenges/hints-section";
import { useConfirm } from "@/components/ui/confirm";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState, FlagEmptyIcon } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { Select } from "@/components/ui/select";
import { GUIDE_PDFS } from "@/lib/guides";
import {
  useCategories,
  useCreateCategory,
  useDeleteCategory,
} from "@/lib/hooks/use-categories";
import {
  useChallengeStateMutation,
  useChallenges,
  useCreateChallenge,
  useExportChallenges,
  useImportChallenges,
  useUpdateChallenge,
} from "@/lib/hooks/use-challenges";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { toast } from "@/stores/toast";
import type {
  Category,
  Challenge,
  ChallengeCreate,
  FlagType,
  RichTextDoc,
  ScoringType,
} from "@/lib/types";
import { cn } from "@/lib/utils";

// An ISO/UTC instant → the local "YYYY-MM-DDTHH:mm" a datetime-local input wants.
function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

type Selection = string | "new" | null;

// Admin authoring surface (ROADMAP #8/#9), redesigned as a master-detail view:
// a persistent, searchable challenge list on the left and the editor for the
// selected challenge on the right — replacing the old stacked flow (list *below*
// the competitor grid, editor *below* the list) that grew the page to ~4
// viewports. All server state via the domain hooks; RBAC (view/create/edit/
// publish/delete) is enforced server-side and any 403 surfaces inline. The flag
// is write-only — the form shows *that* one is set, never its value (§13.2).
export function ChallengeAdmin({ competitionId }: { competitionId: string }) {
  const t = useTranslations("challenges.admin");
  const challenges = useChallenges(competitionId);
  const categories = useCategories(competitionId);
  const exportChallenges = useExportChallenges(competitionId);
  const importChallenges = useImportChallenges(competitionId);

  const [selected, setSelected] = useState<Selection>(null);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");

  const list = useMemo(() => challenges.data ?? [], [challenges.data]);

  const categoryName = (id: string | null) =>
    categories.data?.find((c) => c.id === id)?.name ?? t("uncategorized");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return list.filter(
      (c) =>
        (categoryFilter === "all" || c.category_id === categoryFilter) &&
        (q === "" || c.title.toLowerCase().includes(q)),
    );
  }, [list, search, categoryFilter]);

  // A selected id that no longer resolves (deleted, or a refetch dropped it)
  // falls through to null, and the render below shows the select-prompt instead
  // of a ghost editor — so no effect is needed to scrub stale selection state.
  const selectedChallenge =
    typeof selected === "string" && selected !== "new"
      ? (list.find((c) => c.id === selected) ?? null)
      : null;

  function onImportFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    importChallenges.mutate(file, {
      onSuccess: (r) =>
        toast(
          r.skipped
            ? t("importedSkipped", { created: r.created, skipped: r.skipped })
            : t("imported", { created: r.created }),
          {
            variant: "success",
            description: r.errors.length ? r.errors.slice(0, 3).join("; ") : undefined,
          },
        ),
      onError: (err) =>
        toast(t("importFailed"), {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  return (
    <div className="grid gap-6 md:grid-cols-[19rem_minmax(0,1fr)] md:items-start">
      {/* LEFT — the challenge list. Sticky on desktop so it stays put while the
          editor pane scrolls; its own inner scroll keeps a long list bounded. */}
      <Card className="md:sticky md:top-8">
        <CardHeader className="space-y-3 p-4">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <CardTitle className="text-base">{t("listTitle")}</CardTitle>
              <CardDescription>{t("count", { count: list.length })}</CardDescription>
            </div>
            <Button size="sm" onClick={() => setSelected("new")}>
              {t("newChallenge")}
            </Button>
          </div>

          <div className="relative">
            <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("searchPlaceholder")}
              aria-label={t("searchPlaceholder")}
              className="h-9 pl-8"
            />
          </div>

          {(categories.data?.length ?? 0) > 0 && (
            <Select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              aria-label={t("fieldCategory")}
              className="h-9"
            >
              <option value="all">{t("filterAllCategories")}</option>
              {categories.data!.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          )}

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="flex-1"
              onClick={() =>
                exportChallenges.mutate(undefined, {
                  onError: (err) =>
                    toast(t("exportFailed"), {
                      description: (err as Error).message,
                      variant: "destructive",
                    }),
                })
              }
              disabled={exportChallenges.isPending || list.length === 0}
            >
              {t("export")}
            </Button>
            <label className="flex-1">
              <span
                className={cn(
                  "inline-flex h-9 w-full cursor-pointer items-center justify-center rounded-md border border-input px-3 text-sm font-medium hover:bg-accent hover:text-accent-foreground",
                  importChallenges.isPending && "pointer-events-none opacity-60",
                )}
              >
                {importChallenges.isPending ? t("importing") : t("import")}
              </span>
              <input
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                onChange={onImportFile}
                disabled={importChallenges.isPending}
              />
            </label>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          {challenges.isError && (
            <p role="alert" className="px-4 pb-4 text-sm text-destructive">
              {(challenges.error as Error).message}
            </p>
          )}
          {challenges.data && list.length === 0 && (
            <p className="px-4 pb-5 text-sm text-muted-foreground">{t("emptyBody")}</p>
          )}
          {list.length > 0 && (
            <ul className="max-h-[60vh] divide-y divide-border overflow-y-auto border-t border-border">
              {filtered.map((challenge) => (
                <ChallengeListItem
                  key={challenge.id}
                  challenge={challenge}
                  categoryName={categoryName(challenge.category_id)}
                  selected={selected === challenge.id}
                  onSelect={() => setSelected(challenge.id)}
                />
              ))}
              {filtered.length === 0 && (
                <li className="px-4 py-6 text-sm text-muted-foreground">
                  {t("noResults")}
                </li>
              )}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* RIGHT — the editor for the selected challenge, or a prompt when none is. */}
      {selected === "new" || selectedChallenge ? (
        <ChallengeForm
          // Keyed so switching edit targets (or Edit → New) REMOUNTS the form:
          // every field is seeded from props by a useState initializer, which
          // only runs on mount. Without this, React reconciles the same instance
          // and the previous challenge's values persist — then get saved onto the
          // new target (the bug class behind #258/#260/#262).
          key={selected === "new" ? "new" : selectedChallenge!.id}
          competitionId={competitionId}
          challenge={selected === "new" ? null : selectedChallenge}
          categories={categories.data ?? []}
          allChallenges={list}
          onCreated={(created) => setSelected(created.id)}
          onDeleted={() => setSelected(null)}
          onCancel={() => setSelected(null)}
        />
      ) : (
        <EmptyState
          icon={<FlagEmptyIcon />}
          title={list.length === 0 ? t("emptyTitle") : t("selectTitle")}
          description={list.length === 0 ? t("emptyBody") : t("selectBody")}
          action={
            <>
              <Button onClick={() => setSelected("new")}>{t("newChallenge")}</Button>
              {/* First-authoring orientation: the bundled Judge guide. */}
              <Button variant="ghost" asChild>
                <a href={GUIDE_PDFS.judge} target="_blank" rel="noreferrer">
                  {t("readGuide")}
                </a>
              </Button>
            </>
          }
        />
      )}
    </div>
  );
}

function ChallengeListItem({
  challenge,
  categoryName,
  selected,
  onSelect,
}: {
  challenge: Challenge;
  categoryName: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const t = useTranslations("challenges.admin");
  const isPublished = challenge.state === "published";
  const scheduled =
    isPublished &&
    !!challenge.release_at &&
    new Date(challenge.release_at) > new Date();
  const worth =
    challenge.scoring_type === "dynamic"
      ? `${challenge.value} ${t("dyn")}`
      : String(challenge.points);

  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className={cn(
          "flex w-full flex-col gap-0.5 px-4 py-2.5 text-left transition-colors",
          selected ? "bg-primary/10" : "hover:bg-accent/50",
        )}
      >
        <span className="flex items-center gap-2">
          <span
            className={cn(
              "truncate text-sm",
              selected ? "font-semibold text-primary" : "font-medium",
            )}
          >
            {challenge.title}
          </span>
          {!isPublished && <RowTag label={t("stateDraft")} />}
          {scheduled && <RowTag label={t("scheduledShort")} />}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {categoryName} · {worth}
        </span>
      </button>
    </li>
  );
}

function RowTag({ label }: { label: string }) {
  return (
    <span className="shrink-0 rounded-full border border-border px-1.5 py-px text-[10px] uppercase tracking-wide text-muted-foreground">
      {label}
    </span>
  );
}

function ChallengeForm({
  competitionId,
  challenge,
  categories,
  allChallenges,
  onCreated,
  onDeleted,
  onCancel,
}: {
  competitionId: string;
  challenge: Challenge | null;
  categories: Category[];
  allChallenges: Challenge[];
  onCreated: (created: Challenge) => void;
  onDeleted: () => void;
  onCancel: () => void;
}) {
  const t = useTranslations("challenges.admin");
  const isEdit = challenge !== null;
  const isPublished = challenge?.state === "published";
  const { data: activeCompetition } = useActiveCompetition();
  const tagVocab = activeCompetition?.challenge_tags ?? [];
  const tiers = activeCompetition?.difficulty_tiers ?? [];
  const confirm = useConfirm();
  // Own id so the submit button can live in the sticky header, *outside* the
  // <form> — a <form> can't nest the attachments/hints sub-forms, so those and
  // the action buttons must be siblings, wired back by `form={formId}`.
  const formId = useId();
  const create = useCreateChallenge(competitionId);
  const update = useUpdateChallenge(competitionId, challenge?.id ?? "");
  const stateMutation = useChallengeStateMutation(competitionId);
  const mutation = isEdit ? update : create;

  const [title, setTitle] = useState(challenge?.title ?? "");
  const [description, setDescription] = useState<RichTextDoc>(
    challenge?.description ?? {},
  );
  const [categoryId, setCategoryId] = useState(challenge?.category_id ?? "");
  const [points, setPoints] = useState(String(challenge?.points ?? 100));
  const [scoringType, setScoringType] = useState<ScoringType>(
    challenge?.scoring_type ?? "static",
  );
  const [minPoints, setMinPoints] = useState(String(challenge?.min_points ?? 100));
  const [decay, setDecay] = useState(String(challenge?.decay ?? 20));
  // `datetime-local` wants "YYYY-MM-DDTHH:mm" in local time; store "" for none.
  const [releaseAt, setReleaseAt] = useState(
    challenge?.release_at ? toLocalInput(challenge.release_at) : "",
  );
  const [prerequisites, setPrerequisites] = useState<string[]>(
    challenge?.prerequisites ?? [],
  );
  const [tags, setTags] = useState<string[]>(challenge?.tags ?? []);
  const [difficulty, setDifficulty] = useState(challenge?.difficulty ?? "");
  const [connectionInfo, setConnectionInfo] = useState(
    challenge?.connection_info ?? "",
  );
  const [flagType, setFlagType] = useState<FlagType>(
    challenge?.flag_type ?? "static",
  );
  const [caseInsensitive, setCaseInsensitive] = useState(
    challenge?.case_insensitive ?? false,
  );
  const [flag, setFlag] = useState("");
  // Multiple choice: the option list (the correct answer isn't returned by the
  // API, so on edit the correct radio starts unselected — picking one re-sets it).
  const [choices, setChoices] = useState<string[]>(
    challenge?.choices && challenge.choices.length >= 2 ? challenge.choices : ["", ""],
  );
  const [correctIndex, setCorrectIndex] = useState<number | null>(null);

  function updateChoice(i: number, value: string) {
    setChoices((cs) => cs.map((c, idx) => (idx === i ? value : c)));
  }
  function removeChoice(i: number) {
    setChoices((cs) => cs.filter((_, idx) => idx !== i));
    setCorrectIndex((ci) => (ci === null ? null : ci === i ? null : ci > i ? ci - 1 : ci));
  }

  async function onTogglePublish() {
    if (!challenge) return;
    if (
      isPublished &&
      !(await confirm({
        title: t("unpublishConfirmTitle"),
        description: t("unpublishConfirmDescription", { title: challenge.title }),
        confirmLabel: t("unpublishConfirmLabel"),
        destructive: false,
      }))
    ) {
      return;
    }
    stateMutation.mutate({
      challengeId: challenge.id,
      action: isPublished ? "unpublish" : "publish",
    });
  }

  async function onDelete() {
    if (!challenge) return;
    if (
      await confirm({
        title: t("deleteConfirmTitle"),
        description: t("deleteConfirmDescription", { title: challenge.title }),
        confirmLabel: t("deleteConfirmLabel"),
      })
    ) {
      stateMutation.mutate(
        { challengeId: challenge.id, action: "delete" },
        {
          onSuccess: () => {
            toast(t("deletedToast"), { variant: "success" });
            onDeleted();
          },
        },
      );
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const base: ChallengeCreate = {
      title,
      description,
      category_id: categoryId || null,
      points: Number(points),
      scoring_type: scoringType,
      flag_type: flagType,
    };
    if (scoringType === "dynamic") {
      base.min_points = Number(minPoints);
      base.decay = Number(decay);
    }
    // A blank release clears any schedule (null); otherwise send it as ISO/UTC.
    base.release_at = releaseAt ? new Date(releaseAt).toISOString() : null;
    base.prerequisites = prerequisites;
    base.tags = tags;
    base.difficulty = difficulty || null;
    // Blank clears it — this same object is the PATCH body, so "" must become null.
    base.connection_info = connectionInfo.trim() || null;
    if (flagType === "multiple_choice") {
      const trimmed = choices.map((c) => c.trim());
      const hasCorrect = correctIndex !== null && !!trimmed[correctIndex];
      if (hasCorrect) {
        // Setting/replacing the answer: send options + the correct one together.
        base.choices = trimmed;
        base.flag = trimmed[correctIndex as number];
      } else if (!isEdit) {
        // New draft: options only, answer added later before publishing.
        base.choices = trimmed;
      }
      // Editing without re-picking the correct option keeps the stored answer.
    } else {
      base.case_insensitive = caseInsensitive;
      // Only send the flag when the author typed one (empty = keep existing).
      if (flag) base.flag = flag;
    }
    mutation.mutate(base, {
      onSuccess: (saved) => {
        if (isEdit) {
          toast(t("savedToast"), { variant: "success" });
        } else {
          toast(t("createdToast"), { variant: "success" });
          onCreated(saved as Challenge);
        }
      },
    });
  }

  return (
    <Card className="min-w-0">
      {/* Action bar at the top of the editor: identifies the challenge and keeps
          Save/Publish/Delete together above the fields, rather than buried at the
          bottom of a long form. Not sticky — a sub-header pinned inside this
          padded scroll container lets fields peek through its top edge; the list
          pane (a whole sticky card) is what stays put for navigation. */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-t-lg border-b border-border bg-card px-6 py-4">
        <div className="flex min-w-0 items-center gap-2">
          <h2 className="truncate text-lg font-semibold tracking-tight">
            {isEdit ? challenge.title : t("newChallenge")}
          </h2>
          {isEdit && (
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
                isPublished ? "bg-success/15 text-success" : "bg-muted text-muted-foreground",
              )}
            >
              {t(isPublished ? "statePublished" : "stateDraft")}
            </span>
          )}
        </div>
        <div className="flex flex-shrink-0 flex-wrap items-center gap-2">
          {isEdit ? (
            <>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={onDelete}
                disabled={stateMutation.isPending}
              >
                {t("delete")}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={onTogglePublish}
                disabled={stateMutation.isPending || (!isPublished && !challenge.has_flag)}
              >
                {isPublished ? t("unpublish") : t("publish")}
              </Button>
              <Button type="submit" form={formId} size="sm" disabled={mutation.isPending}>
                {mutation.isPending ? t("saving") : t("saveChanges")}
              </Button>
            </>
          ) : (
            <>
              <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
                {t("cancel")}
              </Button>
              <Button type="submit" form={formId} size="sm" disabled={mutation.isPending}>
                {mutation.isPending ? t("saving") : t("createChallenge")}
              </Button>
            </>
          )}
        </div>
      </div>

      <CardContent className="space-y-5 pt-5">
        {mutation.isError && (
          <p role="alert" className="text-sm text-destructive">
            {(mutation.error as Error).message}
          </p>
        )}

        <form id={formId} onSubmit={onSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="title">{t("fieldTitle")}</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label>{t("fieldDescription")}</Label>
            <RichTextEditor value={description} onChange={setDescription} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="category">{t("fieldCategory")}</Label>
              <Select
                id="category"
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
              >
                <option value="">{t("uncategorized")}</option>
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="points">
                {scoringType === "dynamic" ? t("initialPoints") : t("points")}
              </Label>
              <Input
                id="points"
                type="number"
                min={0}
                value={points}
                onChange={(e) => setPoints(e.target.value)}
                required
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="scoring-type">{t("scoring")}</Label>
            <Select
              id="scoring-type"
              value={scoringType}
              onChange={(e) => setScoringType(e.target.value as ScoringType)}
              className="max-w-xs"
            >
              <option value="static">{t("scoringStatic")}</option>
              <option value="dynamic">{t("scoringDynamic")}</option>
            </Select>
            {scoringType === "dynamic" && (
              <div className="grid grid-cols-2 gap-3 pt-1">
                <div className="space-y-2">
                  <Label htmlFor="min-points">{t("minPoints")}</Label>
                  <Input
                    id="min-points"
                    type="number"
                    min={0}
                    value={minPoints}
                    onChange={(e) => setMinPoints(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="decay">{t("decay")}</Label>
                  <Input
                    id="decay"
                    type="number"
                    min={1}
                    value={decay}
                    onChange={(e) => setDecay(e.target.value)}
                    required
                  />
                </div>
                <p className="col-span-2 text-xs text-muted-foreground">
                  {t("dynamicHint", { points: points || 0, min: minPoints || 0, decay: decay || 0 })}
                </p>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="flag-type">{t("flagType")}</Label>
            <Select
              id="flag-type"
              value={flagType}
              onChange={(e) => setFlagType(e.target.value as FlagType)}
              className="max-w-xs"
            >
              <option value="static">{t("flagStatic")}</option>
              <option value="regex">{t("flagRegex")}</option>
              <option value="multiple_choice">{t("flagMultipleChoice")}</option>
            </Select>
          </div>

          {flagType === "multiple_choice" ? (
            <div className="space-y-2">
              <Label>{t("options")}</Label>
              <p className="text-xs text-muted-foreground">
                {isEdit && challenge.has_flag ? t("optionsHintKeep") : t("optionsHint")}
              </p>
              <div className="space-y-2">
                {choices.map((opt, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="mc-correct"
                      checked={correctIndex === i}
                      onChange={() => setCorrectIndex(i)}
                      style={{ accentColor: "hsl(var(--primary))" }}
                      aria-label={t("markCorrect", { n: i + 1 })}
                    />
                    <Input
                      value={opt}
                      onChange={(e) => updateChoice(i, e.target.value)}
                      placeholder={t("optionPlaceholder", { n: i + 1 })}
                    />
                    {choices.length > 2 && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => removeChoice(i)}
                        aria-label={t("removeOption", { n: i + 1 })}
                      >
                        ✕
                      </Button>
                    )}
                  </div>
                ))}
              </div>
              {choices.length < 10 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setChoices([...choices, ""])}
                >
                  {t("addOption")}
                </Button>
              )}
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor="flag">
                  {flagType === "regex" ? t("flagPattern") : t("flag")}
                </Label>
                <Input
                  id="flag"
                  value={flag}
                  placeholder={isEdit && challenge.has_flag ? t("flagUnchanged") : ""}
                  onChange={(e) => setFlag(e.target.value)}
                  required={!isEdit}
                  className="max-w-md"
                />
                {isEdit && (
                  <p className="text-xs text-muted-foreground">
                    {challenge.has_flag ? t("flagSetHint") : t("noFlagHint")}
                  </p>
                )}
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={caseInsensitive}
                  onChange={(e) => setCaseInsensitive(e.target.checked)}
                />
                {t("caseInsensitive")}
              </label>
            </>
          )}

          {/* Secondary fields fold away by default so the essentials aren't buried.
              These are all stored in React state and submitted from onSubmit, so
              collapsing them never drops a value; only *required* inputs must stay
              visible (constraint validation can't focus a hidden field). */}
          <CollapsibleSection title={t("sectionMore")} hint={t("sectionMoreHint")}>
            <div className="space-y-2">
              <Label htmlFor="connection-info">{t("fieldConnectionInfo")}</Label>
              <Input
                id="connection-info"
                className="font-mono"
                value={connectionInfo}
                onChange={(e) => setConnectionInfo(e.target.value)}
                placeholder="nc host 1337"
              />
              <p className="text-xs text-muted-foreground">
                {t("fieldConnectionInfoHint")}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="release-at">{t("releaseAt")}</Label>
              <div className="flex items-center gap-2">
                <Input
                  id="release-at"
                  type="datetime-local"
                  value={releaseAt}
                  onChange={(e) => setReleaseAt(e.target.value)}
                  className="max-w-xs"
                />
                {releaseAt && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setReleaseAt("")}
                  >
                    {t("clear")}
                  </Button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{t("releaseHint")}</p>
            </div>

            <div className="space-y-2">
              <Label>{t("prerequisites")}</Label>
              <p className="text-xs text-muted-foreground">{t("prerequisitesHint")}</p>
              {allChallenges.filter((c) => c.id !== challenge?.id).length === 0 ? (
                <p className="text-xs text-muted-foreground">{t("noOtherChallenges")}</p>
              ) : (
                <div className="grid max-h-40 gap-1 overflow-y-auto rounded-md border border-border p-2">
                  {allChallenges
                    .filter((c) => c.id !== challenge?.id)
                    .map((c) => (
                      <label key={c.id} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-border"
                          style={{ accentColor: "hsl(var(--primary))" }}
                          checked={prerequisites.includes(c.id)}
                          onChange={(e) =>
                            setPrerequisites((prev) =>
                              e.target.checked
                                ? [...prev, c.id]
                                : prev.filter((id) => id !== c.id),
                            )
                          }
                        />
                        <span>{c.title}</span>
                      </label>
                    ))}
                </div>
              )}
            </div>

            {(tiers.length > 0 || tagVocab.length > 0) && (
              <div className="grid gap-4 sm:grid-cols-2">
                {tiers.length > 0 && (
                  <div className="space-y-2">
                    <Label htmlFor="difficulty">{t("difficulty")}</Label>
                    <Select
                      id="difficulty"
                      value={difficulty}
                      onChange={(e) => setDifficulty(e.target.value)}
                    >
                      <option value="">—</option>
                      {tiers.map((tier) => (
                        <option key={tier} value={tier}>
                          {tier}
                        </option>
                      ))}
                    </Select>
                  </div>
                )}
                {tagVocab.length > 0 && (
                  <div className="space-y-2">
                    <Label>{t("tags")}</Label>
                    <div className="flex flex-wrap gap-1.5">
                      {tagVocab.map((tag) => {
                        const on = tags.includes(tag);
                        return (
                          <button
                            key={tag}
                            type="button"
                            onClick={() =>
                              setTags((prev) =>
                                on ? prev.filter((x) => x !== tag) : [...prev, tag],
                              )
                            }
                            className={cn(
                              "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                              on
                                ? "border-primary bg-primary/10 text-primary"
                                : "border-border text-muted-foreground hover:border-primary/40",
                            )}
                          >
                            {tag}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </CollapsibleSection>
        </form>

        {/* Attachments, hints, and guesses have their own sub-forms, so they sit
            *outside* the challenge <form> (no nested forms). They need a persisted
            challenge id, so they're edit-mode only. */}
        {isEdit && (
          <div className="space-y-4 border-t border-border pt-5">
            <AttachmentsSection competitionId={competitionId} challengeId={challenge.id} />
            <HintsSection competitionId={competitionId} challengeId={challenge.id} />
            {challenge.flag_type === "multiple_choice" && (
              <ChallengeGuessesSection
                competitionId={competitionId}
                challengeId={challenge.id}
              />
            )}
            <DeploymentSection
              competitionId={competitionId}
              challengeId={challenge.id}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// A titled disclosure whose children stay mounted while collapsed (via `hidden`,
// not conditional render) so form field state — and its submission — survives a
// collapse. `type="button"` keeps the toggle from submitting the form.
function CollapsibleSection({
  title,
  hint,
  defaultOpen = false,
  children,
}: {
  title: string;
  hint?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-md border border-border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
      >
        <Chevron open={open} />
        <span className="text-sm font-medium">{title}</span>
        {hint && !open && (
          <span className="ml-1 hidden truncate text-xs text-muted-foreground sm:inline">
            {hint}
          </span>
        )}
      </button>
      <div hidden={!open} className="space-y-4 border-t border-border px-4 py-4">
        {children}
      </div>
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn(
        "shrink-0 text-muted-foreground transition-transform",
        open && "rotate-90",
      )}
      aria-hidden="true"
    >
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}

export function CategoryManager({ competitionId }: { competitionId: string }) {
  const t = useTranslations("challenges.admin");
  const categories = useCategories(competitionId);
  const createCategory = useCreateCategory(competitionId);
  const deleteCategory = useDeleteCategory(competitionId);
  const confirm = useConfirm();
  const [name, setName] = useState("");

  async function onDeleteCategory(id: string, catName: string) {
    if (
      await confirm({
        title: t("deleteCategoryConfirmTitle"),
        description: t("deleteCategoryConfirmDescription", { name: catName }),
        confirmLabel: t("deleteCategoryConfirmLabel"),
      })
    ) {
      deleteCategory.mutate(id);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("categories")}</CardTitle>
        <CardDescription>{t("categoriesDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2">
          {categories.data?.map((category) => (
            <span
              key={category.id}
              className="inline-flex items-center gap-1 rounded-full bg-muted px-3 py-1 text-sm"
            >
              {category.name}
              <button
                type="button"
                aria-label={t("deleteCategoryAria", { name: category.name })}
                className="text-muted-foreground hover:text-destructive"
                onClick={() => onDeleteCategory(category.id, category.name)}
              >
                ×
              </button>
            </span>
          ))}
          {categories.data?.length === 0 && (
            <span className="text-sm text-muted-foreground">
              {t("noCategoriesYet")}
            </span>
          )}
        </div>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            createCategory.mutate(
              { name },
              { onSuccess: () => setName("") },
            );
          }}
        >
          <Input
            value={name}
            placeholder={t("newCategory")}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <Button type="submit" disabled={createCategory.isPending}>
            {t("add")}
          </Button>
        </form>
        {createCategory.isError && (
          <p role="alert" className="text-sm text-destructive">
            {(createCategory.error as Error).message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
