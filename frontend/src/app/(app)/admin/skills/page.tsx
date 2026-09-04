"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { SectionHeader } from "@/components/app/section-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useSkillMatrix } from "@/lib/hooks/use-skills";
import type { SkillMatrix } from "@/lib/types";

// Admin → Skills. The cross-competition users×skills matrix (#364, ADR-0039) —
// the second §6.3 sanctioned consolidation read, gated on view_global_analytics
// and paginated over users.
const PAGE_SIZE = 25;

export default function AdminSkillsPage() {
  const t = useTranslations("admin.skills");
  const access = useAccess();
  const canView = access.has("view_global_analytics");
  const [offset, setOffset] = useState(0);
  const matrix = useSkillMatrix({ limit: PAGE_SIZE, offset }, canView);

  return (
    <>
      <SectionHeader title={t("title")} subtitle={t("subtitle")} />

      {!access.ready ? (
        <Skeleton className="h-24 w-full" />
      ) : !canView ? (
        <EmptyState title={t("noAccessTitle")} description={t("noAccessDescription")} />
      ) : matrix.isLoading || !matrix.data ? (
        <Skeleton className="h-64 w-full" />
      ) : matrix.data.users.length === 0 ? (
        <EmptyState title={t("emptyTitle")} description={t("emptyDescription")} />
      ) : (
        <MatrixCard data={matrix.data} offset={offset} onOffset={setOffset} />
      )}
    </>
  );
}

function MatrixCard({
  data,
  offset,
  onOffset,
}: {
  data: SkillMatrix;
  offset: number;
  onOffset: (next: number) => void;
}) {
  const t = useTranslations("admin.skills");
  const from = offset + 1;
  const to = Math.min(offset + PAGE_SIZE, data.total_users);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("cardTitle", { count: data.total_users })}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("colUser")}</TableHead>
                {data.skills.map((skill) => (
                  <TableHead key={skill} className="text-right capitalize">
                    {skill}
                  </TableHead>
                ))}
                <TableHead className="text-right">{t("colTotal")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.users.map((u) => (
                <TableRow key={u.user_id}>
                  <TableCell className="font-medium">{u.display_name}</TableCell>
                  {data.skills.map((skill) => (
                    <TableCell
                      key={skill}
                      className="text-right tabular-nums text-muted-foreground"
                    >
                      {u.scores[skill] ?? 0}
                    </TableCell>
                  ))}
                  <TableCell className="text-right font-mono">{u.total}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            {t("range", { from, to, total: data.total_users })}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              {t("prev")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={offset + PAGE_SIZE >= data.total_users}
              onClick={() => onOffset(offset + PAGE_SIZE)}
            >
              {t("next")}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
