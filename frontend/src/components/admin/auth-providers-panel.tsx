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

import { useTranslations } from "next-intl";
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

type Kind = "oidc" | "oauth2" | "saml" | "ldap";

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
  // OIDC, multi-tenant Entra only (ADR-0032): the id_token `iss` validation
  // template; normally blank.
  issuer_template: string;
  // OAuth2 (#193): endpoints + the claim map naming which userinfo fields
  // carry identity. No issuer — a plain-OAuth2 provider has none.
  authorize_url: string;
  token_url: string;
  userinfo_url: string;
  emails_url: string;
  subject_field: string;
  email_field: string;
  name_field: string;
  email_verified_field: string;
  use_pkce: boolean;
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
  issuer_template: "",
  authorize_url: "",
  token_url: "",
  userinfo_url: "",
  emails_url: "",
  subject_field: "id",
  email_field: "email",
  name_field: "name",
  email_verified_field: "",
  use_pkce: false,
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
    issuer_template: str(c.issuer_template),
    authorize_url: str(c.authorize_url),
    token_url: str(c.token_url),
    userinfo_url: str(c.userinfo_url),
    emails_url: str(c.emails_url),
    subject_field: str(c.subject_field, "id"),
    email_field: str(c.email_field, "email"),
    name_field: str(c.name_field, "name"),
    email_verified_field: str(c.email_verified_field),
    use_pkce: c.use_pkce === true,
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
  const t = useTranslations("admin.authProviders");
  const create = useCreateAuthProvider();
  const update = useUpdateAuthProvider();
  const [form, setForm] = useState<FormState>(
    editing ? fromEditing(editing) : prefill ? { ...EMPTY, ...prefill } : EMPTY,
  );
  const pending = create.isPending || update.isPending;
  const error = (create.error ?? update.error) as Error | null;
  const isSaml = form.kind === "saml";
  const isLdap = form.kind === "ldap";
  const isOauth2 = form.kind === "oauth2";

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
        : isOauth2
          ? {
              authorize_url: form.authorize_url,
              token_url: form.token_url,
              userinfo_url: form.userinfo_url,
              client_id: form.client_id,
              scopes: form.scopes,
              subject_field: form.subject_field,
              // Optional claim-map entries: blank means "this provider doesn't
              // expose one", which the backend stores as null rather than
              // looking up an empty key.
              email_field: form.email_field.trim() || null,
              name_field: form.name_field.trim() || null,
              email_verified_field: form.email_verified_field.trim() || null,
              emails_url: form.emails_url.trim() || null,
              use_pkce: form.use_pkce,
            }
          : {
              issuer: form.issuer,
              client_id: form.client_id,
              scopes: form.scopes,
              // Blank for single-tenant; the backend stores null and validates
              // exact-issuer as before (ADR-0032).
              issuer_template: form.issuer_template.trim() || null,
            };
    // SAML/LDAP are always closed (the API enforces it). The public-IdP kinds —
    // OIDC and OAuth2 — let the admin choose. email_is_authoritative only means
    // something for a closed directory, so switching a provider to open clears
    // it rather than 400ing.
    const posture =
      form.kind === "oidc" || form.kind === "oauth2" ? form.posture : "closed";
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
            toast(t("providerUpdated"), { variant: "success" });
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
            toast(t("providerAdded"), {
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
        <CardTitle>{editing ? t("editTitle", { name: editing.name }) : t("addTitle")}</CardTitle>
        <CardDescription>
          {isLdap ? t("descLdap") : isSaml ? t("descSaml") : t("descOauth")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid max-w-xl gap-4">
          {!editing && (
            <div className="grid gap-2">
              <Label htmlFor="ap-kind">{t("protocol")}</Label>
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
                <option value="oidc">{t("protocolOidc")}</option>
                <option value="oauth2">{t("protocolOauth2")}</option>
                <option value="saml">{t("protocolSaml")}</option>
                <option value="ldap">{t("protocolLdap")}</option>
              </Select>
              <p className="text-xs text-muted-foreground">{t("protocolHint")}</p>
            </div>
          )}

          <div className="grid gap-2">
            <Label htmlFor="ap-name">{t("displayName")}</Label>
            <Input
              id="ap-name"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="Company SSO"
              required
            />
            <p className="text-xs text-muted-foreground">
              {isLdap
                ? t("displayNameHintLdap")
                : t("displayNameHint", { name: form.name || "…" })}
            </p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="ap-slug">{t("slug")}</Label>
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
              {editing ? t("slugHintEditing") : t("slugHint")}
            </p>
          </div>

          {isLdap ? (
            <>
              <div className="grid gap-2">
                <Label htmlFor="ap-ldap-url">{t("serverUrl")}</Label>
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
                  {t("startTls")}
                </label>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-ldap-bind">{t("bindDn")}</Label>
                <Input
                  id="ap-ldap-bind"
                  value={form.bind_dn}
                  onChange={(e) => set("bind_dn", e.target.value)}
                  placeholder="cn=flagpost,ou=services,dc=example,dc=com"
                  required
                />
                <p className="text-xs text-muted-foreground">{t("bindDnHint")}</p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-ldap-base">{t("baseDn")}</Label>
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
                  <Label htmlFor="ap-ldap-search">{t("loginAttribute")}</Label>
                  <Input
                    id="ap-ldap-search"
                    value={form.search_attribute}
                    onChange={(e) => set("search_attribute", e.target.value)}
                    placeholder="uid"
                    required
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="ap-ldap-subject">{t("stableIdAttribute")}</Label>
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
                {t.rich("ldapAttrHint", {
                  mono: (chunks) => <span className="font-mono">{chunks}</span>,
                })}
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label htmlFor="ap-attr-email">{t("emailAttribute")}</Label>
                  <Input
                    id="ap-attr-email"
                    value={form.email_attribute}
                    onChange={(e) => set("email_attribute", e.target.value)}
                    placeholder="mail"
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="ap-attr-name">{t("nameAttribute")}</Label>
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
                <Label htmlFor="ap-idp-entity">{t("idpEntityId")}</Label>
                <Input
                  id="ap-idp-entity"
                  value={form.idp_entity_id}
                  onChange={(e) => set("idp_entity_id", e.target.value)}
                  placeholder="https://idp.example.edu/idp/shibboleth"
                  required
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-idp-sso">{t("idpSsoUrl")}</Label>
                <Input
                  id="ap-idp-sso"
                  type="url"
                  value={form.idp_sso_url}
                  onChange={(e) => set("idp_sso_url", e.target.value)}
                  placeholder="https://idp.example.edu/idp/profile/SAML2/Redirect/SSO"
                  required
                />
                <p className="text-xs text-muted-foreground">{t("idpSsoUrlHint")}</p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-idp-cert">{t("idpCert")}</Label>
                <textarea
                  id="ap-idp-cert"
                  className={TEXTAREA_CLASS}
                  value={form.idp_x509_cert}
                  onChange={(e) => set("idp_x509_cert", e.target.value)}
                  placeholder="-----BEGIN CERTIFICATE-----&#10;…&#10;-----END CERTIFICATE-----"
                  required
                />
                <p className="text-xs text-muted-foreground">{t("idpCertHint")}</p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-sp-entity">{t("spEntityId")}</Label>
                <Input
                  id="ap-sp-entity"
                  value={form.sp_entity_id}
                  onChange={(e) => set("sp_entity_id", e.target.value)}
                  placeholder="https://ctf.example.edu/saml/metadata"
                  required
                />
                <p className="text-xs text-muted-foreground">{t("spEntityIdHint")}</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label htmlFor="ap-attr-email">{t("emailAttribute")}</Label>
                  <Input
                    id="ap-attr-email"
                    value={form.email_attribute}
                    onChange={(e) => set("email_attribute", e.target.value)}
                    placeholder="email"
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="ap-attr-name">{t("nameAttribute")}</Label>
                  <Input
                    id="ap-attr-name"
                    value={form.name_attribute}
                    onChange={(e) => set("name_attribute", e.target.value)}
                    placeholder="displayName"
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">{t("samlAttrHint")}</p>
            </>
          ) : isOauth2 ? (
            <>
              <div className="grid gap-2">
                <Label htmlFor="ap-authorize-url">{t("authorizeUrl")}</Label>
                <Input
                  id="ap-authorize-url"
                  type="url"
                  value={form.authorize_url}
                  onChange={(e) => set("authorize_url", e.target.value)}
                  placeholder="https://github.com/login/oauth/authorize"
                  required
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-token-url">{t("tokenUrl")}</Label>
                <Input
                  id="ap-token-url"
                  type="url"
                  value={form.token_url}
                  onChange={(e) => set("token_url", e.target.value)}
                  placeholder="https://github.com/login/oauth/access_token"
                  required
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-userinfo-url">{t("userinfoUrl")}</Label>
                <Input
                  id="ap-userinfo-url"
                  type="url"
                  value={form.userinfo_url}
                  onChange={(e) => set("userinfo_url", e.target.value)}
                  placeholder="https://api.github.com/user"
                  required
                />
                <p className="text-xs text-muted-foreground">{t("userinfoUrlHint")}</p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-client">{t("clientId")}</Label>
                <Input
                  id="ap-client"
                  value={form.client_id}
                  onChange={(e) => set("client_id", e.target.value)}
                  required
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-scopes">{t("scopes")}</Label>
                <Input
                  id="ap-scopes"
                  value={form.scopes}
                  onChange={(e) => set("scopes", e.target.value)}
                  placeholder="read:user user:email"
                />
              </div>

              <div className="grid gap-3 rounded-md border border-border p-3">
                <p className="text-xs font-medium">{t("claimMap")}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="grid gap-2">
                    <Label htmlFor="ap-subject-field">{t("subjectField")}</Label>
                    <Input
                      id="ap-subject-field"
                      value={form.subject_field}
                      onChange={(e) => set("subject_field", e.target.value)}
                      placeholder="id"
                      required
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="ap-email-field">{t("emailField")}</Label>
                    <Input
                      id="ap-email-field"
                      value={form.email_field}
                      onChange={(e) => set("email_field", e.target.value)}
                      placeholder="email"
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="ap-name-field">{t("nameField")}</Label>
                    <Input
                      id="ap-name-field"
                      value={form.name_field}
                      onChange={(e) => set("name_field", e.target.value)}
                      placeholder="login"
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="ap-email-verified-field">
                      {t("emailVerifiedField")}
                    </Label>
                    <Input
                      id="ap-email-verified-field"
                      value={form.email_verified_field}
                      onChange={(e) =>
                        set("email_verified_field", e.target.value)
                      }
                      placeholder="verified"
                    />
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">{t("claimMapHint")}</p>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="ap-emails-url">
                  {t("verifiedEmailsUrl")}{" "}
                  <span className="text-muted-foreground">{t("optional")}</span>
                </Label>
                <Input
                  id="ap-emails-url"
                  type="url"
                  value={form.emails_url}
                  onChange={(e) => set("emails_url", e.target.value)}
                  placeholder="https://api.github.com/user/emails"
                />
                <p className="text-xs text-muted-foreground">{t("verifiedEmailsUrlHint")}</p>
              </div>

              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={form.use_pkce}
                  onChange={(e) => set("use_pkce", e.target.checked)}
                />
                <span>
                  {t("usePkce")}
                  <span className="block text-xs text-muted-foreground">
                    {t("usePkceHint")}
                  </span>
                </span>
              </label>
            </>
          ) : (
            <>
              <div className="grid gap-2">
                <Label htmlFor="ap-issuer">{t("issuerUrl")}</Label>
                <Input
                  id="ap-issuer"
                  type="url"
                  value={form.issuer}
                  onChange={(e) => set("issuer", e.target.value)}
                  placeholder="https://login.example.com"
                  required
                />
                <p className="text-xs text-muted-foreground">
                  {t.rich("issuerUrlHint", {
                    mono: (chunks) => <span className="font-mono">{chunks}</span>,
                    url: `${(form.issuer || "…").replace(/\/$/, "")}/.well-known/openid-configuration`,
                  })}
                </p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-client">{t("clientId")}</Label>
                <Input
                  id="ap-client"
                  value={form.client_id}
                  onChange={(e) => set("client_id", e.target.value)}
                  required
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-scopes">{t("scopes")}</Label>
                <Input
                  id="ap-scopes"
                  value={form.scopes}
                  onChange={(e) => set("scopes", e.target.value)}
                  required
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ap-issuer-template">
                  {t("tenantTemplate")}{" "}
                  <span className="text-muted-foreground">{t("optional")}</span>
                </Label>
                <Input
                  id="ap-issuer-template"
                  value={form.issuer_template}
                  onChange={(e) => set("issuer_template", e.target.value)}
                  placeholder="https://login.microsoftonline.com/{tenantid}/v2.0"
                />
                <p className="text-xs text-muted-foreground">
                  {t.rich("tenantTemplateHint", {
                    mono: (chunks) => <span className="font-mono">{chunks}</span>,
                  })}
                </p>
              </div>
            </>
          )}

          <div className="grid gap-2">
            <Label htmlFor="ap-secret">
              {isLdap ? t("secretLdap") : isSaml ? t("secretSaml") : t("secretOidc")}
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
                    ? t("secretPlaceholderKeep")
                    : t("secretPlaceholderSaml")
                }
              />
            ) : (
              <Input
                id="ap-secret"
                type="password"
                autoComplete="new-password"
                value={form.secret}
                onChange={(e) => set("secret", e.target.value)}
                placeholder={editing?.secret_set ? t("secretPlaceholderKeep") : ""}
              />
            )}
            <p className="text-xs text-muted-foreground">
              {isLdap ? t("secretHintLdap") : isSaml ? t("secretHintSaml") : t("secretHintOidc")}
            </p>
          </div>

          {/* SAML and LDAP are always closed directories (the API enforces
              it), so the posture control only appears for the public-IdP kinds:
              OIDC and plain OAuth2. */}
          {(form.kind === "oidc" || form.kind === "oauth2") && (
            <div className="grid gap-2">
              <Label htmlFor="ap-posture">{t("signInPolicy")}</Label>
              <Select
                id="ap-posture"
                value={form.posture}
                onChange={(e) =>
                  set("posture", e.target.value as "open" | "closed")
                }
              >
                <option value="open">{t("postureOpen")}</option>
                <option value="closed">{t("postureClosed")}</option>
              </Select>
              <p className="text-xs text-muted-foreground">
                {form.posture === "open" ? t("postureHintOpen") : t("postureHintClosed")}
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
                  {t("trustEmail")}
                  <span className="block text-xs font-normal text-muted-foreground">
                    {t("trustEmailHint")}
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
              {pending ? t("saving") : editing ? t("saveChanges") : t("addProvider")}
            </Button>
            <Button type="button" variant="ghost" onClick={onDone}>
              {t("cancel")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

/** One quick-setup row (#preset). Google opens the prefilled form in one
 *  click; Microsoft first collects its tenant GUID inline (its issuer is a
 *  per-tenant template), then opens the form. Either way the admin still
 *  pastes client ID + secret into the ordinary form and can edit anything.
 *
 *  Laid out as a row rather than a card: the catalog grew to five entries and
 *  keeps growing (a new OAuth2 IdP is just data), and a card grid gave every
 *  entry a different height, left a hole in the last column, and pushed the
 *  actual provider list below the fold. Rows stay uniform however many there
 *  are. */
function PresetRow({
  preset,
  onUse,
}: {
  preset: ProviderPreset;
  onUse: (prefill: Partial<FormState>) => void;
}) {
  const t = useTranslations("admin.authProviders");
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
    <div className="flex flex-col gap-3 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <SsoBrandIcon
          brand={preset.id.startsWith("microsoft") ? "microsoft" : preset.id}
          className="shrink-0"
        />
        {/* min-w-0 lets the note wrap instead of forcing the row wider than
            the panel when a provider's guidance is long. */}
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">{preset.name}</div>
          <p className="text-xs text-muted-foreground">{preset.notes}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <a
            href={preset.setup_url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-muted-foreground hover:text-primary hover:underline"
          >
            {setupLinkLabel(preset)}
          </a>
          {/* Just "Set up" — the provider is already named to the left, and
              repeating it made the longest label ("Set up Microsoft
              (multi-tenant)") set the width of every button. */}
          <Button type="button" variant="outline" size="sm" onClick={start}>
            {collecting ? t("continue") : t("setUp")}
          </Button>
        </div>
      </div>

      {collecting &&
        preset.params.map((param) => {
          const value = values[param.key] ?? "";
          const error = validatePresetParam(param, value);
          const id = `preset-${preset.id}-${param.key}`;
          return (
            <div key={param.key} className="grid max-w-md gap-2">
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
    </div>
  );
}

export function AuthProvidersPanel() {
  const t = useTranslations("admin.authProviders");
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
        title: t("deleteTitle", { name: provider.name }),
        description: t("deleteDescription"),
        confirmLabel: t("deleteConfirm"),
        destructive: true,
      }))
    ) {
      return;
    }
    remove.mutate(provider.id, {
      onSuccess: () => toast(t("providerDeleted"), { variant: "success" }),
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
          <h2 className="text-lg font-semibold">{t("heading")}</h2>
          <p className="mb-4 mt-1 text-sm text-muted-foreground">
            {t("headingDescription")}
          </p>
        </div>
        {!adding && !editing && (
          <Button onClick={() => setAdding(true)}>{t("addProvider")}</Button>
        )}
      </div>

      {/* Quick set up — hidden while any form is open, just like the Add
          provider button. Presets only prefill that same form. */}
      {!adding && !editing && presets && presets.length > 0 && (
        <div className="grid gap-2">
          <h3 className="text-sm font-semibold">{t("quickSetup")}</h3>
          {/* Said once here rather than repeated in all five notes: it's the
              same for every provider, and forgetting it is the most common
              reason a finished setup still fails at first sign-in. */}
          <p className="text-xs text-muted-foreground">{t("quickSetupHint")}</p>
          <Card>
            <CardContent className="divide-y divide-border p-0">
              {presets.map((preset) => (
                <PresetRow
                  key={preset.id}
                  preset={preset}
                  onUse={(seed) => {
                    setPrefill(seed);
                    setAdding(true);
                  }}
                />
              ))}
            </CardContent>
          </Card>
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
        <p className="text-sm text-muted-foreground">{t("loading")}</p>
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
                      {p.enabled ? t("badgeEnabled") : t("badgeDisabled")}
                    </Badge>
                    {p.posture === "closed" && (
                      <Badge variant="secondary">{t("badgeClosed")}</Badge>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {p.kind === "saml"
                      ? p.config.idp_entity_id
                      : p.kind === "ldap"
                        ? p.config.server_url
                        : p.kind === "oauth2"
                          ? p.config.authorize_url
                          : p.config.issuer}
                  </span>
                  {p.kind === "oidc" || p.kind === "oauth2" ? (
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {t("redirectUri", { uri: p.redirect_uri })}
                    </span>
                  ) : p.kind === "saml" ? (
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {t("spMetadata", { slug: p.slug })}
                    </span>
                  ) : (
                    <span className="text-[11px] text-muted-foreground">
                      {t("ldapSignInNote")}
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
                            toast(p.enabled ? t("providerDisabled") : t("providerEnabled"), {
                              variant: "success",
                            }),
                        },
                      )
                    }
                  >
                    {p.enabled ? t("disable") : t("enable")}
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
                    {t("edit")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive"
                    disabled={remove.isPending}
                    onClick={() => onDelete(p)}
                  >
                    {t("delete")}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        !adding && (
          <EmptyState
            title={t("emptyTitle")}
            description={t("emptyDescription")}
            action={<Button onClick={() => setAdding(true)}>{t("addProvider")}</Button>}
          />
        )
      )}
    </div>
  );
}
