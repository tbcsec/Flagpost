"use client";

import { useTranslations } from "next-intl";
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { UserAvatar } from "@/components/ui/user-avatar";
import { useRemoveAvatar, useUploadAvatar } from "@/lib/hooks/use-users";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

// Self-service profile picture. The server accepts PNG/JPEG/WebP and stores
// its own square re-encode, so no client-side cropping is needed — whatever is
// uploaded comes back normalised.
export function AvatarCard() {
  const t = useTranslations("profile.avatar");
  const user = useAuthStore((s) => s.user);
  const upload = useUploadAvatar();
  const remove = useRemoveAvatar();
  const fileInput = useRef<HTMLInputElement>(null);

  if (!user) return null;
  const hasAvatar = user.avatar_updated_at !== null;

  function onFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    upload.mutate(file, {
      onSuccess: () => toast(t("updatedToast"), { variant: "success" }),
      onError: (err) =>
        toast(t("uploadFailed"), {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex items-center gap-4">
        <UserAvatar
          userId={user.id}
          name={user.display_name}
          avatarUpdatedAt={user.avatar_updated_at}
          size={72}
        />
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={onFileChosen}
          />
          <Button
            variant="outline"
            disabled={upload.isPending}
            onClick={() => fileInput.current?.click()}
          >
            {upload.isPending
              ? t("uploading")
              : hasAvatar
                ? t("replace")
                : t("upload")}
          </Button>
          {hasAvatar && (
            <Button
              variant="ghost"
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate(undefined, {
                  onSuccess: () => toast(t("removedToast"), { variant: "success" }),
                })
              }
            >
              {t("remove")}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
