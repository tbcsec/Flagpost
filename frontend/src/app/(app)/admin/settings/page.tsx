"use client";

import { useTranslations } from "next-intl";
import { Suspense, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { SectionHeader } from "@/components/app/section-header";
import { AiSettingsPanel } from "@/components/admin/ai-settings-panel";
import { AppearancePanel } from "@/components/admin/appearance-panel";
import { AuthProvidersPanel } from "@/components/admin/auth-providers-panel";
import { BackupPanel } from "@/components/admin/backup-panel";
import { RulesSettingsPanel } from "@/components/admin/rules-settings-panel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { relativeTime } from "@/lib/datetime";
import { useAccess } from "@/lib/hooks/use-permissions";
import {
  useOperationalSettings,
  useUpdateOperationalSettings,
} from "@/lib/hooks/use-site-settings";
import type { OperationalSettings } from "@/lib/types";
import { toast } from "@/stores/toast";

// Admin → Site settings. Every site-wide (non-competition) setting, grouped into
// tabs (#104): registration + retention, outbound email, the rules document,
// backup, theming, and the deferred AI placeholder. Gated on
// manage_site_settings.
//
// Following the Competition Settings precedent, panels stay **mounted** and are
// toggled with `hidden` rather than conditionally rendered, so an unsaved edit
// in one tab survives a look at another.
type Tab = "general" | "email" | "auth" | "rules" | "backup" | "appearance" | "ai";

/** The two tabs that are views of the one settings form. */
type FormSection = Extract<Tab, "general" | "email">;

const TAB_ORDER: Tab[] = ["general", "email", "auth", "rules", "backup", "appearance", "ai"];

/** Tab → message key in the admin.settings namespace. */
const TAB_KEY: Record<Tab, "tabGeneral" | "tabEmail" | "tabAuth" | "tabRules" | "tabBackup" | "tabAppearance" | "tabAi"> = {
  general: "tabGeneral",
  email: "tabEmail",
  auth: "tabAuth",
  rules: "tabRules",
  backup: "tabBackup",
  appearance: "tabAppearance",
  ai: "tabAi",
};

function isFormSection(tab: Tab): tab is FormSection {
  return tab === "general" || tab === "email";
}

/** The tab named in `?tab=`, or the first one this viewer may actually see.
 *
 *  Validated against the *visible* list rather than the full one, so a
 *  hand-typed or stale `?tab=auth` can't strand someone without
 *  `manage_auth_providers` on a tab that renders nothing. */
function resolveTab(requested: string | null, visible: { value: Tab }[]): Tab {
  const match = visible.find((tab) => tab.value === requested);
  // `visible` is never empty here — the caller returns early when the viewer
  // holds neither permission — but fall back rather than index blindly.
  return match?.value ?? visible[0]?.value ?? "general";
}

function AdminSettingsInner() {
  const t = useTranslations("admin.settings");
  const access = useAccess();
  const canManage = access.has("manage_site_settings");
  // Auth providers are a different, higher-stakes grant (§7.1) — so the tab is
  // hidden without it, and someone holding *only* it still gets into this page
  // rather than being locked out of the feature by the site-settings gate.
  const canManageAuth = access.has("manage_auth_providers");
  // AI provider config is its own grant too (holds an API key + enables
  // outbound calls) — same higher-stakes treatment as auth providers.
  const canManageAi = access.has("manage_ai");
  const settings = useOperationalSettings();
  const data = settings.data;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  if (!access.ready) return <Skeleton className="h-64 w-full" />;
  if (!canManage && !canManageAuth && !canManageAi) {
    return (
      <>
        <SectionHeader title={t("title")} subtitle={t("subtitleShort")} />
        <EmptyState title={t("noAccessTitle")} description={t("noAccessDescription")} />
      </>
    );
  }

  const visibleTabs = TAB_ORDER.filter((value) => {
    if (value === "auth") return canManageAuth;
    if (value === "ai") return canManageAi;
    return canManage;
  }).map((value) => ({ value, label: t(TAB_KEY[value]) }));

  // Everything below is derived *after* the permission guards, which is the fix
  // for #126. The tab used to be `useState(canManage ? "general" : "auth")`, and
  // useState only reads its argument on the first render — at which point the
  // permissions query hasn't resolved and every flag is conservatively false. So
  // a refresh always initialised to "auth" and nothing reset it. Deriving the
  // value here means it can't be computed from data that hasn't arrived yet.
  const tab = resolveTab(searchParams.get("tab"), visibleTabs);

  function setTab(next: Tab) {
    // push, not replace: the URL is the state, so Back should undo a tab switch
    // the way a user expects. scroll:false stops a long tab jumping to the top.
    const query = new URLSearchParams(searchParams.toString());
    query.set("tab", next);
    router.push(`${pathname}?${query}`, { scroll: false });
  }

  // Derived once and reused, so the panel's visibility and the `active` it is
  // told about can never disagree — the theme preview writes to <html>, and a
  // drift between the two would leak an unsaved palette across the whole UI.
  const showAppearance = tab === "appearance";
  // The form spans two tabs, so the section is just whichever of them is
  // showing. On a non-form tab the whole form is hidden, so the fallback is
  // never seen.
  const formSection: FormSection = isFormSection(tab) ? tab : "general";

  return (
    <>
      <SectionHeader title={t("title")} subtitle={t("subtitle")} />

      <Tabs tabs={visibleTabs} value={tab} onValueChange={(v) => setTab(v as Tab)} />

      <div className="mt-6">
        <div className={isFormSection(tab) && canManage ? "" : "hidden"}>
          {settings.isLoading || !data ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            // Keyed by the row's save timestamp: a successful save refetches and
            // remounts the form seeded with the canonical server values (and a
            // cleared write-only password field) — the old sync-on-data effect,
            // without the effect.
            <SettingsForm
              key={data.updated_at ?? "initial"}
              data={data}
              section={formSection}
              onShowSection={setTab}
            />
          )}
        </div>

        {canManageAuth && (
          <div className={tab === "auth" ? "" : "hidden"}>
            <AuthProvidersPanel />
          </div>
        )}

        <div className={tab === "rules" ? "max-w-2xl" : "hidden"}>
          <h2 className="text-lg font-semibold">{t("rulesHeading")}</h2>
          <p className="mb-4 mt-1 text-sm text-muted-foreground">
            {t("rulesHeadingDescription")}
          </p>
          <RulesSettingsPanel />
        </div>

        <div className={tab === "backup" ? "" : "hidden"}>
          <h2 className="text-lg font-semibold">{t("backupHeading")}</h2>
          <p className="mb-4 mt-1 text-sm text-muted-foreground">
            {t("backupHeadingDescription")}
          </p>
          <BackupPanel />
        </div>

        <div className={showAppearance ? "" : "hidden"}>
          {/* Told whether it's on screen so its live theme preview stops when
              the admin looks at another tab — the panel stays mounted, so it
              can't rely on unmount to clean up. */}
          <AppearancePanel active={showAppearance} />
        </div>

        {canManageAi && (
          <div className={tab === "ai" ? "" : "hidden"}>
            <h2 className="text-lg font-semibold">{t("aiHeading")}</h2>
            <p className="mb-4 mt-1 text-sm text-muted-foreground">
              {t("aiHeadingDescription")}
            </p>
            <AiSettingsPanel />
          </div>
        )}
      </div>
    </>
  );
}

/** Call `reportValidity()` once `field` is on screen, or give up after ~20
 *  frames. Polls visibility instead of racing a fixed timeout: the browser
 *  silently declines to show a validation bubble on a control it can't focus,
 *  so firing early makes Save look inert — the very thing this avoids. */
function reportWhenVisible(
  form: HTMLFormElement,
  field: HTMLElement,
  attempts = 20,
): void {
  // offsetParent is null while an ancestor is `display: none` — which is how
  // the inactive tab panel is hidden.
  if (field.offsetParent !== null || attempts === 0) {
    form.reportValidity();
    return;
  }
  requestAnimationFrame(() => reportWhenVisible(form, field, attempts - 1));
}

/** `useSearchParams` needs a Suspense boundary or Next refuses to prerender the
 *  route — the build fails outright rather than degrading. */
export default function AdminSettingsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <AdminSettingsInner />
    </Suspense>
  );
}

// One form, one PUT, two views of it. Both sections stay mounted (toggled with
// `hidden`) rather than being conditionally rendered, for two reasons: card-local
// state like DomainListEditor's draft survives a tab switch, and — the important
// one — the browser only applies constraint validation to *mounted* controls, so
// unmounting would let an invalid From address or port typed on the tab you
// aren't looking at go to the server unchecked. `smtp_from` in particular is only
// format-checked here; the API validates its length, not that it's an address.
function SettingsForm({
  data,
  section,
  onShowSection,
}: {
  data: OperationalSettings;
  section: FormSection;
  onShowSection: (section: FormSection) => void;
}) {
  const t = useTranslations("admin.settings");
  const update = useUpdateOperationalSettings();
  const [registrationOpen, setRegistrationOpen] = useState(data.registration_open);
  const [updateChecks, setUpdateChecks] = useState(data.update_checks_enabled);
  const [host, setHost] = useState(data.smtp_host ?? "");
  const [port, setPort] = useState(String(data.smtp_port));
  const [from, setFrom] = useState(data.smtp_from);
  const [username, setUsername] = useState(data.smtp_username ?? "");
  const [password, setPassword] = useState("");
  const [starttls, setStarttls] = useState(data.smtp_starttls);
  const [autoDelete, setAutoDelete] = useState(data.archive_auto_delete);
  const [retentionDays, setRetentionDays] = useState(String(data.archive_retention_days));
  const [allowlistEnabled, setAllowlistEnabled] = useState(
    data.email_domain_allowlist_enabled,
  );
  const [allowedDomains, setAllowedDomains] = useState(data.allowed_email_domains);
  const [verificationEnabled, setVerificationEnabled] = useState(
    data.email_verification_enabled,
  );

  // The "is this actually working?" line beside the update-check toggle.
  // Deliberately states the running version even when all is well — "last
  // checked N ago" alone doesn't tell an admin what they're on.
  function updateCheckStatus(): string {
    const version = data.current_version;
    if (!data.update_checks_enabled) return t("updateOff", { version });
    if (!data.last_update_check_at) {
      const failed = data.last_update_check_status;
      if (failed === "unreachable") return t("updateUnreachable", { version });
      if (failed === "error") return t("updateError", { version });
      return t("updateNever", { version });
    }
    const checked = relativeTime(data.last_update_check_at);
    if (data.update_available && data.latest_known_version) {
      // Reports the fact regardless of dismissal — this is where an admin
      // checks whether they're current, so it must mean up to date, not
      // "you clicked Dismiss".
      const params = { version, latest: data.latest_known_version, checked };
      return data.update_notice_dismissed
        ? t("updateAvailableDismissed", params)
        : t("updateAvailable", params);
    }
    const stale = data.last_update_check_status && data.last_update_check_status !== "ok";
    return stale
      ? t("updateCurrentStale", { version, checked })
      : t("updateCurrent", { version, checked });
  }

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;

    // Validation is driven from here (the form carries `noValidate`) rather than
    // left to the browser. Both sections stay mounted, so the control blocking
    // submit may sit on the tab the admin *isn't* looking at — and the browser
    // refuses to submit on an invalid field it can't focus, without showing its
    // message, so Save would simply look inert. Taking over lets us reveal the
    // offending section first and then point at the field.
    if (!form.checkValidity()) {
      const invalid = form.querySelector<HTMLElement>(":invalid");
      const owner = invalid?.closest<HTMLElement>("[data-section]")?.dataset.section;
      if ((owner === "general" || owner === "email") && owner !== section) {
        onShowSection(owner);
        // Wait for the field to actually become visible rather than guessing a
        // delay. Showing a section is a router navigation now (#126 put the tab
        // in the URL), so it isn't guaranteed to land within one tick the way a
        // setState was — and reportValidity() on a still-hidden control shows
        // nothing at all, which is the exact failure this branch exists to
        // avoid.
        reportWhenVisible(form, invalid!);
      } else {
        form.reportValidity();
      }
      return;
    }

    update.mutate(
      {
        registration_open: registrationOpen,
        smtp_host: host.trim() || null,
        smtp_port: Number(port) || 587,
        smtp_username: username.trim() || null,
        smtp_from: from.trim() || "flagpost@localhost",
        smtp_starttls: starttls,
        // Only send a password when the admin typed a new one (write-only).
        ...(password ? { smtp_password: password } : {}),
        archive_auto_delete: autoDelete,
        archive_retention_days: Math.min(3650, Math.max(1, Number(retentionDays) || 30)),
        email_domain_allowlist_enabled: allowlistEnabled,
        allowed_email_domains: allowedDomains,
        email_verification_enabled: verificationEnabled,
        update_checks_enabled: updateChecks,
      },
      {
        onSuccess: () => toast(t("settingsSaved"), { variant: "success" }),
        onError: (err) =>
          toast(t("couldntSave"), { description: (err as Error).message, variant: "destructive" }),
      },
    );
  }

  // `noValidate`: onSubmit runs the same constraint checks itself, so it can
  // reveal a field on the other tab rather than let the browser silently refuse
  // to submit on a control it can't focus (see onSubmit).
  return (
    <form onSubmit={onSubmit} noValidate className="grid max-w-2xl gap-5">
      <div
        data-section="general"
        className={section === "general" ? "grid gap-5" : "hidden"}
      >
        <Card>
          <CardHeader>
            <CardTitle>{t("registration")}</CardTitle>
            <CardDescription>{t("registrationDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2">
              <Label htmlFor="reg">{t("publicSignup")}</Label>
              <Select
                id="reg"
                value={registrationOpen ? "open" : "closed"}
                onChange={(e) => setRegistrationOpen(e.target.value === "open")}
                className="max-w-xs"
              >
                <option value="open">{t("signupOpen")}</option>
                <option value="closed">{t("signupClosed")}</option>
              </Select>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("updateChecks")}</CardTitle>
            <CardDescription>
              {t.rich("updateChecksDescription", {
                mono: (chunks) => <span className="font-mono text-xs">{chunks}</span>,
                strong: (chunks) => <strong>{chunks}</strong>,
                link: (chunks) => (
                  <a
                    href="https://github.com/tbcsec/Flagpost/blob/main/PRIVACY.md"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    {chunks}
                  </a>
                ),
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="updchk">{t("checkForUpdates")}</Label>
              <Select
                id="updchk"
                value={updateChecks ? "on" : "off"}
                onChange={(e) => setUpdateChecks(e.target.value === "on")}
                className="max-w-xs"
              >
                <option value="on">{t("updatesOn")}</option>
                <option value="off">{t("updatesOff")}</option>
              </Select>
              {/* Inline with the toggle rather than in a banner: this is the
                  operational detail an admin comes looking for, and it tells
                  them the check is alive even when there's no update. */}
              <p className="text-xs text-muted-foreground">
                {updateCheckStatus()}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("dataRetention")}</CardTitle>
            <CardDescription>
              {t.rich("dataRetentionDescription", {
                em: (chunks) => <em>{chunks}</em>,
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="autodel">{t("autoDeleteLabel")}</Label>
              <Select
                id="autodel"
                value={autoDelete ? "on" : "off"}
                onChange={(e) => setAutoDelete(e.target.value === "on")}
                className="max-w-xs"
              >
                <option value="on">{t("autoDeleteOn")}</option>
                <option value="off">{t("autoDeleteOff")}</option>
              </Select>
            </div>
            {autoDelete && (
              <div className="grid gap-2">
                <Label htmlFor="retention">{t("retentionPeriod")}</Label>
                <Input
                  id="retention"
                  type="number"
                  min={1}
                  max={3650}
                  value={retentionDays}
                  onChange={(e) => setRetentionDays(e.target.value)}
                  className="max-w-32"
                />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div
        data-section="email"
        className={section === "email" ? "grid gap-5" : "hidden"}
      >
        <Card>
          <CardHeader>
            <CardTitle>{t("emailAllowlist")}</CardTitle>
            <CardDescription>{t("emailAllowlistDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="allowlist">{t("restrictSignup")}</Label>
              <Select
                id="allowlist"
                value={allowlistEnabled ? "on" : "off"}
                onChange={(e) => setAllowlistEnabled(e.target.value === "on")}
                className="max-w-xs"
              >
                <option value="off">{t("allowlistOff")}</option>
                <option value="on">{t("allowlistOn")}</option>
              </Select>
            </div>
            {allowlistEnabled && (
              <DomainListEditor values={allowedDomains} onChange={setAllowedDomains} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("emailVerification")}</CardTitle>
            <CardDescription>{t("emailVerificationDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2">
              <Label htmlFor="verify">{t("requireVerification")}</Label>
              <Select
                id="verify"
                value={verificationEnabled ? "on" : "off"}
                onChange={(e) => setVerificationEnabled(e.target.value === "on")}
                className="max-w-xs"
              >
                <option value="off">{t("verificationOff")}</option>
                <option value="on">{t("verificationOn")}</option>
              </Select>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("smtp")}</CardTitle>
            <CardDescription>
              {t.rich("smtpDescription", {
                mono: (chunks) => <span className="font-mono text-xs">{chunks}</span>,
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2 grid gap-2">
                <Label htmlFor="host">{t("host")}</Label>
                <Input id="host" value={host} onChange={(e) => setHost(e.target.value)} placeholder="smtp.example.com" />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="port">{t("port")}</Label>
                <Input id="port" type="number" min={1} max={65535} value={port} onChange={(e) => setPort(e.target.value)} />
              </div>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="from">{t("fromAddress")}</Label>
              <Input id="from" type="email" value={from} onChange={(e) => setFrom(e.target.value)} placeholder="ctf@example.com" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="user">{t("username")}</Label>
                <Input id="user" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="pass">{t("password")}</Label>
                <Input
                  id="pass"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  placeholder={data.smtp_password_set ? t("passwordUnchanged") : t("passwordNotSet")}
                />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={starttls} onChange={(e) => setStarttls(e.target.checked)} />
              {t("useStarttls")}
            </label>
          </CardContent>
        </Card>
      </div>

      {/* Save submits the whole payload, whichever section is on screen. */}
      <div className="flex items-center gap-3">
        <Button type="submit" className="w-fit" disabled={update.isPending}>
          {update.isPending ? t("saving") : t("saveChanges")}
        </Button>
        {data.updated_at && (
          <span className="text-xs text-muted-foreground">
            {t("lastSaved", { time: new Date(data.updated_at).toLocaleString() })}
          </span>
        )}
      </div>
    </form>
  );
}

// Tag-input pattern matching VocabEditor (competition-settings-form.tsx) for
// consistency across the admin UI — a small local component since that one
// isn't exported/shared.
function DomainListEditor({
  values,
  onChange,
}: {
  values: string[];
  onChange: (values: string[]) => void;
}) {
  const t = useTranslations("admin.settings");
  const [draft, setDraft] = useState("");

  function add() {
    const v = draft.trim().toLowerCase();
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  }

  return (
    <div className="space-y-2">
      <Label>{t("allowedDomains")}</Label>
      <p className="text-xs text-muted-foreground">
        {t.rich("subdomainsHint", {
          mono: (chunks) => <span className="font-mono">{chunks}</span>,
        })}
      </p>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((v) => (
            <span
              key={v}
              className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-0.5 text-xs"
            >
              {v}
              <button
                type="button"
                onClick={() => onChange(values.filter((x) => x !== v))}
                className="text-muted-foreground hover:text-destructive"
                aria-label={t("removeDomainAria", { domain: v })}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("domainPlaceholder")}
          maxLength={253}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button type="button" variant="outline" onClick={add} disabled={!draft.trim()}>
          {t("addDomain")}
        </Button>
      </div>
    </div>
  );
}
