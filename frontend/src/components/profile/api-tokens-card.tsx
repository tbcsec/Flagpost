"use client";

// /profile "API tokens" section (issue #75) — the *only* place a token is
// minted. A token always belongs to the account that created it: there is no
// holder picker here because the API has no field for one, so no user (however
// privileged) can issue a credential that acts as somebody else.

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
  const tokens = useMyApiTokens();
  const revoke = useRevokeMyApiToken();
  const confirm = useConfirm();
  const [createOpen, setCreateOpen] = useState(false);
  const [revealed, setRevealed] = useState<ApiTokenCreated | null>(null);

  const rows = tokens.data ?? [];

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
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div className="grid gap-1.5">
          <CardTitle>API tokens</CardTitle>
          <CardDescription>
            Use a token instead of signing in to call the API from a script. Each
            one acts as you, with your permissions, and is shown only once.
          </CardDescription>
        </div>
        <Button onClick={() => setCreateOpen(true)}>Create token</Button>
      </CardHeader>
      <CardContent>
        {tokens.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : tokens.isError ? (
          // Distinct from "no tokens": silently rendering an empty state on a
          // failed fetch would tell someone they have no tokens when a live one
          // may still be authenticating.
          <p role="alert" className="text-sm text-destructive">
            Couldn&apos;t load your tokens: {(tokens.error as Error).message}
          </p>
        ) : rows.length === 0 ? (
          <EmptyState
            title="No API tokens"
            description="Create one to call the Flagpost API from a script or CI job."
          />
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
          toast("Couldn't create token", { description: (err as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create API token</DialogTitle>
          <DialogDescription>
            The token acts as you, with your own permissions. Tokens can only be
            created for your own account.
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-2">
            <Label htmlFor="token-desc">Description</Label>
            <Input
              id="token-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. CI grading bot"
              maxLength={200}
              required
              autoFocus
            />
            <p className="text-xs text-muted-foreground">
              So you can tell your tokens apart later.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="token-expiry">Expires in (days)</Label>
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
              {create.isPending ? "Creating…" : "Create token"}
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
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token.token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast("Couldn't copy — select and copy manually", { variant: "destructive" });
    }
  }

  return (
    <Dialog open={Boolean(token)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Token created</DialogTitle>
          <DialogDescription>
            Copy it now — it won&apos;t be shown again. Send it in an
            <span className="font-mono text-xs"> Authorization: Bearer </span>
            header.
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
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
        <DialogFooter>
          <Button type="button" onClick={() => onOpenChange(false)}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
