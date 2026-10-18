"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

// An on/off switch (role="switch"), styled from design tokens (§9). A plain
// button rather than a checkbox: it acts at once, like the module toggles it
// was made for (#502), with no form to submit.
export function Switch({
  checked,
  onCheckedChange,
  disabled,
  className,
  ...props
}: Omit<React.ComponentProps<"button">, "onChange"> & {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50",
        // Off is an outlined track with a solid thumb, so the state reads at a
        // glance against any card (the switch is the only signal of it).
        checked ? "border-primary bg-primary" : "border-muted-foreground/70 bg-transparent",
        className,
      )}
      {...props}
    >
      <span
        aria-hidden="true"
        className={cn(
          "pointer-events-none block h-3.5 w-3.5 rounded-full shadow transition-transform",
          checked ? "translate-x-4 bg-primary-foreground" : "translate-x-0.5 bg-muted-foreground",
        )}
      />
    </button>
  );
}
