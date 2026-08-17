"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  useDownloadMyCertificate,
  useMyCertificateAvailability,
} from "@/lib/hooks/use-certificates";
import { useEnabledModules } from "@/lib/hooks/use-modules";

/** Contextual re-find on the results page (#219): once released, a card offering
 *  the download. Renders nothing until the user has a certificate available. */
export function ScoreboardCertificateCard({ competitionId }: { competitionId: string }) {
  const t = useTranslations("certificates");
  const enabled = useEnabledModules(competitionId, Boolean(competitionId));
  const moduleOn = !enabled.data || enabled.data.includes("certificates");
  const availability = useMyCertificateAvailability(
    competitionId,
    Boolean(competitionId) && moduleOn,
  );
  const download = useDownloadMyCertificate(competitionId);
  const a = availability.data;
  if (!a?.available) return null;
  return (
    <Card className="border-success/40 bg-success/5">
      <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-5">
        <div>
          <p className="text-sm font-medium">{t("card.ready")}</p>
          <p className="text-xs text-muted-foreground">
            {t("card.hint")}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link href="/profile?tab=certificates">{t("viewInProfile")}</Link>
          </Button>
          <Button
            size="sm"
            disabled={download.isPending}
            onClick={() =>
              download.mutate(`certificate-${a.competition_name ?? "flagpost"}.png`)
            }
          >
            {download.isPending ? t("preparing") : t("download")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
