"use client";

// Admin → Users, "API tokens" section (issue #75). Mint a personal API token
// for any user (manage_api_tokens), see the full inventory, and revoke one.
// The one-time reveal dialog is the only place the raw token is ever shown.

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { EntityCombobox } from "@/components/ui/entity-combobox";
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
  useApiTokens,
  useCreateApiToken,
  useRevokeApiToken,
} from "@/lib/hooks/use-api-tokens";
import { useUsers } from "@/lib/hooks/use-users";
import type { ApiToken, ApiTokenCreated } from "@/lib/types";
import { toast } from "@/stores/toast";

export function ApiTokensPanel() {
  const tokens = useApiTokens();
  const revoke = useRevokeApiToken();
  const confirm = useConfirm();
  const [createOpen, setCreateOpen] = useState(false);
  const [revealed, setRevealed] = useState<ApiTokenCreated | null>(null);

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
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold">API tokens</h3>
            <p className="text-xs text-muted-foreground">
              Programmatic REST access, minted per user with that user&apos;s full permissions.
            </p>
          </div>
          <Button size="sm" onClick={() => setCreateOpen(true)}>Create token</Button>
        </div>

        {tokens.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : rows.length === 0 ? (
          <EmptyState title="No API tokens" description="No personal API tokens have been minted yet." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Holder</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Created by</TableHead>
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
                      {t.created_by_display_name ?? "—"}
                    </TableCell>
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
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(created) => setRevealed(created)}
      />
      <RevealTokenDialog token={revealed} onOpenChange={(o) => !o && setRevealed(null)} />
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
  const users = useUsers("");
  const create = useCreateApiToken();
  const [userId, setUserId] = useState("");
  const [description, setDescription] = useState("");
  const [expiresInDays, setExpiresInDays] = useState("30");

  const userOptions = useMemo(
    () =>
      (users.data ?? []).map((u) => ({
        value: u.id,
        label: u.display_name,
        hint: u.email ?? undefined,
      })),
    [users.data],
  );

  function reset() {
    setUserId("");
    setDescription("");
    setExpiresInDays("30");
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const days = Number(expiresInDays);
    if (!userId || !description.trim() || !Number.isFinite(days) || days <= 0) return;
    create.mutate(
      { user_id: userId, description: description.trim(), expires_in_days: days },
      {
        onSuccess: (token) => {
          reset();
          onOpenChange(false);
          onCreated(token);
        },
        onError: (err) =>
          toast("Couldn't create token", { description: (err as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) reset(); onOpenChange(o); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create API token</DialogTitle>
          <DialogDescription>
            The token authenticates as its holder, with their full effective permissions.
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-2">
            <Label htmlFor="token-user">Holder</Label>
            <EntityCombobox
              id="token-user"
              options={userOptions}
              value={userId}
              onChange={setUserId}
              placeholder="Search by name or email…"
              emptyText={users.isLoading ? "Loading users…" : "No matching users"}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="token-desc">Description</Label>
            <Input
              id="token-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. CI grading bot"
              maxLength={200}
              required
            />
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
            <Button type="submit" disabled={create.isPending || !userId || !description.trim()}>
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
            Copy it now — for {token?.user_display_name}. It won&apos;t be shown again.
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2">
          <Input readOnly value={token?.token ?? ""} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
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
