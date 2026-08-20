"use client";

import { useTranslations } from "next-intl";

import { SectionHeader } from "@/components/app/section-header";
import { PagesPanel } from "@/components/admin/pages-panel";
import { EmptyState } from "@/components/ui/empty-state";
import { useAccess } from "@/lib/hooks/use-permissions";

// Custom pages authoring (#198, ADR-0034). Its own admin route rather than a
// Site-settings tab: this is content management with a list and a full editor,
// not a settings form, and `manage_pages` is a separate grant from
// `manage_site_settings` precisely so it can be delegated on its own.
export default function AdminPagesPage() {
  const t = useTranslations("pages");
  const access = useAccess();

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader title={t("heading")} subtitle={t("subtitle")} />
      {access.has("manage_pages") ? (
        <PagesPanel />
      ) : (
        <EmptyState title={t("noAccess.title")} description={t("noAccess.description")} />
      )}
    </div>
  );
}
