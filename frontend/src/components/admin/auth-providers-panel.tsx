"use client";

// Admin → Site settings → Auth (#58/#100, ADR-0021, ADR-0022). Configure the
// identity providers offered on the login page — OIDC and SAML today.
//
// A panel rather than its own route: it's a tab of Site settings, mounted
// alongside the others. Note it's gated on `manage_auth_providers`, *not* the
// `manage_site_settings` the rest of that page needs — who can sign in is a
// higher-stakes surface than a palette (§7.1) — so the page shows this tab only
// to holders of that permission.
//
// The secret (OIDC client secret; SAML SP private key) is write-only: the API
// only ever tells us whether one is stored, so the edit form leaves its field
// blank and omitting it preserves what's saved. That mirrors the SMTP password.

import { useState } from "react";

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
  useUpdateAuthProvider,
} from "@/lib/hooks/use-users";
import type { AuthProvider } from "@/lib/types";
import { toast } from "@/stores/toast";

type Kind = "oidc" | "saml";

interface FormState {
  kind: Kind;
  name: string;
  slug: string;
  posture: "open" | "closed";
  email_is_authoritative: boolean;
  // Write-only: OIDC client secret, or SAML SP private key (PEM).
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
  email_attribute: string;
  name_attribute: string;
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
};

function fromEditing(p: AuthProvider): FormState {
  const c = p.config;
  return {
    kind: p.kind as Kind,
    name: p.name,
    slug: p.slug,
    posture: p.posture,
    email_is_authoritative: p.email_is_authoritative,
    secret: "", // never returned; blank means "leave unchanged"
    issuer: c.issuer ?? "",
    client_id: c.client_id ?? "",
    scopes: c.scopes ?? "openid email profile",
    idp_entity_id: c.idp_entity_id ?? "",
    idp_sso_url: c.idp_sso_url ?? "",
    idp_x509_cert: c.idp_x509_cert ?? "",
    sp_entity_id: c.sp_entity_id ?? "",
    sp_x509_cert: c.sp_x509_cert ?? "",
    email_attribute: c.email_attribute ?? "email",
    name_attribute: c.name_attribute ?? "displayName",
  };
}

/** Multi-line field for PEM certs/keys — no Textarea primitive exists yet, so
 *  this borrows the Input token styling. */
const TEXTAREA_CLASS =
  "flex min-h-[88px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

function ProviderForm({
  editing,
  onDone,
}: {
  editing: AuthProvider | null;
  onDone: () => void;
}) {
  const create = useCreateAuthProvider();
  const update = useUpdateAuthProvider();
  const [form, setForm] = useState<FormState>(
    editing ? fromEditing(editing) : EMPTY,
  );
  const pending = create.isPending || update.isPending;
  const error = (create.error ?? update.error) as Error | null;
  const isSaml = form.kind === "saml";

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const config: Record<string, string | null> = isSaml
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
    // SAML is always closed (the API enforces it). For OIDC the admin chooses.
    // email_is_authoritative only means something for a closed directory, so
    // switching a provider to open clears it rather than 400ing.
    const posture = isSaml ? "closed" : form.posture;
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
          {isSaml
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
                onChange={(e) => set("kind", e.target.value as Kind)}
              >
                <option value="oidc">OpenID Connect (OAuth2)</option>
                <option value="saml">SAML 2.0</option>
              </Select>
              <p className="text-xs text-muted-foreground">
                Fixed after creation. SAML suits campus/enterprise IdPs
                (Shibboleth, ADFS); OIDC suits most modern providers.
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
              Shown on the login button: &ldquo;Sign in with {form.name || "…"}&rdquo;.
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

          {isSaml ? (
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
              {isSaml ? "SP private key (optional)" : "Client secret"}
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
              {isSaml
                ? "Only needed to sign our requests — leave blank otherwise."
                : "Leave blank for a public client using PKCE only."}
            </p>
          </div>

          {/* SAML is always a closed directory (the API enforces it), so the
              posture control only appears for OIDC. */}
          {!isSaml && (
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

          {(isSaml || form.posture === "closed") && (
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

export function AuthProvidersPanel() {
  const { data: providers, isLoading, isError, error } = useAdminAuthProviders();
  const update = useUpdateAuthProvider();
  const remove = useDeleteAuthProvider();
  const confirm = useConfirm();
  const [editing, setEditing] = useState<AuthProvider | null>(null);
  const [adding, setAdding] = useState(false);

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

      {(adding || editing) && (
        <ProviderForm
          editing={editing}
          onDone={() => {
            setAdding(false);
            setEditing(null);
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
                      : p.config.issuer}
                  </span>
                  {p.kind === "oidc" ? (
                    <span className="font-mono text-[11px] text-muted-foreground">
                      Redirect URI: {p.redirect_uri}
                    </span>
                  ) : (
                    <span className="font-mono text-[11px] text-muted-foreground">
                      SP metadata: /api/auth/saml/{p.slug}/metadata
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
                  <Button variant="ghost" size="sm" onClick={() => setEditing(p)}>
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
            description="Add an OIDC or SAML provider to let people sign in with your organisation's directory instead of a Flagpost password."
            action={<Button onClick={() => setAdding(true)}>Add provider</Button>}
          />
        )
      )}
    </div>
  );
}
