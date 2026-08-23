import * as React from "react";

import { cn } from "@/lib/utils";

/** The avatar image URL for a user, or null when they have none. `updatedAt`
 *  (the profile's `avatar_updated_at`) doubles as the cache-buster: the serve
 *  path is immutable-cached, so a changed avatar must be a changed URL. */
export function avatarUrl(userId: string, updatedAt: string | null): string | null {
  if (!updatedAt) return null;
  return `/api/users/${userId}/avatar?v=${Date.parse(updatedAt)}`;
}

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

/** A user's profile picture, falling back to their initials on the same
 *  circle when none is set (the pre-avatar rendering, so nothing shifts). */
export function UserAvatar({
  userId,
  name,
  avatarUpdatedAt,
  size = 32,
  className,
}: {
  userId: string;
  name: string;
  avatarUpdatedAt: string | null;
  size?: number;
  className?: string;
}) {
  const src = avatarUrl(userId, avatarUpdatedAt);
  if (src) {
    return (
      // A dynamic same-origin API image; next/image can't optimise it and the
      // server already normalised the size.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt=""
        width={size}
        height={size}
        className={cn("flex-shrink-0 rounded-full object-cover", className)}
      />
    );
  }
  return (
    <span
      style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }}
      className={cn(
        "flex flex-shrink-0 items-center justify-center rounded-full bg-secondary font-semibold text-secondary-foreground",
        className,
      )}
    >
      {initialsOf(name)}
    </span>
  );
}
