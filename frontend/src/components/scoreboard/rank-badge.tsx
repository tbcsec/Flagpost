import { cn } from "@/lib/utils";

/** Rank rendering shared by the standings table and the top-10 chart tooltip
 *  (#52): the top three get a medal-coloured disc, everyone else a plain
 *  monospace number. */
export function RankBadge({ rank }: { rank: number }) {
  if (rank > 3) return <span className="font-mono text-muted-foreground">{rank}</span>;
  const style = {
    1: "bg-warning text-warning-foreground",
    2: "bg-secondary text-secondary-foreground",
    3: "bg-muted text-muted-foreground",
  }[rank as 1 | 2 | 3];
  return (
    <span
      className={cn(
        "inline-flex h-6 w-6 items-center justify-center rounded-full font-mono text-xs font-semibold",
        style,
      )}
    >
      {rank}
    </span>
  );
}
