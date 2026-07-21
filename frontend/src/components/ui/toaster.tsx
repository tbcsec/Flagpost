"use client";

import { useToastStore } from "@/stores/toast";
import { cn } from "@/lib/utils";

// Design-system primitive: references tokens (§9), never raw hex. Rendered once
// near the app root; reads the toast store and stacks toasts bottom-right.
const VARIANT_CLASS = {
  default: "border-border bg-card text-card-foreground",
  success: "border-success/40 bg-card text-card-foreground",
  destructive: "border-destructive/40 bg-card text-card-foreground",
} as const;

const ACCENT_CLASS = {
  default: "bg-primary",
  success: "bg-success",
  destructive: "bg-destructive",
} as const;

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={cn(
            "pointer-events-auto flex items-start gap-3 overflow-hidden rounded-lg border p-4 shadow-lg",
            VARIANT_CLASS[t.variant],
          )}
        >
          <span className={cn("mt-1 h-2 w-2 flex-shrink-0 rounded-full", ACCENT_CLASS[t.variant])} />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium">{t.title}</div>
            {t.description && (
              <div className="mt-0.5 text-[13px] text-muted-foreground">{t.description}</div>
            )}
          </div>
          <button
            onClick={() => dismiss(t.id)}
            className="flex-shrink-0 text-muted-foreground hover:text-foreground"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
