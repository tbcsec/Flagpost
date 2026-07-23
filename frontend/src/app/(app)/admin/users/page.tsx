"use client";

import { useEffect, useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { UserFormDialog } from "@/components/admin/user-form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { relativeTime } from "@/lib/datetime";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useBanUser, useDeleteUser, useUsers } from "@/lib/hooks/use-users";
import type { UserAccount } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

// Admin → Users. The account directory + lifecycle (§7): search, create, edit,
// ban/unban, delete — all off /api/users, gated on view_all_users (read) and
// manage_users (write). Per-competition role assignment stays on Admin → Roles.
export default function AdminUsersPage() {
  const access = useAccess();
  const selfId = useAuthStore((s) => s.user?.id);
  const canView = access.has("view_all_users");
  const canManage = access.has("manage_users");

  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  // Debounce so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => setQ(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  const users = useUsers(canView ? q : "");
  const ban = useBanUser();
  const del = useDeleteUser();

  const [dialog, setDialog] = useState<{ mode: "create" } | { mode: "edit"; user: UserAccount } | null>(null);
  const [deleting, setDeleting] = useState<UserAccount | null>(null);

  if (!access.ready) return <Skeleton className="h-64 w-full" />;
  if (!canView) {
    return (
      <>
        <SectionHeader title="Admin — Users" subtitle="Global — platform-wide" />
        <EmptyState title="No access" description="You need the view-all-users permission to see the directory." />
      </>
    );
  }

  function onBan(u: UserAccount) {
    ban.mutate(
      { id: u.id, banned: u.is_active },
      {
        onSuccess: () => toast(`${u.display_name} ${u.is_active ? "banned" : "unbanned"}`),
        onError: (e) => toast("Couldn't update", { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  function confirmDelete() {
    if (!deleting) return;
    del.mutate(deleting.id, {
      onSuccess: () => {
        toast(`Deleted ${deleting.display_name}`, { variant: "success" });
        setDeleting(null);
      },
      onError: (e) => toast("Couldn't delete", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  const rows = users.data ?? [];

  return (
    <>
      <SectionHeader
        title="Admin — Users"
        subtitle="Global — every account on the platform"
        actions={
          canManage ? <Button onClick={() => setDialog({ mode: "create" })}>Create account</Button> : undefined
        }
      />

      <Input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by name or email…"
        className="max-w-sm"
      />

      {users.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : rows.length === 0 ? (
        <EmptyState
          title={q ? "No matches" : "No accounts"}
          description={q ? "No accounts match your search." : "No accounts on the platform yet."}
        />
      ) : (
        <Card>
          <CardContent className="pt-5">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((u) => {
                  const isSelf = u.id === selfId;
                  return (
                    <TableRow key={u.id}>
                      <TableCell className="font-medium">
                        {u.display_name}
                        {isSelf && <span className="ml-2 text-xs text-primary">You</span>}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{u.email ?? "—"}</TableCell>
                      <TableCell>
                        <Badge variant={u.is_administrator ? "success" : "outline"}>
                          {u.is_administrator ? "Administrator" : "User"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant={u.is_active ? "muted" : "destructive"}>
                          {u.is_active ? "Active" : "Banned"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {relativeTime(u.created_at)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right">
                        {canManage && (
                          <div className="flex justify-end gap-1">
                            <Button variant="ghost" size="sm" onClick={() => setDialog({ mode: "edit", user: u })}>
                              Edit
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={isSelf || ban.isPending}
                              onClick={() => onBan(u)}
                            >
                              {u.is_active ? "Ban" : "Unban"}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-destructive"
                              disabled={isSelf}
                              onClick={() => setDeleting(u)}
                            >
                              Delete
                            </Button>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {dialog && (
        <UserFormDialog
          mode={dialog.mode}
          user={dialog.mode === "edit" ? dialog.user : undefined}
          open={Boolean(dialog)}
          onOpenChange={(o) => !o && setDialog(null)}
        />
      )}

      <Dialog open={Boolean(deleting)} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete account?</DialogTitle>
            <DialogDescription>
              This permanently removes <span className="font-medium">{deleting?.display_name}</span> and all
              of their data (submissions, tickets, team memberships…). This can&apos;t be undone —
              consider banning instead.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={del.isPending}>
              {del.isPending ? "Deleting…" : "Delete account"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
