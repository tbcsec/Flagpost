// The backend serializes timestamps as naive UTC (no offset suffix, e.g.
// "2026-07-20T23:44:44"). A browser parses a bare datetime as *local* time, so
// without this it would be off by the viewer's UTC offset. Treat any tz-less
// string as UTC by appending "Z".
export function parseServerDate(iso: string): Date {
  const hasZone = /(?:Z|[+-]\d\d:?\d\d)$/.test(iso);
  return new Date(hasZone ? iso : `${iso}Z`);
}

/** "just now" / "5m ago" / "3h ago" / "2d ago" from a server timestamp. */
export function relativeTime(iso: string): string {
  const diff = Date.now() - parseServerDate(iso).getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}
