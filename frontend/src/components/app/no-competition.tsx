"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { EmptyState, TrophyEmptyIcon } from "@/components/ui/empty-state";
import { GUIDE_PDFS } from "@/lib/guides";
import { useAccess } from "@/lib/hooks/use-permissions";

// Shown on competition-scoped surfaces when there's no active competition — a
// fresh install has none until an admin creates one. Role-aware: staff get a
// create CTA, everyone else gets a reassuring "check back" message.
export function NoCompetition() {
  const t = useTranslations("app.noCompetition");
  const access = useAccess();
  const canCreate = access.has("create_competition");
  return (
    <EmptyState
      icon={<TrophyEmptyIcon />}
      title={t("title")}
      description={canCreate ? t("descriptionCanCreate") : t("description")}
      action={
        <>
          {canCreate && (
            <Button asChild>
              <Link href="/admin/competitions">{t("manage")}</Link>
            </Button>
          )}
          {/* The bundled Competitor guide — orientation while there's nothing
              to play yet. */}
          <Button variant="ghost" asChild>
            <a href={GUIDE_PDFS.competitor} target="_blank" rel="noreferrer">
              {t("readGuide")}
            </a>
          </Button>
        </>
      }
    />
  );
}
