"use client";

// One hook module per domain (ARCHITECTURE.md §8). RBAC roles admin (§7.4) —
// list/clone/edit/delete custom roles, read the permission catalog, and
// assign/unassign roles to users. All gated on manage_roles server-side.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { rolesApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

const roleKeys = {
  all: ["roles"] as const,
  list: ["roles", "list"] as const,
  catalog: ["roles", "catalog"] as const,
  assignments: ["roles", "assignments"] as const,
};

function useIsAuthed() {
  return useAuthStore((s) => s.status === "authenticated");
}

export function useRoles() {
  return useQuery({
    queryKey: roleKeys.list,
    queryFn: rolesApi.list,
    enabled: useIsAuthed(),
  });
}

export function useRoleCatalog() {
  return useQuery({
    queryKey: roleKeys.catalog,
    queryFn: rolesApi.catalog,
    enabled: useIsAuthed(),
    staleTime: 5 * 60_000, // the catalog only changes with a deploy
  });
}

export function useRoleAssignments() {
  return useQuery({
    queryKey: roleKeys.assignments,
    queryFn: rolesApi.assignments,
    enabled: useIsAuthed(),
  });
}

export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: rolesApi.create,
    onSuccess: () => qc.invalidateQueries({ queryKey: roleKeys.list }),
  });
}

export function useUpdateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...input }: { id: string; name?: string; description?: string; permissions?: string[] }) =>
      rolesApi.update(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: roleKeys.list }),
  });
}

export function useDeleteRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => rolesApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: roleKeys.all }),
  });
}

export function useAssignRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: rolesApi.assign,
    onSuccess: () => qc.invalidateQueries({ queryKey: roleKeys.assignments }),
  });
}

export function useUnassignRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (assignmentId: string) => rolesApi.unassign(assignmentId),
    onSuccess: () => qc.invalidateQueries({ queryKey: roleKeys.assignments }),
  });
}
