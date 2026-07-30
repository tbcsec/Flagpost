"use client";

// /profile "API tokens" section (issue #75) — self-service view/revoke of the
// current user's own tokens. Minting stays admin-only (Admin → Users); a
// holder can see and revoke, but not create, their own tokens.

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
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
import { useMyApiTokens, useRevokeMyApiToken } from "@/lib/hooks/use-api-tokens";
import type { ApiToken } from "@/lib/types";
import { toast } from "@/stores/toast";

export function MyApiTokensCard() {
  const tokens = useMyApiTokens();
  const revoke = useRevokeMyApiToken();
  const confirm = useConfirm();

  const rows = tokens.data ?? [];
  if (!tokens.isLoading && rows.length === 0) return null;

  async function onRevoke(t: ApiToken) {
    if (
      !(await confirm({
        title: "Revoke this token?",
        description: `${t.description} will stop authenticating immediately. This can't be undone.`,
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
      <CardHeader>
        <CardTitle>API tokens</CardTitle>
        <CardDescription>
          Personal API tokens minted for your account by an administrator.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {tokens.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
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
                    <TableCell className="font-medium">{t.description}</TableCell>
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
