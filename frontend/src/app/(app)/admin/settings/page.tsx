"use client";

import { useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { BackupPanel } from "@/components/admin/backup-panel";
import { RulesSettingsPanel } from "@/components/admin/rules-settings-panel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useAccess } from "@/lib/hooks/use-permissions";
import {
  useOperationalSettings,
  useUpdateOperationalSettings,
} from "@/lib/hooks/use-site-settings";
import type { OperationalSettings } from "@/lib/types";
import { toast } from "@/stores/toast";

// Admin → Site settings. The operational (non-theming) site config: the public
// registration policy and the SMTP server the send_email automation action uses.
// Theming lives on Admin → Appearance; AI/SSO are deferred. Gated on
// manage_site_settings.
export default function AdminSettingsPage() {
  const access = useAccess();
  const canManage = access.has("manage_site_settings");
  const settings = useOperationalSettings();
  const data = settings.data;

  if (!access.ready) return <Skeleton className="h-64 w-full" />;
  if (!canManage) {
    return (
      <>
        <SectionHeader title="Admin — Site settings" subtitle="Global — platform-wide" />
        <EmptyState title="No access" description="You need the manage-site-settings permission to change site settings." />
      </>
    );
  }

  return (
    <>
      <SectionHeader title="Admin — Site settings" subtitle="Global — registration policy & outbound email" />

      {settings.isLoading || !data ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        // Keyed by the row's save timestamp: a successful save refetches and
        // remounts the form seeded with the canonical server values (and a
        // cleared write-only password field) — the old sync-on-data effect,
        // without the effect.
        <SettingsForm key={data.updated_at ?? "initial"} data={data} />
      )}

      <div className="mt-8 grid gap-1">
        <h2 className="text-lg font-semibold">Rules / code of conduct</h2>
        <p className="text-sm text-muted-foreground">
          The site-wide document users accept before joining a competition.
        </p>
      </div>
      <div className="mt-4 max-w-2xl">
        <RulesSettingsPanel />
      </div>

      <div className="mt-8 grid gap-1">
        <h2 className="text-lg font-semibold">Backup — export &amp; import</h2>
        <p className="text-sm text-muted-foreground">
          Move the platform&apos;s data between installs, or keep an off-site backup.
        </p>
      </div>
      <div className="mt-4">
        <BackupPanel />
      </div>
    </>
  );
}

function SettingsForm({ data }: { data: OperationalSettings }) {
  const update = useUpdateOperationalSettings();
  const [registrationOpen, setRegistrationOpen] = useState(data.registration_open);
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

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
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
      },
      {
        onSuccess: () => toast("Settings saved", { variant: "success" }),
        onError: (err) =>
          toast("Couldn't save", { description: (err as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <form onSubmit={onSubmit} className="grid max-w-2xl gap-5">
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

          <Card className="opacity-70">
            <CardHeader>
              <CardTitle>AI assistant</CardTitle>
              <CardDescription>Deferred past MVP — not configurable yet.</CardDescription>
            </CardHeader>
          </Card>

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
