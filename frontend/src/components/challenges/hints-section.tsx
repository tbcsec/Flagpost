"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateHint, useDeleteHint, useHints } from "@/lib/hooks/use-hints";

// Hint authoring inside the challenge editor (Phase 9). Like attachments, this
// needs a persisted challenge id, so it only appears in edit mode. Editors see
// every hint body (the list endpoint returns them revealed for challenge_edit).
export function HintsSection({
  competitionId,
  challengeId,
}: {
  competitionId: string;
  challengeId: string;
}) {
  const hints = useHints(competitionId, challengeId);
  const create = useCreateHint(competitionId, challengeId);
  const remove = useDeleteHint(competitionId, challengeId);
  const [body, setBody] = useState("");
  const [cost, setCost] = useState("0");

  function onAdd(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      { body, cost: Number(cost) || 0 },
      {
        onSuccess: () => {
          setBody("");
          setCost("0");
        },
      },
    );
  }

  return (
    <div className="grid gap-3">
      <Label>Hints</Label>
      {hints.data && hints.data.length > 0 && (
        <ul className="grid gap-2">
          {hints.data.map((hint) => (
            <li
              key={hint.id}
              className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm"
            >
              <span className="min-w-0 flex-1 truncate">{hint.body}</span>
              <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                {hint.cost} pts
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-destructive"
                disabled={remove.isPending}
                onClick={() => remove.mutate(hint.id)}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={onAdd} className="flex items-end gap-2">
        <div className="grid flex-1 gap-1">
          <Input
            value={body}
            placeholder="Hint text"
            onChange={(e) => setBody(e.target.value)}
            required
          />
        </div>
        <div className="grid w-24 gap-1">
          <Input
            type="number"
            min={0}
            value={cost}
            aria-label="Hint cost"
            onChange={(e) => setCost(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={create.isPending}>
          Add hint
        </Button>
      </form>
      {create.isError && (
        <p className="text-sm text-destructive">{(create.error as Error).message}</p>
      )}
    </div>
  );
}
