"use client";

// "A newer version is available" notice for administrators (#111).
//
// Deliberately restrained. It appears only when there is genuinely something to
// do, only for people who could act on it, and dismissing it pins to the
// *version* rather than setting a timer — so a given release nags at most once,
// while a genuinely newer one still gets through. That's the whole nagging
// policy; there's no interval to tune and nothing to remember.
//
// The operational detail (last checked, current version, whether the check is
// even working) lives beside the toggle in Site settings, not here — an admin
// looking for that goes and looks, rather than having it pushed at them.

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  useDismissUpdateNotice,
  useOperationalSettings,
} from "@/lib/hooks/use-site-settings";
import { useAccess } from "@/lib/hooks/use-permissions";

export function UpdateNotice() {
  const t = useTranslations("admin.updateNotice");
  const tCommon = useTranslations("common");
  const access = useAccess();
  // Gated on the same permission as the settings page it links to: showing a
  // "you're out of date" prompt to someone who can't act on it is noise, and
  // the running version isn't a competitor's business.
  const canManage = access.ready && access.has("manage_site_settings");
  // Gates the *query*, not just the render — this component mounts for every
  // signed-in user, and the endpoint is admin-only.
  const { data } = useOperationalSettings(canManage);
  const dismiss = useDismissUpdateNotice();

  // `update_available` is the raw fact; the dismissal is a separate flag, so
  // the settings page can keep reporting the truth while this stays quiet.
  if (
    !canManage ||
    !data?.update_available ||
    data.update_notice_dismissed ||
    !data.latest_known_version
  ) {
    return null;
  }

  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-3 border-b border-primary/30 bg-primary/10 px-4 py-2 text-sm md:px-8"
    >
      <span>
        {t.rich("available", {
          strong: (chunks) => <span className="font-medium">{chunks}</span>,
          latest: data.latest_known_version,
          current: data.current_version,
        })}
      </span>
      <span className="flex items-center gap-2">
        <a
          href="https://docs.flagpost.io/updating"
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline"
        >
          {t("howToUpdate")}
        </a>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={dismiss.isPending}
          onClick={() => dismiss.mutate()}
        >
          {tCommon("dismiss")}
        </Button>
      </span>
    </div>
  );
}
