"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
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
import { useCreateUser, useUpdateUser } from "@/lib/hooks/use-users";
import type { UserAccount } from "@/lib/types";
import { toast } from "@/stores/toast";

// Create or edit an account (Admin → Users). On edit, the password field is
// optional — left blank it's unchanged; set, it resets and signs the user out
// everywhere (enforced server-side).
export function UserFormDialog({
  mode,
  user,
  open,
  onOpenChange,
}: {
  mode: "create" | "edit";
  user?: UserAccount;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const create = useCreateUser();
  const update = useUpdateUser();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");

  // Reset the form to the target each time the dialog opens.
  useEffect(() => {
    if (open) {
      setEmail(user?.email ?? "");
      setDisplayName(user?.display_name ?? "");
      setPassword("");
    }
  }, [open, user]);

  const pending = create.isPending || update.isPending;
  const error = (create.error ?? update.error) as Error | null;

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (mode === "create") {
      create.mutate(
        { display_name: displayName, password, email: email.trim() || undefined },
        {
          onSuccess: () => {
            toast(`Created ${displayName}`, { variant: "success" });
            onOpenChange(false);
          },
        },
      );
    } else if (user) {
      update.mutate(
        {
          id: user.id,
          display_name: displayName,
          // Blank leaves the existing email unchanged (omitted, not cleared).
          ...(email.trim() ? { email: email.trim() } : {}),
          ...(password ? { password } : {}),
        },
        {
          onSuccess: () => {
            toast("Account updated", { variant: "success" });
            onOpenChange(false);
          },
        },
      );
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{mode === "create" ? "Create account" : "Edit account"}</DialogTitle>
          <DialogDescription>
            {mode === "create"
              ? "The account can sign in immediately with the password you set. Grant an Administrator or per-competition role on Admin → Roles."
              : "Change the name, email, or reset the password. A new password signs the user out everywhere."}
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-2">
            <Label htmlFor="user-name">Username</Label>
            <Input
              id="user-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
            />
            <p className="text-xs text-muted-foreground">
              The login identifier and display name — must be unique.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="user-email">Email (optional)</Label>
            <Input
              id="user-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={mode === "edit" ? "Leave blank to keep unchanged" : ""}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="user-password">
              {mode === "create" ? "Password" : "New password"}
              {mode === "edit" && (
                <span className="ml-1 text-xs text-muted-foreground">(leave blank to keep)</span>
              )}
            </Label>
            <Input
              id="user-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required={mode === "create"}
              placeholder={mode === "edit" ? "••••••••" : undefined}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error.message}</p>}
          <DialogFooter>
            <Button type="submit" disabled={pending}>
              {pending ? "Saving…" : mode === "create" ? "Create account" : "Save changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
