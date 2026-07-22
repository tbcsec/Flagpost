"use client";

// Live "who's here" indicator for the §4.1 presence layer. Purely presentational
// — it renders whatever set the usePresence hook hands it, so the same component
// serves the challenge detail and the ticket thread.

import type { PresenceMember } from "@/lib/hooks/use-presence";
import { cn } from "@/lib/utils";

function initials(name: string): string {
  const n = name.trim();
  if (!n) return "?";
  const parts = n.split(/\s+/);
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

/** Stacked avatar chips for the given members, capped with a "+N" overflow. */
export function PresenceIndicator({
  members,
  label,
  max = 4,
  className,
}: {
  members: PresenceMember[];
  /** Optional trailing text, e.g. "3 viewing". */
  label?: string;
  max?: number;
  className?: string;
}) {
  if (members.length === 0) return null;
  const shown = members.slice(0, max);
  const overflow = members.length - shown.length;

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="flex -space-x-1.5">
        {shown.map((m) => (
          <span
            key={m.id}
            title={m.role === "staff" ? `${m.name} (staff)` : m.name}
            className={cn(
              "flex h-6 w-6 items-center justify-center rounded-full border-2 border-card text-[10px] font-semibold",
              m.role === "staff"
                ? "bg-primary text-primary-foreground"
                : "bg-secondary text-secondary-foreground",
            )}
          >
            {initials(m.name)}
          </span>
        ))}
        {overflow > 0 && (
          <span className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-card bg-muted text-[10px] font-semibold text-muted-foreground">
            +{overflow}
          </span>
        )}
      </div>
      {label && <span className="text-xs text-muted-foreground">{label}</span>}
    </div>
  );
}
