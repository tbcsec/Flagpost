"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Shared toolbar toggle for the rich-text editors (RichTextEditor, CollabNote).
// Module-scope on purpose: a component type declared inside a render is a new
// type every render, so React remounts its subtree each time (react-hooks/
// static-components — and it blocks React Compiler memoization).
export function ToolbarButton({
  active,
  onClick,
  label,
  disabled = false,
  title,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  /** Grey out actions that can't apply to the current selection (e.g.
   *  alignment inside a list) instead of letting them silently no-op. */
  disabled?: boolean;
  title?: string;
}) {
  return (
    <Button
      type="button"
      variant={active ? "secondary" : "ghost"}
      size="sm"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn("h-7 px-2 text-xs", active && "font-semibold")}
    >
      {label}
    </Button>
  );
}
