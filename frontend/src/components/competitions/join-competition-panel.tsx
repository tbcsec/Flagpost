"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { SectionHeader } from "@/components/app/section-header";
import { usePublicJoin } from "@/components/competitions/use-public-join";
import { Button } from "@/components/ui/button";
import { EmptyState, TrophyEmptyIcon } from "@/components/ui/empty-state";
import type { Competition } from "@/lib/types";
import { toast } from "@/stores/toast";

// What a signed-in user sees on a competition they haven't joined (#478). The
// switcher lists public competitions alongside their own, so picking one used
// to land on a page the server refused; it now offers the same self-serve join
// as the lobby. A competition that isn't open to joiners (archived, or not
// public) points to the lobby, where an invite code works.
export function JoinCompetitionPanel({ competition }: { competition: Competition }) {
  const t = useTranslations("app.joinCompetition");
  const tl = useTranslations("lobby");
  const tc = useTranslations("common");
  const publicJoin = usePublicJoin({
    onJoined: (name) => toast(tl("joined", { name }), { variant: "success" }),
  });
  const open = competition.visibility === "public" && !competition.archived_at;

  return (
    <>
      <SectionHeader
        title={competition.name}
        subtitle={`${tc(`competitionMode.${competition.participation_mode}`)} · ${tc(
          `visibility.${competition.visibility}`,
        )}`}
      />
      <EmptyState
        icon={<TrophyEmptyIcon />}
        title={open ? t("title") : t("closedTitle")}
        description={open ? t("description") : t("closedDescription")}
        action={
          <>
            {open && (
              <Button
                disabled={publicJoin.isPending}
                onClick={() => publicJoin.start(competition.id, competition.name)}
              >
                {publicJoin.isPending ? tl("joining") : t("join")}
              </Button>
            )}
            <Button variant={open ? "ghost" : "default"} asChild>
              <Link href="/lobby">{t("lobby")}</Link>
            </Button>
          </>
        }
      />
      {publicJoin.dialogs}
    </>
  );
}
