"use client";

// Admin → Users, "API tokens" section (issue #75) — **oversight only**.
// Administrators (manage_api_tokens) see every token on the platform and can
// revoke any of them, so a leaked credential can be killed by someone other
// than its holder. There is deliberately no minting here: a token is always
// created by, and belongs to, the account using it (see
// components/profile/api-tokens-card.tsx), so no permission can issue a
// credential that acts as another user.

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
  const tokens = useApiTokens();
  const revoke = useRevokeApiToken();
  const confirm = useConfirm();

  const rows = tokens.data ?? [];

  async function onRevoke(t: ApiToken) {
    if (
      !(await confirm({
        title: "Revoke this token?",
        description: `${t.description} (held by ${t.user_display_name}) will stop authenticating immediately. This can't be undone.`,
        confirmLabel: "Revoke",
        destructive: true,
      }))
    ) {
      return;
    }
    revoke.mutate(t.id, {
      onSuccess: () => toast("Token revoked"),
      onError: (e) => toast("Couldn't revoke", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  return (
    <Card>
      <CardContent className="pt-5">
        <div className="mb-4">
          <h3 className="text-sm font-semibold">API tokens</h3>
          <p className="text-xs text-muted-foreground">
            Every token on the platform. Users create their own from their
            profile; you can revoke any of them here.
          </p>
        </div>

        {tokens.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : tokens.isError ? (
          <p role="alert" className="text-sm text-destructive">
            Couldn&apos;t load tokens: {(tokens.error as Error).message}
          </p>
        ) : rows.length === 0 ? (
          <EmptyState
            title="No API tokens"
            description="Nobody has created a personal API token yet."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Holder</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((t) => {
                const status = apiTokenStatus(t);
                return (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">{t.user_display_name}</TableCell>
                    <TableCell className="text-muted-foreground">{t.description}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(t.expires_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {t.last_used_at ? relativeTime(t.last_used_at) : "Never"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={status.variant}>{status.label}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {!t.revoked_at && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          disabled={revoke.isPending}
                          onClick={() => onRevoke(t)}
                        >
                          Revoke
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
