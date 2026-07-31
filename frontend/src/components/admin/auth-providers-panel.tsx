"use client";

// Admin → Site settings → Auth (#58, ADR-0021). Configure the OIDC identity
// providers offered on the login page.
//
// A panel rather than its own route: it's a tab of Site settings, mounted
// alongside the others. Note it's gated on `manage_auth_providers`, *not* the
// `manage_site_settings` the rest of that page needs — who can sign in is a
// higher-stakes surface than a palette (§7.1) — so the page shows this tab only
// to holders of that permission, and grants access to the page for someone who
// holds it without the site-settings grant.
//
// The client secret is write-only: the API only ever tells us whether one is
// stored, so the edit form leaves its field blank and omitting it preserves
// what's saved. That mirrors the SMTP password field on Site settings.

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
import {
  useAdminAuthProviders,
  useCreateAuthProvider,
  useDeleteAuthProvider,
  useUpdateAuthProvider,
} from "@/lib/hooks/use-users";
import type { AuthProvider } from "@/lib/types";
import { toast } from "@/stores/toast";

interface FormState {
  name: string;
  slug: string;
  issuer: string;
  client_id: string;
  client_secret: string;
  scopes: string;
}

const EMPTY: FormState = {
  name: "",
  slug: "",
  issuer: "",
  client_id: "",
  client_secret: "",
  scopes: "openid email profile",
};

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
    editing
      ? {
          name: editing.name,
          slug: editing.slug,
          issuer: editing.issuer,
          client_id: editing.client_id,
          client_secret: "", // never returned; blank means "leave unchanged"
          scopes: editing.scopes,
        }
      : EMPTY,
  );
  const pending = create.isPending || update.isPending;
  const error = (create.error ?? update.error) as Error | null;

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (editing) {
      update.mutate(
        {
          id: editing.id,
          name: form.name,
          issuer: form.issuer,
          client_id: form.client_id,
          scopes: form.scopes,
          // Omitted entirely when blank, so an edit never wipes a stored secret.
          ...(form.client_secret ? { client_secret: form.client_secret } : {}),
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
        { ...form, client_secret: form.client_secret || null, enabled: false },
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
          Register Flagpost as an OAuth client at your provider first, then paste
          its details here. New providers start disabled.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid max-w-xl gap-4">
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
                ? "Fixed after creation — it's part of the redirect URI registered at your provider."
                : "Lowercase letters, numbers and hyphens. Appears in the redirect URI."}
            </p>
          </div>

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
            <Label htmlFor="ap-secret">Client secret</Label>
            <Input
              id="ap-secret"
              type="password"
              autoComplete="new-password"
              value={form.client_secret}
              onChange={(e) => set("client_secret", e.target.value)}
              placeholder={
                editing?.client_secret_set ? "•••••• (leave blank to keep)" : ""
              }
            />
            <p className="text-xs text-muted-foreground">
              Stored encrypted. Leave blank for a public client using PKCE only.
            </p>
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
                    <Badge variant={p.enabled ? "success" : "muted"}>
                      {p.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                    {!p.client_secret_set && (
                      <Badge variant="muted">Public client</Badge>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">{p.issuer}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    Redirect URI: {p.redirect_uri}
                  </span>
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
            description="Add an OIDC provider to let people sign in with your organisation's directory instead of a Flagpost password."
            action={<Button onClick={() => setAdding(true)}>Add provider</Button>}
          />
        )
      )}
    </div>
  );
}
