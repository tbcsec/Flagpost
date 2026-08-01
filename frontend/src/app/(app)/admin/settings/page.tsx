"use client";

import { Suspense, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { SectionHeader } from "@/components/app/section-header";
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

const TABS: { value: Tab; label: string }[] = [
  { value: "general", label: "General" },
  { value: "email", label: "Email" },
  { value: "auth", label: "Auth" },
  { value: "rules", label: "Rules" },
  { value: "backup", label: "Backup" },
  { value: "appearance", label: "Appearance" },
  { value: "ai", label: "AI" },
];

function isFormSection(tab: Tab): tab is FormSection {
  return tab === "general" || tab === "email";
}

/** The tab named in `?tab=`, or the first one this viewer may actually see.
 *
 *  Validated against the *visible* list rather than the full one, so a
 *  hand-typed or stale `?tab=auth` can't strand someone without
 *  `manage_auth_providers` on a tab that renders nothing. */
function resolveTab(requested: string | null, visible: { value: Tab }[]): Tab {
  const match = visible.find((t) => t.value === requested);
  // `visible` is never empty here — the caller returns early when the viewer
  // holds neither permission — but fall back rather than index blindly.
  return match?.value ?? visible[0]?.value ?? "general";
}

function AdminSettingsInner() {
  const access = useAccess();
  const canManage = access.has("manage_site_settings");
  // Auth providers are a different, higher-stakes grant (§7.1) — so the tab is
  // hidden without it, and someone holding *only* it still gets into this page
  // rather than being locked out of the feature by the site-settings gate.
  const canManageAuth = access.has("manage_auth_providers");
  const settings = useOperationalSettings();
  const data = settings.data;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  if (!access.ready) return <Skeleton className="h-64 w-full" />;
  if (!canManage && !canManageAuth) {
    return (
      <>
        <SectionHeader title="Admin — Site settings" subtitle="Global — platform-wide" />
        <EmptyState title="No access" description="You need the manage-site-settings permission to change site settings." />
      </>
    );
  }

  const visibleTabs = TABS.filter((t) =>
    t.value === "auth" ? canManageAuth : canManage,
  );

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
      <SectionHeader
        title="Admin — Site settings"
        subtitle="Global — platform-wide, not scoped to a competition"
      />

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
          <h2 className="text-lg font-semibold">Rules / code of conduct</h2>
          <p className="mb-4 mt-1 text-sm text-muted-foreground">
            The site-wide document users accept before joining a competition.
          </p>
          <RulesSettingsPanel />
        </div>

        <div className={tab === "backup" ? "" : "hidden"}>
          <h2 className="text-lg font-semibold">Backup — export &amp; import</h2>
          <p className="mb-4 mt-1 text-sm text-muted-foreground">
            Move the platform&apos;s data between installs, or keep an off-site backup.
          </p>
          <BackupPanel />
        </div>

        <div className={showAppearance ? "" : "hidden"}>
          {/* Told whether it's on screen so its live theme preview stops when
              the admin looks at another tab — the panel stays mounted, so it
              can't rely on unmount to clean up. */}
          <AppearancePanel active={showAppearance} />
        </div>

        <div className={tab === "ai" ? "" : "hidden"}>
          <Card className="max-w-2xl opacity-70">
            <CardHeader>
              <CardTitle>AI assistant</CardTitle>
              <CardDescription>Not built yet — planned for a future release.</CardDescription>
            </CardHeader>
          </Card>
        </div>
      </div>
    </>
  );
}

/** The "is this actually working?" line shown beside the toggle. Deliberately
 *  states the running version even when everything is fine — "last checked N ago"
 *  alone doesn't tell an admin what they're on. */
function updateCheckStatus(data: OperationalSettings): string {
  const version = data.current_version;
  if (!data.update_checks_enabled) {
    return `Checks are off. Running version ${version}.`;
  }
  if (!data.last_update_check_at) {
    const failed = data.last_update_check_status;
    if (failed === "unreachable") {
      return `Running version ${version}. Couldn't reach the update service — that's expected on an air-gapped install.`;
    }
    if (failed === "error") {
      return `Running version ${version}. The update service responded but the answer wasn't usable.`;
    }
    return `Running version ${version}. No check has run yet — the first one happens within a minute of startup.`;
  }
  const checked = relativeTime(data.last_update_check_at);
  if (data.update_available && data.latest_known_version) {
    // Reports the fact regardless of dismissal — this is the page an admin
    // consults to find out whether they're current, so "up to date" here has to
    // mean up to date, not "you clicked Dismiss".
    const waved = data.update_notice_dismissed
      ? " You've dismissed the notice for it."
      : "";
    return `Running version ${version}. Version ${data.latest_known_version} is available.${waved} Last checked ${checked}.`;
  }
  const stale =
    data.last_update_check_status && data.last_update_check_status !== "ok"
      ? " The most recent attempt failed."
      : "";
  return `Running version ${version} — up to date. Last checked ${checked}.${stale}`;
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
        onSuccess: () => toast("Settings saved", { variant: "success" }),
        onError: (err) =>
          toast("Couldn't save", { description: (err as Error).message, variant: "destructive" }),
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
            <CardTitle>Registration</CardTitle>
            <CardDescription>
              Whether anyone can sign up. When closed, only an administrator can create accounts
              (Admin → Users).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2">
              <Label htmlFor="reg">Public sign-up</Label>
              <Select
                id="reg"
                value={registrationOpen ? "open" : "closed"}
                onChange={(e) => setRegistrationOpen(e.target.value === "open")}
                className="max-w-xs"
              >
                <option value="open">Open — anyone can register</option>
                <option value="closed">Closed — invite / admin-created only</option>
              </Select>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Update checks</CardTitle>
            <CardDescription>
              Once a day Flagpost asks{" "}
              <span className="font-mono text-xs">updates.flagpost.io</span> whether a newer
              release exists. The request sends <strong>only the version you&apos;re
              running</strong> — no identifier, no hostname, no competition or user data —
              and the count of those requests is how the project gauges how many
              deployments are live. See{" "}
              <a
                href="https://github.com/tbcsec/Flagpost/blob/main/PRIVACY.md"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline"
              >
                PRIVACY.md
              </a>{" "}
              for the full detail.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="updchk">Check for updates</Label>
              <Select
                id="updchk"
                value={updateChecks ? "on" : "off"}
                onChange={(e) => setUpdateChecks(e.target.value === "on")}
                className="max-w-xs"
              >
                <option value="on">On — check daily</option>
                <option value="off">Off — never contact the update service</option>
              </Select>
              {/* Inline with the toggle rather than in a banner: this is the
                  operational detail an admin comes looking for, and it tells
                  them the check is alive even when there's no update. */}
              <p className="text-xs text-muted-foreground">
                {updateCheckStatus(data)}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Data retention</CardTitle>
            <CardDescription>
              When on, an <em>archived</em> competition is permanently deleted — database
              records and stored files — once it has stayed archived for the retention
              period. The archive dialog shows the exact deletion date; unarchiving cancels
              the clock. Competitions archived before enabling this are never auto-deleted.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="autodel">Auto-delete archived competitions</Label>
              <Select
                id="autodel"
                value={autoDelete ? "on" : "off"}
                onChange={(e) => setAutoDelete(e.target.value === "on")}
                className="max-w-xs"
              >
                <option value="on">On — delete after the retention period</option>
                <option value="off">Off — keep archives forever</option>
              </Select>
            </div>
            {autoDelete && (
              <div className="grid gap-2">
                <Label htmlFor="retention">Retention period (days)</Label>
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
            <CardTitle>Email domain allowlist</CardTitle>
            <CardDescription>
              Restrict public sign-up to specific email domains. A rejected sign-up sees a
              generic error — it never learns which domains are allowed. Applies to public
              registration only; admin-created accounts and existing users&apos; emails are
              unaffected. Enabling this makes email mandatory at registration.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="allowlist">Restrict sign-up by email domain</Label>
              <Select
                id="allowlist"
                value={allowlistEnabled ? "on" : "off"}
                onChange={(e) => setAllowlistEnabled(e.target.value === "on")}
                className="max-w-xs"
              >
                <option value="off">Off — any email may register</option>
                <option value="on">On — only allowed domains may register</option>
              </Select>
            </div>
            {allowlistEnabled && (
              <DomainListEditor values={allowedDomains} onChange={setAllowedDomains} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Email verification</CardTitle>
            <CardDescription>
              Require a self-registered account to confirm its email (a link sent via the SMTP
              server below) before it can join a competition. Requires SMTP to be configured.
              Admin-created accounts (Admin → Users) are exempt, and turning this on never
              affects members who already joined.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2">
              <Label htmlFor="verify">Require email verification to join</Label>
              <Select
                id="verify"
                value={verificationEnabled ? "on" : "off"}
                onChange={(e) => setVerificationEnabled(e.target.value === "on")}
                className="max-w-xs"
              >
                <option value="off">Off — anyone who registers can join</option>
                <option value="on">On — must verify email first</option>
              </Select>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>SMTP (outbound email)</CardTitle>
            <CardDescription>
              Used by the automation <span className="font-mono text-xs">send_email</span> action.
              Leave the host blank to disable email (the action becomes a no-op).
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2 grid gap-2">
                <Label htmlFor="host">Host</Label>
                <Input id="host" value={host} onChange={(e) => setHost(e.target.value)} placeholder="smtp.example.com" />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="port">Port</Label>
                <Input id="port" type="number" min={1} max={65535} value={port} onChange={(e) => setPort(e.target.value)} />
              </div>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="from">From address</Label>
              <Input id="from" type="email" value={from} onChange={(e) => setFrom(e.target.value)} placeholder="ctf@example.com" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="user">Username</Label>
                <Input id="user" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="pass">Password</Label>
                <Input
                  id="pass"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  placeholder={data.smtp_password_set ? "•••••••• (unchanged)" : "Not set"}
                />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={starttls} onChange={(e) => setStarttls(e.target.checked)} />
              Use STARTTLS
            </label>
          </CardContent>
        </Card>
      </div>

      {/* Save submits the whole payload, whichever section is on screen. */}
      <div className="flex items-center gap-3">
        <Button type="submit" className="w-fit" disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save changes"}
        </Button>
        {data.updated_at && (
          <span className="text-xs text-muted-foreground">
            Last saved {new Date(data.updated_at).toLocaleString()}
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
  const [draft, setDraft] = useState("");

  function add() {
    const v = draft.trim().toLowerCase();
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  }

  return (
    <div className="space-y-2">
      <Label>Allowed domains</Label>
      <p className="text-xs text-muted-foreground">
        Subdomains are automatically allowed (e.g. an entry for{" "}
        <span className="font-mono">example.com</span> also allows{" "}
        <span className="font-mono">mail.example.com</span>).
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
                aria-label={`Remove ${v}`}
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
          placeholder="example.com"
          maxLength={253}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button type="button" variant="outline" onClick={add} disabled={!draft.trim()}>
          Add
        </Button>
      </div>
    </div>
  );
}
