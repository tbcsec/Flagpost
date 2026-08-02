// A lightning bolt marks the first solver (first blood) — deliberately chosen
// over a blood drop as the friendlier house glyph. Shared so every first-blood
// surface (the challenge solve list, the venue splash, #77) uses the same mark
// and the same amber default. `currentColor` fill + the `text-*` class default
// keep it tokenised (§9); pass `size`/`className` to scale it up on the big
// screen.
export function FirstBloodIcon({
  size = 14,
  className = "text-warning",
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <path d="M13 2 4 13h6l-1 9 10-12h-7l1-8z" />
    </svg>
  );
}
