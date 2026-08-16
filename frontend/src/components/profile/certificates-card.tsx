"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { parseServerDate } from "@/lib/datetime";
import {
  useDownloadMyCertificate,
  useMyCertificates,
} from "@/lib/hooks/use-certificates";
import type { MyCertificate } from "@/lib/types";

function CertificateRow({ cert }: { cert: MyCertificate }) {
  const t = useTranslations("profile.certificates");
  const download = useDownloadMyCertificate(cert.competition_id);
  return (
    <div className="flex items-center justify-between rounded-md border border-border p-3">
      <div>
        <p className="text-sm font-medium">{cert.competition_name}</p>
        <p className="text-xs text-muted-foreground">
          {t("released", { date: parseServerDate(cert.released_at).toLocaleDateString() })}
        </p>
      </div>
      <Button
        size="sm"
        disabled={download.isPending}
        onClick={() => download.mutate(`certificate-${cert.competition_name}.png`)}
      >
        {download.isPending ? t("preparing") : t("download")}
      </Button>
    </div>
  );
}

/** The durable, cross-competition home for a participant's certificates (#219) —
 *  survives closing the release modal and archiving the competition. */
export function MyCertificatesCard() {
  const t = useTranslations("profile.certificates");
  const { data, isLoading } = useMyCertificates();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : !data?.length ? (
          <p className="text-sm text-muted-foreground">{t("empty")}</p>
        ) : (
          <div className="grid gap-2">
            {data.map((c) => (
              <CertificateRow key={c.competition_id} cert={c} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
