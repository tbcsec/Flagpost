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
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <Button
      type="button"
      variant={active ? "secondary" : "ghost"}
      size="sm"
      onClick={onClick}
      className={cn("h-7 px-2 text-xs", active && "font-semibold")}
    >
      {label}
    </Button>
  );
}
