"use client";

import { useId, useState } from "react";

import { AttachmentsSection } from "@/components/challenges/attachments-section";
import { HintsSection } from "@/components/challenges/hints-section";
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
  FlagType,
  RichTextDoc,
} from "@/lib/types";

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
  const isPublished = challenge.state === "published";

  return (
    <TableRow>
      <TableCell className="font-medium">{challenge.title}</TableCell>
      <TableCell className="text-muted-foreground">{categoryName}</TableCell>
      <TableCell>{challenge.points}</TableCell>
      <TableCell className="capitalize">{challenge.state}</TableCell>
      <TableCell className="space-x-2 text-right">
        <Button variant="ghost" size="sm" onClick={onEdit}>
          Edit
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={stateMutation.isPending || (!isPublished && !challenge.has_flag)}
          onClick={() =>
            stateMutation.mutate({
              challengeId: challenge.id,
              action: isPublished ? "unpublish" : "publish",
            })
          }
        >
          {isPublished ? "Unpublish" : "Publish"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive"
          disabled={stateMutation.isPending}
          onClick={() =>
            stateMutation.mutate({
              challengeId: challenge.id,
              action: "delete",
            })
          }
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
  const [flagType, setFlagType] = useState<FlagType>(
    challenge?.flag_type ?? "static",
  );
  const [caseInsensitive, setCaseInsensitive] = useState(
    challenge?.case_insensitive ?? false,
  );
  const [flag, setFlag] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const base = {
      title,
      description,
      category_id: categoryId || null,
      points: Number(points),
      flag_type: flagType,
      case_insensitive: caseInsensitive,
      // Only send the flag when the author typed one (empty = keep existing).
      ...(flag ? { flag } : {}),
    };
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
              <Label htmlFor="points">Points</Label>
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
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="flag-type">Flag type</Label>
              <Select
                id="flag-type"
                value={flagType}
                onChange={(e) => setFlagType(e.target.value as FlagType)}
              >
                <option value="static">Static</option>
                <option value="regex">Regex</option>
              </Select>
            </div>
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
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={caseInsensitive}
              onChange={(e) => setCaseInsensitive(e.target.checked)}
            />
            Case-insensitive flag
          </label>
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
  const [name, setName] = useState("");

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
                onClick={() => deleteCategory.mutate(category.id)}
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
