"use client";

// Settings → Sharing (#427): the organiser's invite-link surface — mint, copy,
// and revoke shareable competition links. Join links admit people (any
// visibility — the token is the authorization); view links are a read-only
// front door to the public spectator board, so they only exist for public
// competitions (enforced server-side; the capability picker explains it here).

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCreateInviteLink,
  useInviteLinks,
  useRevokeInviteLink,
} from "@/lib/hooks/use-invite-links";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import type { InviteLink } from "@/lib/types";
import { toast } from "@/stores/toast";

/** The Phase-3 landing route. Centralised so the copy button and the created
 * dialog can't drift from the real path. */
function inviteUrl(token: string): string {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return `${origin}/invite/${token}`;
}

/** Display status: `active` is the server's lifecycle verdict; the rest just
 * explains *why* a link is dead. */
function linkStatus(link: InviteLink): {
  key: "active" | "revoked" | "expired" | "usedUp";
  variant: "success" | "destructive" | "secondary";
} {
  if (link.active) return { key: "active", variant: "success" };
  if (link.revoked_at) return { key: "revoked", variant: "secondary" };
  if (link.expires_at && new Date(link.expires_at).getTime() < Date.now()) {
    return { key: "expired", variant: "destructive" };
  }
  return { key: "usedUp", variant: "secondary" };
}

export function InviteLinksPanel({
  competitionId,
  visibility,
}: {
  competitionId: string;
  visibility: "public" | "private";
}) {
  const t = useTranslations("inviteLinks");
  const rel = useRelativeTime();
  const links = useInviteLinks(competitionId);
  const revoke = useRevokeInviteLink(competitionId);
  const confirm = useConfirm();
  const [createOpen, setCreateOpen] = useState(false);
  const [created, setCreated] = useState<InviteLink | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const rows = links.data ?? [];

  async function onCopy(link: InviteLink) {
    try {
      await navigator.clipboard.writeText(inviteUrl(link.token));
      setCopiedId(link.id);
      setTimeout(() => setCopiedId((id) => (id === link.id ? null : id)), 2000);
    } catch {
      toast(t("copyError"), { variant: "destructive" });
    }
  }

  async function onRevoke(link: InviteLink) {
    if (
      !(await confirm({
        title: t("revokeConfirmTitle"),
        description: t("revokeConfirmDescription"),
        confirmLabel: t("revokeConfirmLabel"),
        destructive: true,
      }))
    ) {
      return;
    }
    revoke.mutate(link.id, {
      onSuccess: () => toast(t("revokedToast")),
      onError: (e) =>
        toast(t("revokeError"), {
          description: (e as Error).message,
          variant: "destructive",
        }),
    });
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div className="grid gap-1.5">
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </div>
        <Button onClick={() => setCreateOpen(true)}>{t("create")}</Button>
      </CardHeader>
      <CardContent>
        {links.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : links.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {t("loadError", { message: (links.error as Error).message })}
          </p>
        ) : rows.length === 0 ? (
          <EmptyState title={t("emptyTitle")} description={t("emptyDescription")} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("colCapability")}</TableHead>
                <TableHead>{t("colLabel")}</TableHead>
                <TableHead>{t("colUses")}</TableHead>
                <TableHead>{t("colLastUsed")}</TableHead>
                <TableHead>{t("colExpires")}</TableHead>
                <TableHead>{t("colStatus")}</TableHead>
                <TableHead className="text-right">{t("colActions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((link) => {
                const status = linkStatus(link);
                return (
                  <TableRow key={link.id}>
                    <TableCell>
                      <Badge variant="secondary">
                        {t(`capability.${link.capability}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-medium">
                      {link.label || "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {link.max_uses === null
                        ? link.use_count
                        : `${link.use_count} / ${link.max_uses}`}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {link.last_used_at ? rel(link.last_used_at) : t("never")}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {link.expires_at
                        ? new Date(link.expires_at).toLocaleString()
                        : t("noExpiry")}
                    </TableCell>
                    <TableCell>
                      <Badge variant={status.variant}>
                        {t(`status.${status.key}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {link.active && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => onCopy(link)}
                        >
                          {copiedId === link.id ? t("copied") : t("copy")}
                        </Button>
                      )}
                      {!link.revoked_at && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          disabled={revoke.isPending}
                          onClick={() => onRevoke(link)}
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

      <CreateLinkDialog
        key={createOpen ? "open" : "closed"}
        open={createOpen}
        onOpenChange={setCreateOpen}
        competitionId={competitionId}
        visibility={visibility}
        onCreated={setCreated}
      />
      <CreatedLinkDialog link={created} onOpenChange={() => setCreated(null)} />
    </Card>
  );
}

function CreateLinkDialog({
  open,
  onOpenChange,
  competitionId,
  visibility,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  competitionId: string;
  visibility: "public" | "private";
  onCreated: (link: InviteLink) => void;
}) {
  const t = useTranslations("inviteLinks");
  const create = useCreateInviteLink(competitionId);
  const [capability, setCapability] = useState<"join" | "view">("join");
  const [label, setLabel] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [maxUses, setMaxUses] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        capability,
        label: label.trim() || null,
        // datetime-local is the user's local time; the API wants UTC ISO.
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        max_uses: maxUses ? Number(maxUses) : null,
      },
      {
        onSuccess: (link) => {
          onOpenChange(false);
          onCreated(link);
        },
        onError: (err) =>
          toast(t("createError"), {
            description: (err as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("createTitle")}</DialogTitle>
          <DialogDescription>{t("createDescription")}</DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-2">
            <Label htmlFor="invite-capability">{t("capabilityLabel")}</Label>
            <Select
              id="invite-capability"
              value={capability}
              onChange={(e) => setCapability(e.target.value as "join" | "view")}
            >
              <option value="join">{t("capability.join")}</option>
              {/* View links are public-only (#427): the server 422s a private
                  competition, so don't offer the dead option. */}
              {visibility === "public" && (
                <option value="view">{t("capability.view")}</option>
              )}
            </Select>
            <p className="text-xs text-muted-foreground">
              {capability === "view"
                ? t("viewHint")
                : visibility === "public"
                  ? t("joinHint")
                  : t("joinHintPrivate")}
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="invite-label">{t("labelLabel")}</Label>
            <Input
              id="invite-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t("labelPlaceholder")}
              maxLength={200}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="invite-expires">{t("expiresLabel")}</Label>
            <Input
              id="invite-expires"
              type="datetime-local"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">{t("expiresHint")}</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="invite-max-uses">{t("maxUsesLabel")}</Label>
            <Input
              id="invite-max-uses"
              type="number"
              min={1}
              value={maxUses}
              onChange={(e) => setMaxUses(e.target.value)}
              className="w-32"
            />
            <p className="text-xs text-muted-foreground">{t("maxUsesHint")}</p>
          </div>
          {create.error && (
            <p role="alert" className="text-sm text-destructive">
              {(create.error as Error).message}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? t("creating") : t("createSubmit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function CreatedLinkDialog({
  link,
  onOpenChange,
}: {
  link: InviteLink | null;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("inviteLinks");
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(inviteUrl(link.token));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast(t("copyError"), { variant: "destructive" });
    }
  }

  return (
    <Dialog open={Boolean(link)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("createdTitle")}</DialogTitle>
          <DialogDescription>{t("createdDescription")}</DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2">
          <Input
            readOnly
            value={link ? inviteUrl(link.token) : ""}
            className="font-mono text-xs"
            onFocus={(e) => e.target.select()}
          />
          <Button type="button" variant="outline" onClick={onCopy}>
            {copied ? t("copied") : t("copy")}
          </Button>
        </div>
        <DialogFooter>
          <Button type="button" onClick={() => onOpenChange(false)}>
            {t("done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
