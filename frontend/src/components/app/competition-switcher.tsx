"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { switcherGroups } from "@/components/app/nav-visibility";
import { Select } from "@/components/ui/select";
import { pickActiveCompetitionId } from "@/lib/competition-selection";
import { useCompetitions } from "@/lib/hooks/use-competitions";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useAuthStore } from "@/stores/auth";

// The top bar's competition switcher. Always mounted — it also owns the default
// selection — and rendered only where a competition is in play (`visible`).
//
// Someone who isn't in every competition sees theirs apart from the public ones
// they could join, plus a Join link to the lobby for invite codes (#478).
export function CompetitionSwitcher({ visible }: { visible: boolean }) {
  const t = useTranslations("app");
  const activeCompetitionId = useAuthStore((s) => s.activeCompetitionId);
  const setActiveCompetition = useAuthStore((s) => s.setActiveCompetition);
  const { data: allCompetitions } = useCompetitions();
  const access = useAccess();
  // Archived competitions drop out of the switcher (they're closed out) — but
  // keep the current selection visible even if it was just archived.
  const competitions = React.useMemo(
    () =>
      (allCompetitions ?? []).filter(
        (c) => !c.archived_at || c.id === activeCompetitionId,
      ),
    [allCompetitions, activeCompetitionId],
  );
  const groups = switcherGroups(competitions, access);
  const offerJoin = access.ready && !access.seesEveryCompetition;

  // Resolve the active competition once the list loads: keep the current (or
  // localStorage-restored, #316) selection when it's still visible, otherwise
  // fall back to the first. This both seeds the initial default and corrects a
  // stale/foreign restored id (deleted competition, or a different user on this
  // browser) — leaving the switcher pointing at something the user can't load.
  //
  // The fallback prefers a joined competition, so it waits for permissions —
  // picking before they load would land a competitor on a public event they
  // haven't joined (#478). If they fail to load, it falls back as before.
  const settled = access.ready || access.failed;
  React.useEffect(() => {
    if (!settled || competitions.length === 0) return;
    const next = pickActiveCompetitionId(
      activeCompetitionId,
      competitions.map((c) => c.id),
      access.isMemberOf,
    );
    if (next && next !== activeCompetitionId) setActiveCompetition(next);
  }, [settled, access.isMemberOf, activeCompetitionId, competitions, setActiveCompetition]);

  if (!visible) return null;
  const option = (c: { id: string; name: string }) => (
    <option key={c.id} value={c.id}>
      {c.name}
    </option>
  );
  return (
    <>
      {competitions.length > 0 && (
        <Select
          value={activeCompetitionId ?? ""}
          onChange={(e) => setActiveCompetition(e.target.value)}
          aria-label={t("switcher.label")}
          className="h-9 w-44 md:w-60"
        >
          {groups ? (
            <>
              <optgroup label={t("switcher.joined")}>{groups.joined.map(option)}</optgroup>
              <optgroup label={t("switcher.joinable")}>{groups.joinable.map(option)}</optgroup>
            </>
          ) : (
            competitions.map(option)
          )}
        </Select>
      )}
      {offerJoin && (
        <Link
          href="/lobby"
          title={t("switcher.joinAnother")}
          aria-label={t("switcher.joinAnother")}
          className="flex h-9 shrink-0 items-center gap-1.5 rounded-md border border-input px-2.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
          <span className="hidden md:inline">{t("switcher.join")}</span>
        </Link>
      )}
    </>
  );
}
