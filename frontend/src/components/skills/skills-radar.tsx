"use client";

// The skills web: a hand-rolled inline-SVG radar (Flagpost ships no chart lib,
// matching the points timeline + scoreboard bars). Geometry lives in
// lib/skills-radar.ts (pure + unit-tested); this file is presentation only. One
// accent (`--chart-1`) for the whole web — it's one person's shape, not a set of
// series — with the shared border/muted tokens for the grid and labels.

import { useTranslations } from "next-intl";

import { axisColor, buildRadar, type SkillDatum } from "@/lib/skills-radar";

const WEB = axisColor(0); // hsl(var(--chart-1))

export function SkillsRadar({ skills }: { skills: SkillDatum[] }) {
  const t = useTranslations("skills");
  const g = buildRadar(skills);

  return (
    <svg
      viewBox={g.viewBox}
      width="100%"
      className="mx-auto h-auto w-full max-w-[26em]"
      role="img"
      aria-label={t("radarAria", { count: skills.length })}
    >
      {/* concentric grid rings */}
      {g.rings.map((ring, i) => (
        <polygon
          key={i}
          points={ring}
          fill="none"
          stroke="hsl(var(--border))"
          strokeWidth={1}
          opacity={0.6}
        />
      ))}
      {/* spokes */}
      {g.axes.map((a) => (
        <line
          key={`spoke-${a.skill}`}
          x1={g.cx}
          y1={g.cy}
          x2={a.axisX}
          y2={a.axisY}
          stroke="hsl(var(--border))"
          strokeWidth={1}
          opacity={0.6}
        />
      ))}
      {/* the data web */}
      <polygon points={g.polygon} fill={WEB} fillOpacity={0.2} stroke={WEB} strokeWidth={2} />
      {g.axes.map((a) => (
        <circle key={`pt-${a.skill}`} cx={a.pointX} cy={a.pointY} r={3} fill={WEB} />
      ))}
      {/* axis labels */}
      {g.axes.map((a) => (
        <text
          key={`lbl-${a.skill}`}
          x={a.labelX}
          y={a.labelY}
          textAnchor={a.labelAnchor}
          dominantBaseline="middle"
          className="text-[0.7rem] capitalize"
          fill="hsl(var(--muted-foreground))"
        >
          {a.skill}
        </text>
      ))}
    </svg>
  );
}
