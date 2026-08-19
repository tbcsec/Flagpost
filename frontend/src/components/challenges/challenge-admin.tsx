"use client";

import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import { AttachmentsSection } from "@/components/challenges/attachments-section";
import { ChallengeGuessesSection } from "@/components/challenges/challenge-guesses-section";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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

// Admin authoring surface (ROADMAP #8/#9). All server state via the domain
// hooks; RBAC (view/create/edit/publish/delete) is enforced server-side and
// any 403 surfaces inline. The flag is write-only — the form shows *that* one
// is set, never its value (§13.2).
export function ChallengeAdmin({ competitionId }: { competitionId: string }) {
  const t = useTranslations("challenges.admin");
  const challenges = useChallenges(competitionId);
  const categories = useCategories(competitionId);
  const [editing, setEditing] = useState<Challenge | "new" | null>(null);
  const exportChallenges = useExportChallenges(competitionId);
  const importChallenges = useImportChallenges(competitionId);

  const categoryName = (id: string | null) =>
    categories.data?.find((c) => c.id === id)?.name ?? "—";

  function onImportFile(e: React.ChangeEvent<HTMLInputElement>) {
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
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>{t("listTitle")}</CardTitle>
            <CardDescription>
              {t("count", { count: challenges.data?.length ?? 0 })}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                exportChallenges.mutate(undefined, {
                  onError: (err) =>
                    toast(t("exportFailed"), {
                      description: (err as Error).message,
                      variant: "destructive",
                    }),
                })
              }
              disabled={exportChallenges.isPending || !challenges.data?.length}
            >
              {t("export")}
            </Button>
            <label>
              <span
                className={cn(
                  "inline-flex h-9 cursor-pointer items-center rounded-md border border-border px-3 text-sm font-medium hover:bg-accent/60",
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
            <Button onClick={() => setEditing("new")}>{t("newChallenge")}</Button>
          </div>
        </CardHeader>
        <CardContent>
          {challenges.isError && (
            <p role="alert" className="text-sm text-destructive">
              {(challenges.error as Error).message}
            </p>
          )}
          {challenges.data && challenges.data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("colTitle")}</TableHead>
                  <TableHead>{t("colCategory")}</TableHead>
                  <TableHead>{t("colPoints")}</TableHead>
                  <TableHead>{t("colState")}</TableHead>
                  <TableHead className="text-right">{t("colActions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {challenges.data.map((challenge) => (
                  <ChallengeRow
                    key={challenge.id}
                    competitionId={competitionId}
                    challenge={challenge}
                    categoryName={categoryName(challenge.category_id)}
                    onEdit={() => setEditing(challenge)}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {editing && (
        <ChallengeForm
          // Keyed so switching edit targets (or Edit → New) REMOUNTS the form:
          // every field is seeded from props by a useState initializer, which
          // only runs on mount. Without this the table + New button stay mounted,
          // React reconciles the same instance, and the previous challenge's
          // values persist — then get saved onto the new target (same bug class
          // as #258/#260 on the settings page).
          key={editing === "new" ? "new" : editing.id}
          competitionId={competitionId}
          challenge={editing === "new" ? null : editing}
          categories={categories.data ?? []}
          allChallenges={challenges.data ?? []}
          onDone={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function ChallengeRow({
  competitionId,
  challenge,
  categoryName,
  onEdit,
}: {
  competitionId: string;
  challenge: Challenge;
  categoryName: string;
  onEdit: () => void;
}) {
  const t = useTranslations("challenges.admin");
  const stateMutation = useChallengeStateMutation(competitionId);
  const confirm = useConfirm();
  const isPublished = challenge.state === "published";

  async function onTogglePublish() {
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
    if (
      await confirm({
        title: t("deleteConfirmTitle"),
        description: t("deleteConfirmDescription", { title: challenge.title }),
        confirmLabel: t("deleteConfirmLabel"),
      })
    ) {
      stateMutation.mutate({ challengeId: challenge.id, action: "delete" });
    }
  }

  return (
    <TableRow>
      <TableCell className="font-medium">{challenge.title}</TableCell>
      <TableCell className="text-muted-foreground">{categoryName}</TableCell>
      <TableCell>
        {challenge.scoring_type === "dynamic" ? (
          <span title={t("dynamicTooltip", { points: challenge.points, min: challenge.min_points ?? 0, decay: challenge.decay ?? 0 })}>
            {challenge.value}{" "}
            <span className="text-xs text-muted-foreground">{t("dyn")}</span>
          </span>
        ) : (
          challenge.points
        )}
      </TableCell>
      <TableCell className="capitalize">
        {t(challenge.state === "published" ? "statePublished" : "stateDraft")}
        {challenge.state === "published" &&
          challenge.release_at &&
          new Date(challenge.release_at) > new Date() && (
            <span
              className="ml-1.5 text-xs normal-case text-muted-foreground"
              title={t("releasesTooltip", { date: new Date(challenge.release_at).toLocaleString() })}
            >
              {t("scheduled")}
            </span>
          )}
      </TableCell>
      <TableCell className="space-x-2 text-right">
        <Button variant="ghost" size="sm" onClick={onEdit}>
          {t("edit")}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={stateMutation.isPending || (!isPublished && !challenge.has_flag)}
          onClick={onTogglePublish}
        >
          {isPublished ? t("unpublish") : t("publish")}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive"
          disabled={stateMutation.isPending}
          onClick={onDelete}
        >
          {t("delete")}
        </Button>
      </TableCell>
    </TableRow>
  );
}

function ChallengeForm({
  competitionId,
  challenge,
  categories,
  allChallenges,
  onDone,
}: {
  competitionId: string;
  challenge: Challenge | null;
  categories: Category[];
  allChallenges: Challenge[];
  onDone: () => void;
}) {
  const t = useTranslations("challenges.admin");
  const isEdit = challenge !== null;
  const { data: activeCompetition } = useActiveCompetition();
  const tagVocab = activeCompetition?.challenge_tags ?? [];
  const tiers = activeCompetition?.difficulty_tiers ?? [];
  // Own id so the submit button can live *outside* the <form> (below the
  // attachments/hints sub-forms) and still submit it — a <form> can't nest
  // another <form>, so those sections must be siblings, not children.
  const formId = useId();
  const create = useCreateChallenge(competitionId);
  const update = useUpdateChallenge(competitionId, challenge?.id ?? "");
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

  function onSubmit(e: React.FormEvent) {
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
    mutation.mutate(base, { onSuccess: onDone });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{isEdit ? t("editTitle") : t("newChallenge")}</CardTitle>
        {isEdit && (
          <CardDescription>
            {challenge.has_flag ? t("flagSetHint") : t("noFlagHint")}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <form id={formId} onSubmit={onSubmit} className="space-y-4">
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
                    {tiers.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </Select>
                </div>
              )}
              {tagVocab.length > 0 && (
                <div className="space-y-2">
                  <Label>{t("tags")}</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {tagVocab.map((t) => {
                      const on = tags.includes(t);
                      return (
                        <button
                          key={t}
                          type="button"
                          onClick={() =>
                            setTags((prev) =>
                              on ? prev.filter((x) => x !== t) : [...prev, t],
                            )
                          }
                          className={cn(
                            "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                            on
                              ? "border-primary bg-primary/10 text-primary"
                              : "border-border text-muted-foreground hover:border-primary/40",
                          )}
                        >
                          {t}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
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
                <Button type="button" variant="ghost" size="sm" onClick={() => setReleaseAt("")}>
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
        </form>

        {/* Attachments and hints have their own sub-forms, so they sit *outside*
            the challenge <form> (no nested forms). They need a persisted
            challenge id, so they're edit-mode only. */}
        {isEdit && (
          <>
            <AttachmentsSection
              competitionId={competitionId}
              challengeId={challenge.id}
            />
            <HintsSection
              competitionId={competitionId}
              challengeId={challenge.id}
            />
            {challenge.flag_type === "multiple_choice" && (
              <ChallengeGuessesSection
                competitionId={competitionId}
                challengeId={challenge.id}
              />
            )}
          </>
        )}

        {mutation.isError && (
          <p role="alert" className="text-sm text-destructive">
            {(mutation.error as Error).message}
          </p>
        )}
        {/* `form={formId}` submits the challenge form even though this button is
            outside it, so the layout (fields → sub-sections → actions) holds. */}
        <div className="flex gap-2">
          <Button type="submit" form={formId} disabled={mutation.isPending}>
            {mutation.isPending
              ? t("saving")
              : isEdit
                ? t("saveChanges")
                : t("createChallenge")}
          </Button>
          <Button type="button" variant="ghost" onClick={onDone}>
            {t("cancel")}
          </Button>
        </div>
      </CardContent>
    </Card>
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
