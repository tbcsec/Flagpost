"use client";

// /profile "API tokens" section (issue #75) — the *only* place a token is
// minted. A token always belongs to the account that created it: there is no
// holder picker here because the API has no field for one, so no user (however
// privileged) can issue a credential that acts as somebody else.

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import {
  useCreateApiToken,
  useMyApiTokens,
  useRevokeMyApiToken,
} from "@/lib/hooks/use-api-tokens";
import type { ApiToken, ApiTokenCreated } from "@/lib/types";
import { toast } from "@/stores/toast";

export function MyApiTokensCard() {
  // `t` is a token in the row loop below, so the translator is `tr`.
  const tr = useTranslations("profile.tokens");
  const tokens = useMyApiTokens();
  const revoke = useRevokeMyApiToken();
  const confirm = useConfirm();
  const [createOpen, setCreateOpen] = useState(false);
  const [revealed, setRevealed] = useState<ApiTokenCreated | null>(null);

  const rows = tokens.data ?? [];

  async function onRevoke(t: ApiToken) {
    if (
      !(await confirm({
        title: tr("revokeConfirmTitle"),
        description: tr("revokeConfirmDescription", { description: t.description }),
        confirmLabel: tr("revokeConfirmLabel"),
        destructive: true,
      }))
    ) {
      return;
    }
    revoke.mutate(t.id, {
      onSuccess: () => toast(tr("revokedToast")),
      onError: (e) => toast(tr("revokeError"), { description: (e as Error).message, variant: "destructive" }),
    });
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div className="grid gap-1.5">
          <CardTitle>{tr("title")}</CardTitle>
          <CardDescription>{tr("description")}</CardDescription>
        </div>
        <Button onClick={() => setCreateOpen(true)}>{tr("create")}</Button>
      </CardHeader>
      <CardContent>
        {tokens.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : tokens.isError ? (
          // Distinct from "no tokens": silently rendering an empty state on a
          // failed fetch would tell someone they have no tokens when a live one
          // may still be authenticating.
          <p role="alert" className="text-sm text-destructive">
            {tr("loadError", { message: (tokens.error as Error).message })}
          </p>
        ) : rows.length === 0 ? (
          <EmptyState
            title={tr("emptyTitle")}
            description={tr("emptyDescription")}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{tr("colDescription")}</TableHead>
                <TableHead>{tr("colExpires")}</TableHead>
                <TableHead>{tr("colLastUsed")}</TableHead>
                <TableHead>{tr("colStatus")}</TableHead>
                <TableHead className="text-right">{tr("colActions")}</TableHead>
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
                      {t.last_used_at ? relativeTime(t.last_used_at) : tr("never")}
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
                          {tr("revoke")}
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

      <CreateTokenDialog
        key={createOpen ? "open" : "closed"}
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={setRevealed}
      />
      <RevealTokenDialog token={revealed} onOpenChange={() => setRevealed(null)} />
    </Card>
  );
}

function CreateTokenDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (token: ApiTokenCreated) => void;
}) {
  const tr = useTranslations("profile.tokens");
  const create = useCreateApiToken();
  // Seeded on mount; the call site keys this dialog by open-state so each open
  // starts from a clean form.
  const [description, setDescription] = useState("");
  const [expiresInDays, setExpiresInDays] = useState("90");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      { description: description.trim(), expires_in_days: Number(expiresInDays) || 90 },
      {
        onSuccess: (token) => {
          onOpenChange(false);
          onCreated(token);
        },
        onError: (err) =>
          toast(tr("createError"), { description: (err as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{tr("createTitle")}</DialogTitle>
          <DialogDescription>{tr("createDescription")}</DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-2">
            <Label htmlFor="token-desc">{tr("descLabel")}</Label>
            <Input
              id="token-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={tr("descPlaceholder")}
              maxLength={200}
              required
              autoFocus
            />
            <p className="text-xs text-muted-foreground">{tr("descHint")}</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="token-expiry">{tr("expiresLabel")}</Label>
            <Input
              id="token-expiry"
              type="number"
              min={1}
              value={expiresInDays}
              onChange={(e) => setExpiresInDays(e.target.value)}
              className="w-32"
              required
            />
          </div>
          {create.error && (
            <p role="alert" className="text-sm text-destructive">{(create.error as Error).message}</p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={create.isPending || !description.trim()}>
              {create.isPending ? tr("creating") : tr("createSubmit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RevealTokenDialog({
  token,
  onOpenChange,
}: {
  token: ApiTokenCreated | null;
  onOpenChange: (open: boolean) => void;
}) {
  const tr = useTranslations("profile.tokens");
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token.token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast(tr("copyError"), { variant: "destructive" });
    }
  }

  return (
    <Dialog open={Boolean(token)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{tr("revealTitle")}</DialogTitle>
          <DialogDescription>
            {tr.rich("revealDescription", {
              code: (chunks) => <span className="font-mono text-xs">{chunks}</span>,
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2">
          <Input
            readOnly
            value={token?.token ?? ""}
            className="font-mono text-xs"
            onFocus={(e) => e.target.select()}
          />
          <Button type="button" variant="outline" onClick={onCopy}>
            {copied ? tr("copied") : tr("copy")}
          </Button>
        </div>
        <DialogFooter>
          <Button type="button" onClick={() => onOpenChange(false)}>{tr("done")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
