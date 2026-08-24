"use client";

// Self-service username (display-name) change. The username is the primary
// login handle (ADR-0015), so the change requires the current password and is
// rate-limited by a server-side cooldown; when the cooldown is active the form
// is disabled and the next-allowed date is shown rather than letting the user
// submit into a guaranteed refusal.

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
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
import { useChangeUsername } from "@/lib/hooks/use-users";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

export function UsernameCard() {
  const t = useTranslations("profile.username");
  const user = useAuthStore((s) => s.user);
  const site = useSiteSettings();
  const change = useChangeUsername();
  const [name, setName] = useState(user?.display_name ?? "");
  const [password, setPassword] = useState("");

  if (!user) return null;
  // Site policy (#298): renames disabled ⇒ no card at all — the server 403s
  // anyway, so offering the form would only manufacture a dead end.
  if (site.data && !site.data.username_changes_enabled) return null;

  const allowedAt = user.username_change_allowed_at
    ? new Date(user.username_change_allowed_at)
    : null;
  const onCooldown = allowedAt !== null && allowedAt > new Date();
  const changed = name.trim() !== user.display_name && name.trim().length > 0;

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    change.mutate(
      { current_password: password, new_display_name: name.trim() },
      {
        onSuccess: (updated) => {
          setPassword("");
          setName(updated.display_name);
          toast(t("updatedToast", { name: updated.display_name }), {
            variant: "success",
          });
        },
        onError: (err) =>
          toast(t("failed"), {
            description: (err as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {onCooldown ? (
          <p className="text-sm text-muted-foreground">
            {t("cooldown", { date: allowedAt!.toLocaleDateString() })}
          </p>
        ) : (
          <form onSubmit={onSubmit} className="grid max-w-md gap-4">
            <div className="grid gap-2">
              <Label htmlFor="pun">{t("username")}</Label>
              <Input
                id="pun"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={120}
                required
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="pun-pw">{t("currentPassword")}</Label>
              <Input
                id="pun-pw"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            <p className="text-xs text-muted-foreground">{t("cooldownHint")}</p>
            <div>
              <Button type="submit" disabled={!changed || !password || change.isPending}>
                {change.isPending ? t("saving") : t("save")}
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
