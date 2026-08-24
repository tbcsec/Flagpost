"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

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
  const t = useTranslations("admin.userForm");
  const create = useCreateUser();
  const update = useUpdateUser();
  // Seeded on mount: the call site renders this dialog only while open and
  // keys it by the target account, so opening (or switching target) always
  // remounts with fresh fields.
  const [email, setEmail] = useState(user?.email ?? "");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [password, setPassword] = useState("");

  const pending = create.isPending || update.isPending;
  const error = (create.error ?? update.error) as Error | null;

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (mode === "create") {
      create.mutate(
        { display_name: displayName, password, email: email.trim() || undefined },
        {
          onSuccess: () => {
            toast(t("created", { name: displayName }), { variant: "success" });
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
            toast(t("updated"), { variant: "success" });
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
          <DialogTitle>{mode === "create" ? t("createTitle") : t("editTitle")}</DialogTitle>
          <DialogDescription>
            {mode === "create" ? t("createDescription") : t("editDescription")}
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-2">
            <Label htmlFor="user-name">{t("username")}</Label>
            <Input
              id="user-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
            />
            <p className="text-xs text-muted-foreground">{t("usernameHint")}</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="user-email">{t("emailOptional")}</Label>
            <Input
              id="user-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={mode === "edit" ? t("emailPlaceholderEdit") : ""}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="user-password">
              {mode === "create" ? t("password") : t("newPassword")}
              {mode === "edit" && (
                <span className="ml-1 text-xs text-muted-foreground">{t("passwordKeepHint")}</span>
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
          {error && <p role="alert" className="text-sm text-destructive">{error.message}</p>}
          <DialogFooter>
            <Button type="submit" disabled={pending}>
              {pending ? t("saving") : mode === "create" ? t("createSubmit") : t("saveChanges")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
