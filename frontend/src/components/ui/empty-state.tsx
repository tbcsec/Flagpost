import * as React from "react";

import { Card, CardContent } from "@/components/ui/card";

// A guided empty state (ROADMAP #24) — a framed panel with an icon, a title, a
// short next-step description, and an optional action, shown in place of a blank
// region on a brand-new competition. Call sites make it role-aware: staff get a
// "create the first thing" CTA, competitors get reassuring "what happens next"
// copy. Kept token-styled so it inherits the active palette.
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardContent className="flex flex-col items-center gap-3 px-6 py-12 text-center">
        {icon && (
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-muted text-muted-foreground">
            {icon}
          </div>
        )}
        <div className="grid gap-1">
          <h3 className="font-display text-base font-semibold tracking-tight">{title}</h3>
          {description && (
            <p className="mx-auto max-w-md text-sm text-muted-foreground">{description}</p>
          )}
        </div>
        {action && (
          <div className="mt-1 flex flex-wrap items-center justify-center gap-2">{action}</div>
        )}
      </CardContent>
    </Card>
  );
}

// Shared glyphs for the first-run surfaces, matching the app's inline-SVG
// convention (no icon library). Sized for the EmptyState icon bubble.
type IconProps = { className?: string };
const svgProps = {
  width: 22,
  height: 22,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export const FlagEmptyIcon = ({ className }: IconProps) => (
  <svg {...svgProps} className={className} aria-hidden>
    <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
    <line x1="4" y1="22" x2="4" y2="15" />
  </svg>
);

export const TrophyEmptyIcon = ({ className }: IconProps) => (
  <svg {...svgProps} className={className} aria-hidden>
    <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" />
    <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
    <path d="M4 22h16" />
    <path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22" />
    <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22" />
    <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" />
  </svg>
);

export const TicketEmptyIcon = ({ className }: IconProps) => (
  <svg {...svgProps} className={className} aria-hidden>
    <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
  </svg>
);

export const SurveyEmptyIcon = ({ className }: IconProps) => (
  <svg {...svgProps} className={className} aria-hidden>
    <path d="M9 3h6a2 2 0 0 1 2 2v0h1a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h1a2 2 0 0 1 2-2z" />
    <path d="M9 12l2 2 4-4" />
  </svg>
);

export const PeopleEmptyIcon = ({ className }: IconProps) => (
  <svg {...svgProps} className={className} aria-hidden>
    <path d="M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2" />
    <circle cx="10" cy="7" r="4" />
    <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
);
