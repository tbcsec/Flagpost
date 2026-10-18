import type { AppNotification } from "@/lib/types";

/** The in-app path a notification may be followed to, or null.
 *
 *  Only ever an internal, same-origin path — never an absolute/scheme URL.
 *  Notification links are server-built today, but this defends against a
 *  future producer letting a "javascript:"/"//evil.com" value reach an anchor. */
export function safeNotificationLink(link: string | null | undefined): string | null {
  return link && link.startsWith("/") && !link.startsWith("//") ? link : null;
}

/** The competition to switch to before following a notification's link, or
 *  null when none is needed: a notification about another competition's
 *  ticket would otherwise open the Support page on the wrong one (#508). */
export function competitionToSwitchTo(
  n: Pick<AppNotification, "competition_id">,
  activeCompetitionId: string | null,
): string | null {
  return n.competition_id && n.competition_id !== activeCompetitionId ? n.competition_id : null;
}
