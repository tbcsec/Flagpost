"use client";

// Presence over the real-time layer (ARCHITECTURE.md §4.1). Not a data domain
// like the §8 hooks — it's WS-level state (no REST, no TanStack cache): join a
// resource room, track the broadcast "who's here" set, and clean up on unmount.

import { useEffect, useState } from "react";

import { openRoomSocket } from "@/lib/ws";
import { useAuthStore } from "@/stores/auth";

export interface PresenceMember {
  id: string;
  name: string;
  role?: string;
  mode?: "view" | "edit";
}

interface PresenceFrame {
  type?: string;
  members?: PresenceMember[];
}

export interface PresenceSummary {
  /** Everyone present, current user included. */
  members: PresenceMember[];
  /** Everyone present except the current user. */
  others: PresenceMember[];
  /** Whether a staff member other than the current user is present. */
  staffPresent: boolean;
}

/** Reduce a raw presence set into what indicators actually render. Pure so it
 *  can be unit-tested without a socket. */
export function summarizePresence(
  members: PresenceMember[],
  selfId: string | undefined,
): PresenceSummary {
  const others = members.filter((m) => m.id !== selfId);
  return {
    members,
    others,
    staffPresent: others.some((m) => m.role === "staff"),
  };
}

/** Track presence in a `<roomType>/<roomId>` room. Returns the live set plus
 *  the self-excluding summary the indicators use. */
export function usePresence(
  roomType: string,
  roomId: string | null,
  options: { mode?: "view" | "edit"; enabled?: boolean } = {},
): PresenceSummary {
  const { mode, enabled = true } = options;
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  const selfId = useAuthStore((s) => s.user?.id);
  const [members, setMembers] = useState<PresenceMember[]>([]);

  useEffect(() => {
    if (!enabled || !isAuthenticated || !roomId) {
      setMembers([]);
      return;
    }
    const socket = openRoomSocket(roomType, roomId, {
      mode,
      onMessage: (data) => {
        const frame = data as PresenceFrame;
        if (frame.type === "presence" && Array.isArray(frame.members)) {
          setMembers(frame.members);
        }
      },
      onStatus: (status) => {
        // A dropped socket means our view of the room is stale; clear it so a
        // reconnect repopulates from the fresh join snapshot.
        if (status !== "open") setMembers([]);
      },
    });
    return () => socket.close();
  }, [roomType, roomId, mode, enabled, isAuthenticated]);

  return summarizePresence(members, selfId);
}
