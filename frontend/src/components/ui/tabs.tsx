"use client";

import { cn } from "@/lib/utils";

// A minimal, dependency-free tab bar (underline style). Controlled: the caller
// owns the active value and renders the matching panel. Token-styled so it
// inherits the active palette.
export function Tabs({
  tabs,
  value,
  onValueChange,
  className,
}: {
  tabs: { value: string; label: string }[];
  value: string;
  onValueChange: (value: string) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      className={cn("flex gap-1 border-b border-border", className)}
    >
      {tabs.map((tab) => {
        const active = tab.value === value;
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onValueChange(tab.value)}
            className={cn(
              "-mb-px border-b-2 px-3.5 py-2 text-sm font-medium transition-colors",
              active
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
