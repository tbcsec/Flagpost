"use client";

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
  useUpdateChallenge,
} from "@/lib/hooks/use-challenges";
import type {
  Category,
  Challenge,
  ChallengeCreate,
  FlagType,
  RichTextDoc,
  ScoringType,
} from "@/lib/types";

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
  const challenges = useChallenges(competitionId);
  const categories = useCategories(competitionId);
  const [editing, setEditing] = useState<Challenge | "new" | null>(null);

  const categoryName = (id: string | null) =>
    categories.data?.find((c) => c.id === id)?.name ?? "—";

  return (
    <div className="space-y-6">
      <CategoryManager competitionId={competitionId} />

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Challenges</CardTitle>
            <CardDescription>
              {challenges.data?.length ?? 0} challenge(s)
            </CardDescription>
          </div>
          <Button onClick={() => setEditing("new")}>New challenge</Button>
        </CardHeader>
        <CardContent>
          {challenges.isError && (
            <p className="text-sm text-destructive">
              {(challenges.error as Error).message}
            </p>
          )}
          {challenges.data && challenges.data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Points</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
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
          competitionId={competitionId}
          challenge={editing === "new" ? null : editing}
          categories={categories.data ?? []}
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
  const stateMutation = useChallengeStateMutation(competitionId);
  const confirm = useConfirm();
  const isPublished = challenge.state === "published";

  async function onTogglePublish() {
    if (
      isPublished &&
      !(await confirm({
        title: "Unpublish challenge?",
        description: `"${challenge.title}" will be hidden from competitors until you publish it again.`,
        confirmLabel: "Unpublish",
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
        title: "Delete challenge?",
        description: `"${challenge.title}" and its attachments, hints, and solve history will be permanently removed. This can't be undone.`,
        confirmLabel: "Delete",
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
          <span title={`Dynamic: ${challenge.points}→${challenge.min_points} over ~${challenge.decay} solves`}>
            {challenge.value}{" "}
            <span className="text-xs text-muted-foreground">dyn</span>
          </span>
        ) : (
          challenge.points
        )}
      </TableCell>
      <TableCell className="capitalize">
        {challenge.state}
        {challenge.state === "published" &&
          challenge.release_at &&
          new Date(challenge.release_at) > new Date() && (
            <span
              className="ml-1.5 text-xs normal-case text-muted-foreground"
              title={`Releases ${new Date(challenge.release_at).toLocaleString()}`}
            >
              · scheduled
            </span>
          )}
      </TableCell>
      <TableCell className="space-x-2 text-right">
        <Button variant="ghost" size="sm" onClick={onEdit}>
          Edit
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={stateMutation.isPending || (!isPublished && !challenge.has_flag)}
          onClick={onTogglePublish}
        >
          {isPublished ? "Unpublish" : "Publish"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive"
          disabled={stateMutation.isPending}
          onClick={onDelete}
        >
          Delete
        </Button>
      </TableCell>
    </TableRow>
  );
}

function ChallengeForm({
  competitionId,
  challenge,
  categories,
  onDone,
}: {
  competitionId: string;
  challenge: Challenge | null;
  categories: Category[];
  onDone: () => void;
}) {
  const isEdit = challenge !== null;
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
        <CardTitle>{isEdit ? "Edit challenge" : "New challenge"}</CardTitle>
        {isEdit && (
          <CardDescription>
            {challenge.has_flag
              ? "A flag is set. Leave the flag field blank to keep it."
              : "No flag set yet — add one before publishing."}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <form id={formId} onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="title">Title</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label>Description</Label>
            <RichTextEditor value={description} onChange={setDescription} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="category">Category</Label>
              <Select
                id="category"
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
              >
                <option value="">Uncategorized</option>
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="points">
                {scoringType === "dynamic" ? "Initial points" : "Points"}
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
            <Label htmlFor="scoring-type">Scoring</Label>
            <Select
              id="scoring-type"
              value={scoringType}
              onChange={(e) => setScoringType(e.target.value as ScoringType)}
              className="max-w-xs"
            >
              <option value="static">Static (fixed points)</option>
              <option value="dynamic">Dynamic (decays as more solve)</option>
            </Select>
            {scoringType === "dynamic" && (
              <div className="grid grid-cols-2 gap-3 pt-1">
                <div className="space-y-2">
                  <Label htmlFor="min-points">Minimum points</Label>
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
                  <Label htmlFor="decay">Decay (solves)</Label>
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
                  Worth {points || 0} until solves accumulate, decaying toward{" "}
                  {minPoints || 0} over ~{decay || 0} solves. Every solver always
                  holds the current value.
                </p>
              </div>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="release-at">Release at</Label>
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
                  Clear
                </Button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              Optional. A published challenge stays hidden from competitors until
              this time — leave blank to release as soon as it&apos;s published.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="flag-type">Flag type</Label>
            <Select
              id="flag-type"
              value={flagType}
              onChange={(e) => setFlagType(e.target.value as FlagType)}
              className="max-w-xs"
            >
              <option value="static">Static</option>
              <option value="regex">Regex</option>
              <option value="multiple_choice">Multiple choice</option>
            </Select>
          </div>

          {flagType === "multiple_choice" ? (
            <div className="space-y-2">
              <Label>Options</Label>
              <p className="text-xs text-muted-foreground">
                Add the options a competitor picks from, and mark the correct one.
                {isEdit && challenge.has_flag
                  ? " Leave unselected to keep the current answer."
                  : ""}
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
                      aria-label={`Mark option ${i + 1} correct`}
                    />
                    <Input
                      value={opt}
                      onChange={(e) => updateChoice(i, e.target.value)}
                      placeholder={`Option ${i + 1}`}
                    />
                    {choices.length > 2 && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => removeChoice(i)}
                        aria-label={`Remove option ${i + 1}`}
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
                  + Add option
                </Button>
              )}
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor="flag">
                  {flagType === "regex" ? "Flag pattern" : "Flag"}
                </Label>
                <Input
                  id="flag"
                  value={flag}
                  placeholder={isEdit && challenge.has_flag ? "(unchanged)" : ""}
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
                Case-insensitive flag
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
          <p className="text-sm text-destructive">
            {(mutation.error as Error).message}
          </p>
        )}
        {/* `form={formId}` submits the challenge form even though this button is
            outside it, so the layout (fields → sub-sections → actions) holds. */}
        <div className="flex gap-2">
          <Button type="submit" form={formId} disabled={mutation.isPending}>
            {mutation.isPending
              ? "Saving…"
              : isEdit
                ? "Save changes"
                : "Create challenge"}
          </Button>
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function CategoryManager({ competitionId }: { competitionId: string }) {
  const categories = useCategories(competitionId);
  const createCategory = useCreateCategory(competitionId);
  const deleteCategory = useDeleteCategory(competitionId);
  const confirm = useConfirm();
  const [name, setName] = useState("");

  async function onDeleteCategory(id: string, catName: string) {
    if (
      await confirm({
        title: "Delete category?",
        description: `"${catName}" will be removed. Its challenges aren't deleted — they become uncategorised.`,
        confirmLabel: "Delete",
      })
    ) {
      deleteCategory.mutate(id);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Categories</CardTitle>
        <CardDescription>Group challenges by topic.</CardDescription>
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
                aria-label={`Delete ${category.name}`}
                className="text-muted-foreground hover:text-destructive"
                onClick={() => onDeleteCategory(category.id, category.name)}
              >
                ×
              </button>
            </span>
          ))}
          {categories.data?.length === 0 && (
            <span className="text-sm text-muted-foreground">
              No categories yet.
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
            placeholder="New category"
            onChange={(e) => setName(e.target.value)}
            required
          />
          <Button type="submit" disabled={createCategory.isPending}>
            Add
          </Button>
        </form>
        {createCategory.isError && (
          <p className="text-sm text-destructive">
            {(createCategory.error as Error).message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
