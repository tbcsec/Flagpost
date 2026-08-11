"use client";

// Admin → Site settings → Auth (#58/#100/#101, ADR-0021, ADR-0022). Configure
// external identity providers — OIDC and SAML get a login-page button; LDAP
// plugs into the ordinary username/password form and gets no button at all.
//
// A panel rather than its own route: it's a tab of Site settings, mounted
// alongside the others. Note it's gated on `manage_auth_providers`, *not* the
// `manage_site_settings` the rest of that page needs — who can sign in is a
// higher-stakes surface than a palette (§7.1) — so the page shows this tab only
// to holders of that permission.
//
// The secret (OIDC client secret; SAML SP private key; LDAP bind password) is
// write-only: the API only ever tells us whether one is stored, so the edit
// form leaves its field blank and omitting it preserves what's saved. That
// mirrors the SMTP password.

import { useState } from "react";

import { SsoBrandIcon } from "@/components/brand/sso-brand-icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  useAdminAuthProviders,
  useCreateAuthProvider,
  useDeleteAuthProvider,
  useProviderPresets,
  useUpdateAuthProvider,
} from "@/lib/hooks/use-users";
import {
  presetToFormPrefill,
  setupLinkLabel,
  validatePresetParam,
} from "@/lib/sso-presets";
import type { AuthProvider, ProviderPreset } from "@/lib/types";
import { toast } from "@/stores/toast";

type Kind = "oidc" | "saml" | "ldap";

interface FormState {
  kind: Kind;
  name: string;
  slug: string;
  posture: "open" | "closed";
  email_is_authoritative: boolean;
  // Write-only: OIDC client secret, SAML SP private key (PEM), or LDAP bind
  // password.
  secret: string;
  // OIDC
  issuer: string;
  client_id: string;
  scopes: string;
  // SAML
  idp_entity_id: string;
  idp_sso_url: string;
  idp_x509_cert: string;
  sp_entity_id: string;
  sp_x509_cert: string;
  // SAML + LDAP (per-kind defaults: "email"/"mail")
  email_attribute: string;
  name_attribute: string;
  // LDAP
  server_url: string;
  use_starttls: boolean;
  bind_dn: string;
  base_dn: string;
  search_attribute: string;
  subject_attribute: string;
}

const EMPTY: FormState = {
  kind: "oidc",
  name: "",
  slug: "",
  posture: "open",
  email_is_authoritative: false,
  secret: "",
  issuer: "",
  client_id: "",
  scopes: "openid email profile",
  idp_entity_id: "",
  idp_sso_url: "",
  idp_x509_cert: "",
  sp_entity_id: "",
  sp_x509_cert: "",
  email_attribute: "email",
  name_attribute: "displayName",
  server_url: "",
  use_starttls: false,
  bind_dn: "",
  base_dn: "",
  search_attribute: "uid",
  subject_attribute: "entryUUID",
};

/** Config values are string | boolean | null; the string fields of the form
 *  want strings. */
function str(v: string | boolean | null | undefined, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

function fromEditing(p: AuthProvider): FormState {
  const c = p.config;
  return {
    kind: p.kind as Kind,
    name: p.name,
    slug: p.slug,
    posture: p.posture,
    email_is_authoritative: p.email_is_authoritative,
    secret: "", // never returned; blank means "leave unchanged"
    issuer: str(c.issuer),
    client_id: str(c.client_id),
    scopes: str(c.scopes, "openid email profile"),
    idp_entity_id: str(c.idp_entity_id),
    idp_sso_url: str(c.idp_sso_url),
    idp_x509_cert: str(c.idp_x509_cert),
    sp_entity_id: str(c.sp_entity_id),
    sp_x509_cert: str(c.sp_x509_cert),
    email_attribute: str(c.email_attribute, p.kind === "ldap" ? "mail" : "email"),
    name_attribute: str(c.name_attribute, "displayName"),
    server_url: str(c.server_url),
    use_starttls: c.use_starttls === true,
    bind_dn: str(c.bind_dn),
    base_dn: str(c.base_dn),
    search_attribute: str(c.search_attribute, "uid"),
    subject_attribute: str(c.subject_attribute, "entryUUID"),
  };
}

/** Multi-line field for PEM certs/keys — no Textarea primitive exists yet, so
 *  this borrows the Input token styling. */
const TEXTAREA_CLASS =
  "flex min-h-[88px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

function ProviderForm({
  editing,
  prefill = null,
  onDone,
}: {
  editing: AuthProvider | null;
  /** Seeds the create form from a quick-setup preset (presetToFormPrefill).
   *  Same FormState shape, so the admin edits and submits exactly as if they'd
   *  typed it — a preset is prefill, not a second write path. */
  prefill?: Partial<FormState> | null;
  onDone: () => void;
}) {
  const create = useCreateAuthProvider();
  const update = useUpdateAuthProvider();
  const [form, setForm] = useState<FormState>(
    editing ? fromEditing(editing) : prefill ? { ...EMPTY, ...prefill } : EMPTY,
  );
  const pending = create.isPending || update.isPending;
  const error = (create.error ?? update.error) as Error | null;
  const isSaml = form.kind === "saml";
  const isLdap = form.kind === "ldap";

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const config: Record<string, string | boolean | null> = isLdap
      ? {
          server_url: form.server_url,
          use_starttls: form.use_starttls,
          bind_dn: form.bind_dn,
          base_dn: form.base_dn,
          search_attribute: form.search_attribute,
          subject_attribute: form.subject_attribute,
          email_attribute: form.email_attribute || null,
          name_attribute: form.name_attribute || null,
        }
      : isSaml
        ? {
            idp_entity_id: form.idp_entity_id,
            idp_sso_url: form.idp_sso_url,
            idp_x509_cert: form.idp_x509_cert,
            sp_entity_id: form.sp_entity_id,
            sp_x509_cert: form.sp_x509_cert || null,
            email_attribute: form.email_attribute,
            name_attribute: form.name_attribute,
          }
        : {
            issuer: form.issuer,
            client_id: form.client_id,
            scopes: form.scopes,
          };
    // SAML/LDAP are always closed (the API enforces it). For OIDC the admin
    // chooses. email_is_authoritative only means something for a closed
    // directory, so switching a provider to open clears it rather than 400ing.
    const posture = form.kind === "oidc" ? form.posture : "closed";
    const email_is_authoritative =
      posture === "closed" && form.email_is_authoritative;

    if (editing) {
      update.mutate(
        {
          id: editing.id,
          name: form.name,
          config,
          posture,
          email_is_authoritative,
          // Omitted entirely when blank, so an edit never wipes a stored secret.
          ...(form.secret ? { secret: form.secret } : {}),
        },
        {
          onSuccess: () => {
            toast("Provider updated", { variant: "success" });
            onDone();
          },
        },
      );
    } else {
      create.mutate(
        {
          kind: form.kind,
          name: form.name,
          slug: form.slug,
          config,
          posture,
          email_is_authoritative,
          secret: form.secret || null,
          enabled: false,
        },
        {
          onSuccess: () => {
            toast("Provider added — enable it when you've tested it", {
              variant: "success",
            });
            onDone();
          },
        },
      );
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{editing ? `Edit ${editing.name}` : "Add a provider"}</CardTitle>
        <CardDescription>
          {isLdap
            ? "Point Flagpost at your directory. Directory users sign in with the ordinary username & password form — no separate button appears. New providers start disabled."
            : isSaml
              ? "Register Flagpost as a Service Provider at your IdP (its metadata is at the SP metadata URL below once saved), then paste the IdP's details here. New providers start disabled."
              : "Register Flagpost as an OAuth client at your provider first, then paste its details here. New providers start disabled."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid max-w-xl gap-4">
          {!editing && (
            <div className="grid gap-2">
              <Label htmlFor="ap-kind">Protocol</Label>
              <Select
                id="ap-kind"
                value={form.kind}
                onChange={(e) => {
                  const kind = e.target.value as Kind;
                  // Each protocol has its own conventional attribute names, so
                  // switching kind resets them to that kind's defaults.
                  setForm((f) => ({
                    ...f,
                    kind,
                    email_attribute: kind === "ldap" ? "mail" : "email",
                    name_attribute: "displayName",
                  }));
                }}
              >
                <option value="oidc">OpenID Connect (OAuth2)</option>
                <option value="saml">SAML 2.0</option>
                <option value="ldap">LDAP / Active Directory</option>
              </Select>
              <p className="text-xs text-muted-foreground">
                Fixed after creation. SAML suits campus/enterprise IdPs
                (Shibboleth, ADFS); OIDC suits most modern providers; LDAP binds
                directly against a directory (AD, OpenLDAP, FreeIPA).
              </p>
            </div>
          )}

          <div className="grid gap-2">
            <Label htmlFor="ap-name">Display name</Label>
            <Input
              id="ap-name"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="Company SSO"
              required
            />
            <p className="text-xs text-muted-foreground">
              {isLdap
                ? "Shown in the admin list — LDAP has no login button."
                : `Shown on the login button: “Sign in with ${form.name || "…"}”.`}
            </p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="ap-slug">Slug</Label>
            <Input
              id="ap-slug"
              value={form.slug}
              onChange={(e) => set("slug", e.target.value.toLowerCase())}
              placeholder="company-sso"
              pattern="[a-z0-9][a-z0-9-]*[a-z0-9]"
              required
              disabled={!!editing}
            />
            <p className="text-xs text-muted-foreground">
              {editing
                ? "Fixed after creation — it's part of the URLs registered at your provider."
                : "Lowercase letters, numbers and hyphens. Appears in the callback/ACS URL."}
            </p>
          </div>

          {isLdap ? (
            <>
              <div className="grid gap-2">
                <Label htmlFor="ap-ldap-url">Server URL</Label>
                <Input
                  id="ap-ldap-url"
                  value={form.server_url}
                  onChange={(e) => set("server_url", e.target.value)}
                  placeholder="ldaps://directory.example.com"
                  pattern="ldaps?://.*"
                  required
                />
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={form.use_starttls}
                    onChange={(e) => set("use_starttls", e.target.checked)}
                    style={{ accentColor: "hsl(var(--primary))" }}
                  />
                  Upgrade with StartTLS (required for ldap:// — a plaintext
                  connection is never used)
                </label>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-ldap-bind">Service account (bind DN)</Label>
                <Input
                  id="ap-ldap-bind"
                  value={form.bind_dn}
                  onChange={(e) => set("bind_dn", e.target.value)}
                  placeholder="cn=flagpost,ou=services,dc=example,dc=com"
                  required
                />
                <p className="text-xs text-muted-foreground">
                  Used to look up the person&apos;s entry before their own
                  credentials are checked. Its password goes in the bind
                  password field below.
                </p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-ldap-base">Search base DN</Label>
                <Input
                  id="ap-ldap-base"
                  value={form.base_dn}
                  onChange={(e) => set("base_dn", e.target.value)}
                  placeholder="ou=people,dc=example,dc=com"
                  required
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label htmlFor="ap-ldap-search">Login attribute</Label>
                  <Input
                    id="ap-ldap-search"
                    value={form.search_attribute}
                    onChange={(e) => set("search_attribute", e.target.value)}
                    placeholder="uid"
                    required
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="ap-ldap-subject">Stable ID attribute</Label>
                  <Input
                    id="ap-ldap-subject"
                    value={form.subject_attribute}
                    onChange={(e) => set("subject_attribute", e.target.value)}
                    placeholder="entryUUID"
                    required
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                Login attribute: what people type as their username
                (<span className="font-mono">sAMAccountName</span> on AD,{" "}
                <span className="font-mono">uid</span> elsewhere). Stable ID:
                the attribute that identifies the account forever —{" "}
                <span className="font-mono">objectGUID</span> on AD,{" "}
                <span className="font-mono">entryUUID</span> on
                OpenLDAP/FreeIPA. Never a DN.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label htmlFor="ap-attr-email">Email attribute</Label>
                  <Input
                    id="ap-attr-email"
                    value={form.email_attribute}
                    onChange={(e) => set("email_attribute", e.target.value)}
                    placeholder="mail"
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="ap-attr-name">Name attribute</Label>
                  <Input
                    id="ap-attr-name"
                    value={form.name_attribute}
                    onChange={(e) => set("name_attribute", e.target.value)}
                    placeholder="displayName"
                  />
                </div>
              </div>
            </>
          ) : isSaml ? (
            <>
              <div className="grid gap-2">
                <Label htmlFor="ap-idp-entity">IdP entity ID</Label>
                <Input
                  id="ap-idp-entity"
                  value={form.idp_entity_id}
                  onChange={(e) => set("idp_entity_id", e.target.value)}
                  placeholder="https://idp.example.edu/idp/shibboleth"
                  required
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-idp-sso">IdP SSO URL</Label>
                <Input
                  id="ap-idp-sso"
                  type="url"
                  value={form.idp_sso_url}
                  onChange={(e) => set("idp_sso_url", e.target.value)}
                  placeholder="https://idp.example.edu/idp/profile/SAML2/Redirect/SSO"
                  required
                />
                <p className="text-xs text-muted-foreground">
                  The HTTP-Redirect single-sign-on endpoint we send the login
                  request to.
                </p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-idp-cert">IdP signing certificate (X.509)</Label>
                <textarea
                  id="ap-idp-cert"
                  className={TEXTAREA_CLASS}
                  value={form.idp_x509_cert}
                  onChange={(e) => set("idp_x509_cert", e.target.value)}
                  placeholder="-----BEGIN CERTIFICATE-----&#10;…&#10;-----END CERTIFICATE-----"
                  required
                />
                <p className="text-xs text-muted-foreground">
                  Every assertion is verified against this before it&apos;s
                  trusted — the load-bearing setting.
                </p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-sp-entity">SP entity ID</Label>
                <Input
                  id="ap-sp-entity"
                  value={form.sp_entity_id}
                  onChange={(e) => set("sp_entity_id", e.target.value)}
                  placeholder="https://ctf.example.edu/saml/metadata"
                  required
                />
                <p className="text-xs text-muted-foreground">
                  Our identifier at the IdP. Must match what you register there.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label htmlFor="ap-attr-email">Email attribute</Label>
                  <Input
                    id="ap-attr-email"
                    value={form.email_attribute}
                    onChange={(e) => set("email_attribute", e.target.value)}
                    placeholder="email"
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="ap-attr-name">Name attribute</Label>
                  <Input
                    id="ap-attr-name"
                    value={form.name_attribute}
                    onChange={(e) => set("name_attribute", e.target.value)}
                    placeholder="displayName"
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                The exact SAML attribute names your IdP sends. The stable NameID
                (must be persistent) becomes the account&apos;s identity.
              </p>
            </>
          ) : (
            <>
              <div className="grid gap-2">
                <Label htmlFor="ap-issuer">Issuer URL</Label>
                <Input
                  id="ap-issuer"
                  type="url"
                  value={form.issuer}
                  onChange={(e) => set("issuer", e.target.value)}
                  placeholder="https://login.example.com"
                  required
                />
                <p className="text-xs text-muted-foreground">
                  Must be HTTPS and publicly resolvable. Discovery reads{" "}
                  <span className="font-mono">
                    {(form.issuer || "…").replace(/\/$/, "")}
                    /.well-known/openid-configuration
                  </span>
                  .
                </p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-client">Client ID</Label>
                <Input
                  id="ap-client"
                  value={form.client_id}
                  onChange={(e) => set("client_id", e.target.value)}
                  required
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-scopes">Scopes</Label>
                <Input
                  id="ap-scopes"
                  value={form.scopes}
                  onChange={(e) => set("scopes", e.target.value)}
                  required
                />
              </div>
            </>
          )}

          <div className="grid gap-2">
            <Label htmlFor="ap-secret">
              {isLdap
                ? "Bind password"
                : isSaml
                  ? "SP private key (optional)"
                  : "Client secret"}
            </Label>
            {isSaml ? (
              <textarea
                id="ap-secret"
                className={TEXTAREA_CLASS}
                autoComplete="off"
                value={form.secret}
                onChange={(e) => set("secret", e.target.value)}
                placeholder={
                  editing?.secret_set
                    ? "•••••• (leave blank to keep)"
                    : "-----BEGIN PRIVATE KEY-----…"
                }
              />
            ) : (
              <Input
                id="ap-secret"
                type="password"
                autoComplete="new-password"
                value={form.secret}
                onChange={(e) => set("secret", e.target.value)}
                placeholder={
                  editing?.secret_set ? "•••••• (leave blank to keep)" : ""
                }
              />
            )}
            <p className="text-xs text-muted-foreground">
              Stored encrypted.{" "}
              {isLdap
                ? "The service account's password — required before the provider can be enabled."
                : isSaml
                  ? "Only needed to sign our requests — leave blank otherwise."
                  : "Leave blank for a public client using PKCE only."}
            </p>
          </div>

          {/* SAML and LDAP are always closed directories (the API enforces
              it), so the posture control only appears for OIDC. */}
          {form.kind === "oidc" && (
            <div className="grid gap-2">
              <Label htmlFor="ap-posture">Sign-in policy</Label>
              <Select
                id="ap-posture"
                value={form.posture}
                onChange={(e) =>
                  set("posture", e.target.value as "open" | "closed")
                }
              >
                <option value="open">
                  Open — public provider, registration rules apply
                </option>
                <option value="closed">
                  Closed — being in this directory is the admission
                </option>
              </Select>
              <p className="text-xs text-muted-foreground">
                {form.posture === "open"
                  ? "For public IdPs (Google, GitHub): new accounts pass the same registration-open and email-domain checks as the sign-up form."
                  : "For your own directory (corporate or campus IdP): anyone who can sign in there may enter, even while public registration is closed."}
              </p>
            </div>
          )}

          {(form.kind !== "oidc" || form.posture === "closed") && (
            <div className="grid gap-2">
              <label className="flex items-start gap-2.5 text-sm">
                <input
                  type="checkbox"
                  checked={form.email_is_authoritative}
                  onChange={(e) =>
                    set("email_is_authoritative", e.target.checked)
                  }
                  className="mt-0.5"
                  style={{ accentColor: "hsl(var(--primary))" }}
                />
                <span>
                  Trust this provider&apos;s email addresses
                  <span className="block text-xs font-normal text-muted-foreground">
                    Lets a first sign-in attach to an existing account with the
                    same address. Only enable this if the directory verifies
                    mailbox ownership — an unverified address here can claim
                    someone else&apos;s account.
                  </span>
                </span>
              </label>
            </div>
          )}

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error.message}
            </p>
          )}

          <div className="flex items-center gap-2">
            <Button type="submit" disabled={pending}>
              {pending ? "Saving…" : editing ? "Save changes" : "Add provider"}
            </Button>
            <Button type="button" variant="ghost" onClick={onDone}>
              Cancel
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

/** One quick-setup card (#preset). Google opens the prefilled form in one
 *  click; Microsoft first collects its tenant GUID inline (its issuer is a
 *  per-tenant template), then opens the form. Either way the admin still
 *  pastes client ID + secret into the ordinary form and can edit anything. */
function PresetCard({
  preset,
  onUse,
}: {
  preset: ProviderPreset;
  onUse: (prefill: Partial<FormState>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  // Param errors only show after a submit attempt — not while typing a GUID.
  const [attempted, setAttempted] = useState(false);
  const [collecting, setCollecting] = useState(false);

  function start() {
    if (preset.params.length > 0 && !collecting) {
      setCollecting(true);
      return;
    }
    const prefill = presetToFormPrefill(preset, values);
    if (!prefill) {
      setAttempted(true);
      return;
    }
    onUse(prefill);
  }

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4">
        <div className="flex items-center gap-2">
          <SsoBrandIcon brand={preset.id} className="shrink-0" />
          <span className="font-medium">{preset.name}</span>
        </div>
        <p className="text-xs text-muted-foreground">{preset.notes}</p>

        {collecting &&
          preset.params.map((param) => {
            const value = values[param.key] ?? "";
            const error = validatePresetParam(param, value);
            const id = `preset-${preset.id}-${param.key}`;
            return (
              <div key={param.key} className="grid gap-2">
                <Label htmlFor={id}>{param.label}</Label>
                <Input
                  id={id}
                  value={value}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, [param.key]: e.target.value }))
                  }
                  placeholder={param.placeholder}
                  autoComplete="off"
                />
                {attempted && error ? (
                  <p role="alert" className="text-xs text-destructive">
                    {error}
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">{param.help}</p>
                )}
              </div>
            );
          })}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" variant="outline" size="sm" onClick={start}>
            {collecting ? "Continue" : `Set up ${preset.name}`}
          </Button>
          <a
            href={preset.setup_url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-muted-foreground hover:text-primary hover:underline"
          >
            {setupLinkLabel(preset)} ↗
          </a>
        </div>
      </CardContent>
    </Card>
  );
}

export function AuthProvidersPanel() {
  const { data: providers, isLoading, isError, error } = useAdminAuthProviders();
  // Degrades gracefully: on error/loading `presets` is undefined and the
  // quick-setup cards simply don't render — the panel works exactly as before.
  const { data: presets } = useProviderPresets();
  const update = useUpdateAuthProvider();
  const remove = useDeleteAuthProvider();
  const confirm = useConfirm();
  const [editing, setEditing] = useState<AuthProvider | null>(null);
  const [adding, setAdding] = useState(false);
  const [prefill, setPrefill] = useState<Partial<FormState> | null>(null);

  async function onDelete(provider: AuthProvider) {
    if (
      !(await confirm({
        title: `Delete ${provider.name}?`,
        description:
          "Anyone who signs in only through this provider will lose their way in — a single-sign-on account has no password to fall back on. Disabling it instead is reversible.",
        confirmLabel: "Delete",
        destructive: true,
      }))
    ) {
      return;
    }
    remove.mutate(provider.id, {
      onSuccess: () => toast("Provider deleted", { variant: "success" }),
    });
  }

  if (isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {(error as Error).message}
      </p>
    );
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Auth providers</h2>
          <p className="mb-4 mt-1 text-sm text-muted-foreground">
            Let people sign in with an external identity provider. Local
            passwords keep working, so an administrator can still get in if a
            provider goes down.
          </p>
        </div>
        {!adding && !editing && (
          <Button onClick={() => setAdding(true)}>Add provider</Button>
        )}
      </div>

      {/* Quick set up — hidden while any form is open, just like the Add
          provider button. Presets only prefill that same form. */}
      {!adding && !editing && presets && presets.length > 0 && (
        <div className="grid gap-2">
          <h3 className="text-sm font-semibold">Quick set up</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {presets.map((preset) => (
              <PresetCard
                key={preset.id}
                preset={preset}
                onUse={(seed) => {
                  setPrefill(seed);
                  setAdding(true);
                }}
              />
            ))}
          </div>
        </div>
      )}

      {(adding || editing) && (
        <ProviderForm
          // Remount on target change so the form's useState initializer re-runs
          // — otherwise switching from a preset-prefilled create to Edit (or
          // Edit A to Edit B) keeps the old values under the new header and
          // would PATCH them onto the wrong provider.
          key={editing ? `edit-${editing.id}` : "create"}
          editing={editing}
          prefill={prefill}
          onDone={() => {
            setAdding(false);
            setEditing(null);
            setPrefill(null);
          }}
        />
      )}

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : providers && providers.length > 0 ? (
        <div className="grid gap-3">
          {providers.map((p) => (
            <Card key={p.id}>
              <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
                <div className="grid gap-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{p.name}</span>
                    <Badge variant="outline" className="uppercase">
                      {p.kind}
                    </Badge>
                    <Badge variant={p.enabled ? "success" : "muted"}>
                      {p.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                    {p.posture === "closed" && (
                      <Badge variant="secondary">Closed</Badge>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {p.kind === "saml"
                      ? p.config.idp_entity_id
                      : p.kind === "ldap"
                        ? p.config.server_url
                        : p.config.issuer}
                  </span>
                  {p.kind === "oidc" ? (
                    <span className="font-mono text-[11px] text-muted-foreground">
                      Redirect URI: {p.redirect_uri}
                    </span>
                  ) : p.kind === "saml" ? (
                    <span className="font-mono text-[11px] text-muted-foreground">
                      SP metadata: /api/auth/saml/{p.slug}/metadata
                    </span>
                  ) : (
                    <span className="text-[11px] text-muted-foreground">
                      Signs in through the standard username &amp; password form
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={update.isPending}
                    onClick={() =>
                      update.mutate(
                        { id: p.id, enabled: !p.enabled },
                        {
                          onSuccess: () =>
                            toast(p.enabled ? "Provider disabled" : "Provider enabled", {
                              variant: "success",
                            }),
                        },
                      )
                    }
                  >
                    {p.enabled ? "Disable" : "Enable"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      // Clear any half-started create/preset flow so a stale
                      // prefill can't linger behind the edit form.
                      setAdding(false);
                      setPrefill(null);
                      setEditing(p);
                    }}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive"
                    disabled={remove.isPending}
                    onClick={() => onDelete(p)}
                  >
                    Delete
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        !adding && (
          <EmptyState
            title="No identity providers"
            description="Add an OIDC, SAML or LDAP provider to let people sign in with your organisation's directory instead of a Flagpost password."
            action={<Button onClick={() => setAdding(true)}>Add provider</Button>}
          />
        )
      )}
    </div>
  );
}
