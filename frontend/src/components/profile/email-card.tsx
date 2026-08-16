"use client";

// Self-service add / change / clear of your own email (#106). Before this, an
// account registered without an address (legitimate under ADR-0015) was
// stranded: no password reset, and no way past the #74 verification gate
// without an administrator editing the record by hand.

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSiteSettings } from "@/lib/hooks/use-site-settings";
import { useChangeEmail } from "@/lib/hooks/use-users";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

export function EmailCard() {
  const user = useAuthStore((s) => s.user);
  const { data: settings } = useSiteSettings();
  const changeEmail = useChangeEmail();
  const confirm = useConfirm();

  const t = useTranslations("profile.email");
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");

  const current = user?.email ?? null;
  const verificationRequired = !!settings?.email_verification_enabled;
  // Removing the address is refused server-side while a verification gate is
  // on — an account would have no way to satisfy it.
  const canClear = !!current && !verificationRequired;
  const changed = email.trim().toLowerCase() !== (current ?? "").toLowerCase();

  function submit(newEmail: string | null, successMessage: string) {
    changeEmail.mutate(
      { current_password: password, new_email: newEmail },
      {
        onSuccess: (updated) => {
          setPassword("");
          setEmail(updated.email ?? "");
          toast(
            updated.email && verificationRequired
              ? `${successMessage}${t("verifySuffix")}`
              : successMessage,
            { variant: "success" },
          );
        },
      },
    );
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit(email.trim(), current ? t("updatedToast") : t("addedToast"));
  }

  async function onClear() {
    if (
      !(await confirm({
        title: t("removeConfirmTitle"),
        description: t("removeConfirmDescription"),
        confirmLabel: t("removeConfirmLabel"),
        destructive: true,
      }))
    ) {
      return;
    }
    submit(null, t("removedToast"));
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>
          {current ? t("descriptionSet") : t("descriptionUnset")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid max-w-md gap-4">
          <div className="grid gap-2">
            <Label htmlFor="pem">{t("address")}</Label>
            <Input
              id="pem"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
              autoComplete="email"
            />
            {current && changed && (
              <p className="text-xs text-muted-foreground">
                {verificationRequired
                  ? t("changeHintVerify")
                  : t("changeHintNotify")}
              </p>
            )}
          </div>

          <div className="grid gap-2">
            <Label htmlFor="pemcur">{t("current")}</Label>
            <Input
              id="pemcur"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <p className="text-xs text-muted-foreground">{t("currentHint")}</p>
          </div>

          {changeEmail.isError && (
            <p role="alert" className="text-sm text-destructive">
              {(changeEmail.error as Error).message}
            </p>
          )}

          <div className="flex items-center gap-2">
            <Button type="submit" disabled={changeEmail.isPending || !changed}>
              {changeEmail.isPending ? t("saving") : current ? t("update") : t("add")}
            </Button>
            {canClear && (
              <Button
                type="button"
                variant="ghost"
                className="text-destructive"
                disabled={changeEmail.isPending || !password}
                onClick={onClear}
              >
                {t("remove")}
              </Button>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
