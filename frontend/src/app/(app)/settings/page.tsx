"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { AiCompetitionPanel } from "@/components/ai/ai-competition-panel";
import { NoCompetition } from "@/components/app/no-competition";
import { CertificateDesigner } from "@/components/certificates/certificate-designer";
import { SectionHeader } from "@/components/app/section-header";
import { CategoryManager } from "@/components/challenges/challenge-admin";
import {
  CompetitionSettingsForm,
  type SettingsSection,
} from "@/components/competitions/competition-settings-form";
import { ModulesPanel } from "@/components/competitions/modules-panel";
import { ReportsPanel } from "@/components/reports/reports-panel";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useEnabledModules } from "@/lib/hooks/use-modules";
import { useAccess } from "@/lib/hooks/use-permissions";

type Tab =
  | SettingsSection
  | "modules"
  | "assistant"
  | "certificates"
  | "reports";

// Tab order; labels resolve at render via the settings namespace, except
// "reports", which resolves via its own module namespace (t("reports.tab")).
const TAB_ORDER: Tab[] = [
  "general",
  "schedule",
  "challenges",
  "rules",
  "assistant",
  "certificates",
  "reports",
  "modules",
];

// Competition settings (ROADMAP #6), scoped to the active competition and split
// into tabs by category. The settings form stays mounted across the non-module
// tabs (kept hidden, not unmounted) so switching tabs never drops an unsaved edit;
// Modules (§11.3, per-competition feature toggles) is its own tab.
//
// Switching *competitions* is the opposite contract (#258): every panel below
// holds per-competition local state seeded from props at mount, so the content
// is keyed by competition id — a switch remounts it all and drafts re-derive
// from the newly active competition. Without the key, React reconciles the same
// components in place and competition A's unsaved edits survive into B, where
// Save would write them across tenants. The tab selection lives above the key
// and deliberately survives the switch.
export default function CompetitionSettingsPage() {
  const t = useTranslations("settings");
  const tReports = useTranslations("reports");
  const { competitionId, data, isLoading, isError, error } = useActiveCompetition();
  const [tab, setTab] = useState<Tab>("general");
  // The Assistant tab only exists while the ai module is enabled here — with it
  // off, nothing on the tab would work (§11.3, same treatment as the nav).
  const enabledModules = useEnabledModules(competitionId ?? "", Boolean(competitionId));
  const aiEnabled = !enabledModules.data || enabledModules.data.includes("ai");
  // The Certificates tab, like Assistant, only exists while its module is on here
  // and the manager holds manage_certificates (#219, §11.3).
  const certificatesEnabled =
    !enabledModules.data || enabledModules.data.includes("certificates");
  const access = useAccess();
  // The Modules tab needs its own permission (#168) — hide it for a manager who
  // can edit settings but wasn't granted module management.
  const canManageModules = access.has("manage_modules");
  const canManageCertificates = access.has("manage_certificates");
  const certTabOn = certificatesEnabled && canManageCertificates;
  // The Reports tab, like Certificates, needs the module on here and the
  // generate_report grant (#134, §11.3).
  const reportsEnabled =
    !enabledModules.data || enabledModules.data.includes("reports");
  const reportsTabOn = reportsEnabled && access.has("generate_report");
  const visibleTabs = TAB_ORDER.filter(
    (value) =>
      (value !== "assistant" || aiEnabled) &&
      (value !== "certificates" || certTabOn) &&
      (value !== "reports" || reportsTabOn) &&
      (value !== "modules" || canManageModules),
  ).map((value) => ({
    value,
    label: value === "reports" ? tReports("tab") : t(`tabs.${value}`),
  }));
  const activeTab: Tab =
    (tab === "assistant" && !aiEnabled) ||
    (tab === "certificates" && !certTabOn) ||
    (tab === "reports" && !reportsTabOn) ||
    (tab === "modules" && !canManageModules)
      ? "general"
      : tab;

  if (!competitionId) {
    return <NoCompetition />;
  }

  // The settings form hosts the general/schedule/challenges/rules sections;
  // assistant + certificates + modules are their own panels (own endpoints).
  const isFormTab =
    activeTab !== "modules" &&
    activeTab !== "assistant" &&
    activeTab !== "certificates" &&
    activeTab !== "reports";

  return (
    <>
      <SectionHeader title={t("title")} subtitle={data?.name} />
      {isLoading && <p className="text-sm text-muted-foreground">{t("loading")}</p>}
      {isError && <p role="alert" className="text-sm text-destructive">{(error as Error).message}</p>}
      {data && (
        // key: remount everything per competition — see the header comment (#258).
        <div key={competitionId} className="grid gap-6">
          <Tabs tabs={visibleTabs} value={activeTab} onValueChange={(v) => setTab(v as Tab)} />

          <div className={isFormTab ? "" : "hidden"}>
            <Card>
              <CardContent className="pt-6">
                <CompetitionSettingsForm
                  competition={data}
                  section={isFormTab ? (activeTab as SettingsSection) : "general"}
                />
              </CardContent>
            </Card>
          </div>

          {/* Categories live in their own card (own CRUD endpoints) under the
              Challenges tab, alongside the tag/difficulty vocab for uniformity. */}
          <div className={activeTab === "challenges" ? "" : "hidden"}>
            <CategoryManager competitionId={competitionId} />
          </div>

          {/* Mounted only when shown (unlike the form) — it has no cross-tab
              unsaved state to preserve, and its queries then run on demand. */}
          {activeTab === "assistant" && (
            <AiCompetitionPanel competitionId={competitionId} />
          )}

          {/* Certificate designer — mounted only when shown (own queries). */}
          {activeTab === "certificates" && (
            <Card>
              <CardContent className="pt-6">
                <CertificateDesigner competitionId={competitionId} />
              </CardContent>
            </Card>
          )}

          {/* Post-event reports (#134) — mounted only when shown (own queries). */}
          {activeTab === "reports" && (
            <Card>
              <CardContent className="pt-6">
                <ReportsPanel competitionId={competitionId} status={data.status} />
              </CardContent>
            </Card>
          )}

          <div className={activeTab === "modules" ? "grid gap-3" : "hidden"}>
            <p className="text-sm text-muted-foreground">{t("modulesIntro")}</p>
            <ModulesPanel competitionId={competitionId} />
          </div>
        </div>
      )}
    </>
  );
}
