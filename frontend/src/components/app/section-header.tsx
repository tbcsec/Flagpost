import * as React from "react";

/** Standard page heading — 24px semibold with a muted subtitle (§9 scale). */
export function SectionHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex flex-shrink-0 gap-2">{actions}</div>}
    </div>
  );
}

/** Flags a surface whose UI is built but not yet wired to a backend, so it's
 *  obvious in-app (and in review) that the data is placeholder. */
export function NotWiredNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-warning/40 bg-warning/10 px-4 py-2.5 text-[13px] text-foreground">
      <span className="font-medium text-warning">Preview</span> — {children}
    </div>
  );
}
