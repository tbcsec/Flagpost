"use client";

// Admin → Users, "API tokens" section (issue #75) — **oversight only**.
// Administrators (manage_api_tokens) see every token on the platform and can
// revoke any of them, so a leaked credential can be killed by someone other
// than its holder. There is deliberately no minting here: a token is always
// created by, and belongs to, the account using it (see
// components/profile/api-tokens-card.tsx), so no permission can issue a
// credential that acts as another user.

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
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
import { apiTokenStatus } from "@/lib/api-token-status";
import { relativeTime } from "@/lib/datetime";
import { useApiTokens, useRevokeApiToken } from "@/lib/hooks/use-api-tokens";
import type { ApiToken } from "@/lib/types";
import { toast } from "@/stores/toast";

export function ApiTokensPanel() {
  const t = useTranslations("admin.apiTokens");
  const tStatus = useTranslations("profile.tokens");
  const tokens = useApiTokens();
  const revoke = useRevokeApiToken();
  const confirm = useConfirm();

  const rows = tokens.data ?? [];

  async function onRevoke(token: ApiToken) {
    if (
      !(await confirm({
        title: t("revokeTitle"),
        description: t("revokeDescription", {
          description: token.description,
          holder: token.user_display_name,
        }),
        confirmLabel: t("revokeConfirm"),
        destructive: true,
      }))
    ) {
      return;
    }
    revoke.mutate(token.id, {
      onSuccess: () => toast(t("tokenRevoked")),
      onError: (e) => toast(t("couldntRevoke"), { description: (e as Error).message, variant: "destructive" }),
    });
  }

  return (
    <Card>
      <CardContent className="pt-5">
        <div className="mb-4">
          <h3 className="text-sm font-semibold">{t("heading")}</h3>
          <p className="text-xs text-muted-foreground">{t("headingDescription")}</p>
        </div>

        {tokens.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : tokens.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {t("loadError", { error: (tokens.error as Error).message })}
          </p>
        ) : rows.length === 0 ? (
          <EmptyState
            title={t("noTokensTitle")}
            description={t("noTokensDescription")}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("colHolder")}</TableHead>
                <TableHead>{t("colDescription")}</TableHead>
                <TableHead>{t("colExpires")}</TableHead>
                <TableHead>{t("colLastUsed")}</TableHead>
                <TableHead>{t("colStatus")}</TableHead>
                <TableHead className="text-right">{t("colActions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((token) => {
                const status = apiTokenStatus(token);
                return (
                  <TableRow key={token.id}>
                    <TableCell className="font-medium">{token.user_display_name}</TableCell>
                    <TableCell className="text-muted-foreground">{token.description}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(token.expires_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {token.last_used_at ? relativeTime(token.last_used_at) : t("never")}
                    </TableCell>
                    <TableCell>
                      <Badge variant={status.variant}>{tStatus(`status.${status.key}`)}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {!token.revoked_at && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          disabled={revoke.isPending}
                          onClick={() => onRevoke(token)}
                        >
                          {t("revoke")}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
