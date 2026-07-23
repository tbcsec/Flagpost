// A module-level cache of the current user's notification delivery hints
// (§4.4). The `browser`/`sound` preferences are honored client-side at the
// moment a notification arrives — in the per-user WS handler and the ticket
// audio cue, which live in *different* hooks. Keeping the latest resolved
// values here (kept in sync by `useNotificationPreferences`) lets both read a
// single source of truth without prop-drilling or a stale closure. The
// authoritative `inapp_*` gating happens server-side; these are delivery only.

import type { NotificationPreferences } from "@/lib/types";

export const DEFAULT_PREFS: NotificationPreferences = {
  inapp_tickets: true,
  inapp_automations: true,
  browser: false,
  sound: true,
};

let current: NotificationPreferences = { ...DEFAULT_PREFS };

export function setDeliveryPrefs(prefs: NotificationPreferences): void {
  current = prefs;
}

export function getDeliveryPrefs(): NotificationPreferences {
  return current;
}
