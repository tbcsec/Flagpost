"use client";

import { useEffect, useMemo, useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { SkeletonCards } from "@/components/ui/skeleton";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useCompetitions } from "@/lib/hooks/use-competitions";
import {
  useAssignRole,
  useCreateRole,
  useDeleteRole,
  useRoleAssignments,
  useRoleCatalog,
  useRoles,
  useUnassignRole,
  useUpdateRole,
} from "@/lib/hooks/use-roles";
import { groupCatalog } from "@/lib/roles";
import type { Role } from "@/lib/types";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast";

export default function AdminRolesPage() {
  const access = useAccess();
  const roles = useRoles();
  const catalog = useRoleCatalog();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ open: boolean; cloneFrom: Role | null }>(
    { open: false, cloneFrom: null },
  );

  const selected = roles.data?.find((r) => r.id === selectedId) ?? null;
  // Default the selection to the first role once loaded.
  useEffect(() => {
    if (!selectedId && roles.data && roles.data.length > 0) {
      setSelectedId(roles.data[0].id);
    }
  }, [selectedId, roles.data]);

  if (access.ready && !access.has("manage_roles")) {
    return (
      <>
        <SectionHeader title="Admin — Roles" subtitle="Global — platform-wide, not scoped to a competition" />
        <p className="text-sm text-muted-foreground">You don&apos;t have access to role management.</p>
      </>
    );
  }

  return (
    <>
      <SectionHeader
        title="Admin — Roles"
        subtitle="Global — platform-wide, not scoped to a competition"
        actions={
          <Button onClick={() => setDialog({ open: true, cloneFrom: null })}>New role</Button>
        }
      />

      {roles.isLoading || catalog.isLoading ? (
        <SkeletonCards count={3} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <div className="grid content-start gap-2.5">
            {roles.data?.map((role) => (
              <button
                key={role.id}
                onClick={() => setSelectedId(role.id)}
                className={cn(
                  "grid gap-1 rounded-lg border p-3.5 text-left transition-colors",
                  selectedId === role.id ? "border-primary ring-1 ring-primary" : "border-border hover:border-primary/40",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{role.name}</span>
                  <Badge variant={role.is_system ? "secondary" : "success"}>
                    {role.is_system ? "System" : "Custom"}
                  </Badge>
                </div>
                <span className="text-xs text-muted-foreground">
                  {role.description || "No description"}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {role.scope} · {role.permissions.length} permission{role.permissions.length === 1 ? "" : "s"}
                </span>
              </button>
            ))}
          </div>

          {selected && (
            <RoleEditor
              key={selected.id}
              role={selected}
              onClone={() => setDialog({ open: true, cloneFrom: selected })}
              onDeleted={() => setSelectedId(null)}
            />
          )}
        </div>
      )}

      <AssignmentsCard roles={roles.data ?? []} />

      <RoleDialog
        state={dialog}
        onClose={() => setDialog({ open: false, cloneFrom: null })}
        onCreated={(id) => {
          setSelectedId(id);
          setDialog({ open: false, cloneFrom: null });
        }}
      />
    </>
  );
}

function RoleEditor({
  role,
  onClone,
  onDeleted,
}: {
  role: Role;
  onClone: () => void;
  onDeleted: () => void;
}) {
  const catalog = useRoleCatalog();
  const update = useUpdateRole();
  const del = useDeleteRole();

  const [description, setDescription] = useState(role.description);
  const [perms, setPerms] = useState<Set<string>>(new Set(role.permissions));

  const groups = useMemo(
    () => groupCatalog(catalog.data ?? [], role.scope),
    [catalog.data, role.scope],
  );
  const editable = !role.is_system;

  const dirty =
    description !== role.description ||
    perms.size !== role.permissions.length ||
    role.permissions.some((p) => !perms.has(p));

  function toggle(key: string) {
    setPerms((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function onSave() {
    update.mutate(
      { id: role.id, description, permissions: [...perms] },
      {
        onSuccess: () => toast("Role saved", { variant: "success" }),
        onError: (e) => toast("Couldn't save", { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  function onDelete() {
    del.mutate(role.id, {
      onSuccess: () => {
        toast("Role deleted");
        onDeleted();
      },
      onError: (e) => toast("Couldn't delete", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div className="grid gap-1">
          <CardTitle className="flex items-center gap-2">
            {role.name}
            <Badge variant={role.is_system ? "secondary" : "success"}>
              {role.is_system ? "System" : "Custom"}
            </Badge>
          </CardTitle>
          <CardDescription>
            {role.is_system
              ? "System role — read-only. Clone it to make an editable variant."
              : `Custom · ${role.scope}-scoped`}
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" onClick={onClone}>Clone</Button>
      </CardHeader>
      <CardContent className="grid gap-5">
        {editable && (
          <div className="grid max-w-md gap-2">
            <Label htmlFor="role-desc">Description</Label>
            <Input id="role-desc" value={description} maxLength={280} onChange={(e) => setDescription(e.target.value)} />
          </div>
        )}

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          {groups.map((group) => (
            <div key={group.category}>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {group.category}
              </div>
              <div className="grid gap-1.5">
                {group.entries.map((entry) => (
                  <label
                    key={entry.key}
                    className={cn("flex items-center gap-2 text-[13px]", !editable && "opacity-70")}
                  >
                    <input
                      type="checkbox"
                      checked={perms.has(entry.key)}
                      disabled={!editable}
                      onChange={() => toggle(entry.key)}
                    />
                    <span className="font-mono text-xs">{entry.key}</span>
                    {entry.reserved && <span className="text-[10px] text-warning">reserved</span>}
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>

        {editable && (
          <div className="flex items-center gap-3 border-t border-border pt-4">
            <Button onClick={onSave} disabled={!dirty || update.isPending}>
              {update.isPending ? "Saving…" : "Save changes"}
            </Button>
            <Button variant="outline" size="sm" className="text-destructive" onClick={onDelete} disabled={del.isPending}>
              Delete role
            </Button>
            {dirty && <span className="text-xs text-muted-foreground">Unsaved changes.</span>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RoleDialog({
  state,
  onClose,
  onCreated,
}: {
  state: { open: boolean; cloneFrom: Role | null };
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const create = useCreateRole();
  const cloning = state.cloneFrom;
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"global" | "competition">("competition");

  // Seed the fields whenever the dialog opens.
  useEffect(() => {
    if (state.open) {
      setName(cloning ? `${cloning.name} copy` : "");
      setScope(cloning ? cloning.scope : "competition");
    }
  }, [state.open, cloning]);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      cloning ? { name, clone_from: cloning.id } : { name, scope, permissions: [] },
      {
        onSuccess: (role) => onCreated(role.id),
        onError: (err) => toast("Couldn't create role", { description: (err as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <Dialog open={state.open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{cloning ? `Clone ${cloning.name}` : "New custom role"}</DialogTitle>
          <DialogDescription>
            {cloning
              ? "Creates an editable copy with the same permissions and scope."
              : "Starts empty — pick its permissions after creating."}
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-2">
            <Label htmlFor="new-role-name">Name</Label>
            <Input id="new-role-name" value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
          </div>
          {!cloning && (
            <div className="grid gap-2">
              <Label htmlFor="new-role-scope">Scope</Label>
              <Select id="new-role-scope" value={scope} onChange={(e) => setScope(e.target.value as "global" | "competition")}>
                <option value="competition">Competition — assigned per competition</option>
                <option value="global">Global — assigned site-wide</option>
              </Select>
            </div>
          )}
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating…" : cloning ? "Clone role" : "Create role"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AssignmentsCard({ roles }: { roles: Role[] }) {
  const assignments = useRoleAssignments();
  const competitions = useCompetitions();
  const assign = useAssignRole();
  const unassign = useUnassignRole();

  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState("");
  const [competitionId, setCompetitionId] = useState("");

  const selectedRole = roles.find((r) => r.id === roleId) ?? null;
  const needsCompetition = selectedRole?.scope === "competition";

  function onAssign(e: React.FormEvent) {
    e.preventDefault();
    assign.mutate(
      {
        email: email.trim(),
        role_id: roleId,
        competition_id: needsCompetition ? competitionId : null,
      },
      {
        onSuccess: () => {
          toast("Role assigned", { variant: "success" });
          setEmail("");
        },
        onError: (err) => toast("Couldn't assign", { description: (err as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Assignments</CardTitle>
        <CardDescription>Grant a role to a user by email — per competition, or site-wide for a global role.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <form className="grid gap-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end" onSubmit={onAssign}>
          <div className="grid gap-1.5">
            <Label htmlFor="assign-email">User email</Label>
            <Input id="assign-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="assign-role">Role</Label>
            <Select id="assign-role" value={roleId} onChange={(e) => setRoleId(e.target.value)} required>
              <option value="" disabled>Select a role…</option>
              {roles.map((r) => (
                <option key={r.id} value={r.id}>{r.name} ({r.scope})</option>
              ))}
            </Select>
          </div>
          {needsCompetition ? (
            <div className="grid gap-1.5">
              <Label htmlFor="assign-comp">Competition</Label>
              <Select id="assign-comp" value={competitionId} onChange={(e) => setCompetitionId(e.target.value)} required>
                <option value="" disabled>Select…</option>
                {competitions.data?.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </Select>
            </div>
          ) : (
            <div className="grid gap-1.5">
              <Label>Scope</Label>
              <div className="flex h-9 items-center text-sm text-muted-foreground">Site-wide</div>
            </div>
          )}
          <Button type="submit" disabled={assign.isPending || !roleId}>Assign</Button>
        </form>

        <div className="grid gap-2">
          {assignments.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">No role assignments yet.</p>
          )}
          {assignments.data?.map((a) => (
            <div key={a.id} className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm">
              <div className="min-w-0">
                <span className="font-medium">{a.user_email}</span>
                <span className="text-muted-foreground">
                  {" "}· {a.role_name} · {a.competition_name ?? "site-wide"}
                </span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive"
                onClick={() =>
                  unassign.mutate(a.id, {
                    onSuccess: () => toast("Unassigned"),
                    onError: (err) => toast("Couldn't unassign", { description: (err as Error).message, variant: "destructive" }),
                  })
                }
              >
                Remove
              </Button>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
