"use client";

// Admin → Marketplace (#389, ADR-0040). Two surfaces: import a content pack by
// pasting a code (resolve → confirm → install), and configure the registry +
// trust policy. Import is gated on install_content_pack; settings on
// manage_marketplace, so a delegate can hold one without the other.

import { useTranslations } from "next-intl";
import { Suspense, useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompetitions } from "@/lib/hooks/use-competitions";
import {
  useInstallFromCode,
  useMarketplaceSettings,
  useResolveCode,
  useUpdateMarketplaceSettings,
} from "@/lib/hooks/use-marketplace";
import { useAccess } from "@/lib/hooks/use-permissions";
import type {
  MarketplaceResolveResult,
  MarketplaceSettings,
  MarketplaceTrustedKey,
} from "@/lib/types";
import { toast } from "@/stores/toast";

function MarketplaceInner() {
  const t = useTranslations("admin.marketplace");
  const access = useAccess();

  if (!access.ready) return <Skeleton className="h-64 w-full" />;
  const canImport = access.has("install_content_pack");
  const canManage = access.has("manage_marketplace");
  if (!canImport && !canManage) {
    return (
      <>
        <SectionHeader title={t("title")} subtitle={t("subtitleShort")} />
        <EmptyState title={t("noAccessTitle")} description={t("noAccessDescription")} />
      </>
    );
  }

  return (
    <>
      <SectionHeader title={t("title")} subtitle={t("subtitle")} />
      <div className="mt-6 grid max-w-2xl gap-6">
        {canImport && <ImportCard />}
        {canManage && <SettingsCard />}
      </div>
    </>
  );
}

function ImportCard() {
  const t = useTranslations("admin.marketplace");
  const [code, setCode] = useState("");
  const [resolved, setResolved] = useState<MarketplaceResolveResult | null>(null);
  const [competitionId, setCompetitionId] = useState("");
  const resolve = useResolveCode();
  const install = useInstallFromCode();
  const competitions = useCompetitions();
  const comps = competitions.data ?? [];

  function onResolve(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    resolve.mutate(code.trim(), {
      onSuccess: (data) => {
        setResolved(data);
        setCompetitionId("");
      },
      onError: (err) =>
        toast(t("couldntResolve"), { description: (err as Error).message, variant: "destructive" }),
    });
  }

  function onInstall() {
    if (!resolved) return;
    const target = resolved.pack_type === "challenges" ? competitionId : undefined;
    install.mutate(
      { code: code.trim(), competition_id: target },
      {
        onSuccess: () => {
          toast(t("installed", { name: resolved.name }), { variant: "success" });
          setResolved(null);
          setCode("");
        },
        onError: (err) =>
          toast(t("couldntInstall"), { description: (err as Error).message, variant: "destructive" }),
      },
    );
  }

  const needsCompetition = resolved?.pack_type === "challenges";
  const canInstall =
    !!resolved && resolved.installable && (!needsCompetition || !!competitionId);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("importHeading")}</CardTitle>
        <CardDescription>{t("importDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <form onSubmit={onResolve} className="flex items-end gap-2">
          <div className="grid flex-1 gap-2">
            <Label htmlFor="mkt-code">{t("codeLabel")}</Label>
            <Input
              id="mkt-code"
              value={code}
              onChange={(e) => {
                setCode(e.target.value);
                setResolved(null);
              }}
              placeholder={t("codePlaceholder")}
            />
          </div>
          <Button type="submit" disabled={!code.trim() || resolve.isPending}>
            {resolve.isPending ? t("resolving") : t("resolve")}
          </Button>
        </form>

        {resolved && (
          <div className="grid gap-3 rounded-md border border-border bg-muted/30 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{resolved.name}</span>
              <span className="text-sm text-muted-foreground">v{resolved.version}</span>
              <Badge variant={resolved.signature_present ? "default" : "secondary"}>
                {resolved.signature_present ? t("signed") : t("unsigned")}
              </Badge>
              {resolved.trust_tier && <Badge variant="outline">{resolved.trust_tier}</Badge>}
            </div>
            {typeof resolved.publisher.name === "string" && (
              <p className="text-sm text-muted-foreground">
                {t("publisher", { name: resolved.publisher.name })}
              </p>
            )}
            {resolved.capabilities.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {t("capabilities", { list: resolved.capabilities.join(", ") })}
              </p>
            )}

            {!resolved.installable && (
              <p className="text-sm text-warning">{t("notInstallable")}</p>
            )}

            {needsCompetition && (
              <div className="grid gap-2">
                <Label htmlFor="mkt-comp">{t("targetCompetition")}</Label>
                <Select
                  id="mkt-comp"
                  value={competitionId}
                  onChange={(e) => setCompetitionId(e.target.value)}
                  className="max-w-xs"
                >
                  <option value="">{t("selectCompetition")}</option>
                  {comps.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </div>
            )}

            <div className="flex gap-2">
              <Button onClick={onInstall} disabled={!canInstall || install.isPending}>
                {install.isPending ? t("installing") : t("install")}
              </Button>
              <Button variant="outline" onClick={() => setResolved(null)}>
                {t("cancel")}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SettingsCard() {
  const settings = useMarketplaceSettings();
  if (settings.isLoading || !settings.data) {
    return <Skeleton className="h-80 w-full" />;
  }
  return <SettingsForm data={settings.data} />;
}

function SettingsForm({ data }: { data: MarketplaceSettings }) {
  const t = useTranslations("admin.marketplace");
  const update = useUpdateMarketplaceSettings();
  const [enabled, setEnabled] = useState(data.enabled);
  const [registryUrl, setRegistryUrl] = useState(data.registry_url);
  const [trustPolicy, setTrustPolicy] = useState(data.trust_policy);
  const [maxTier, setMaxTier] = useState(data.max_trust_tier);
  const [keys, setKeys] = useState<MarketplaceTrustedKey[]>(data.trusted_keys);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    update.mutate(
      {
        enabled,
        registry_url: registryUrl.trim(),
        trust_policy: trustPolicy,
        max_trust_tier: maxTier,
        trusted_keys: keys,
      },
      {
        onSuccess: () => toast(t("settingsSaved"), { variant: "success" }),
        onError: (err) =>
          toast(t("couldntSave"), { description: (err as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle>{t("settingsHeading")}</CardTitle>
          <CardDescription>{t("settingsDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="mkt-enabled">{t("enabled")}</Label>
            <Select
              id="mkt-enabled"
              value={enabled ? "on" : "off"}
              onChange={(e) => setEnabled(e.target.value === "on")}
              className="max-w-xs"
            >
              <option value="on">{t("enabledOn")}</option>
              <option value="off">{t("enabledOff")}</option>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="mkt-url">{t("registryUrl")}</Label>
            <Input
              id="mkt-url"
              value={registryUrl}
              onChange={(e) => setRegistryUrl(e.target.value)}
              placeholder="https://marketplace.flagpost.io"
            />
            <p className="text-xs text-muted-foreground">{t("registryUrlDescription")}</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="mkt-policy">{t("trustPolicy")}</Label>
            <Select
              id="mkt-policy"
              value={trustPolicy}
              onChange={(e) => setTrustPolicy(e.target.value)}
              className="max-w-xs"
            >
              <option value="official">{t("policy_official")}</option>
              <option value="verified">{t("policy_verified")}</option>
              <option value="signed">{t("policy_signed")}</option>
              <option value="any">{t("policy_any")}</option>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="mkt-tier">{t("maxTier")}</Label>
            <Select
              id="mkt-tier"
              value={maxTier}
              onChange={(e) => setMaxTier(e.target.value)}
              className="max-w-xs"
            >
              <option value="pack">{t("tier_pack")}</option>
              <option value="declarative">{t("tier_declarative")}</option>
              <option value="code">{t("tier_code")}</option>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("trustedKeys")}</CardTitle>
          <CardDescription>{t("trustedKeysDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <TrustedKeysEditor values={keys} onChange={setKeys} />
        </CardContent>
      </Card>

      <Button type="submit" className="w-fit" disabled={update.isPending}>
        {update.isPending ? t("saving") : t("save")}
      </Button>
    </form>
  );
}

function TrustedKeysEditor({
  values,
  onChange,
}: {
  values: MarketplaceTrustedKey[];
  onChange: (keys: MarketplaceTrustedKey[]) => void;
}) {
  const t = useTranslations("admin.marketplace");
  const [keyId, setKeyId] = useState("");
  const [publicKey, setPublicKey] = useState("");
  const [label, setLabel] = useState("");
  const [verified, setVerified] = useState(false);

  function add() {
    if (!keyId.trim() || !publicKey.trim()) return;
    onChange([
      ...values,
      { key_id: keyId.trim(), public_key: publicKey.trim(), verified, label: label.trim() || null },
    ]);
    setKeyId("");
    setPublicKey("");
    setLabel("");
    setVerified(false);
  }

  return (
    <div className="grid gap-3">
      {values.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("noKeys")}</p>
      ) : (
        <ul className="grid gap-1.5">
          {values.map((k) => (
            <li
              key={k.key_id}
              className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm"
            >
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-mono">{k.key_id}</span>
                {k.label && <span className="text-muted-foreground">{k.label}</span>}
                {k.verified && <Badge variant="default">{t("verifiedBadge")}</Badge>}
              </span>
              <button
                type="button"
                onClick={() => onChange(values.filter((x) => x.key_id !== k.key_id))}
                className="text-muted-foreground hover:text-destructive"
                aria-label={t("removeKeyAria", { keyId: k.key_id })}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-2 rounded-md border border-dashed border-border p-3">
        <div className="grid gap-2 sm:grid-cols-2">
          <Input value={keyId} onChange={(e) => setKeyId(e.target.value)} placeholder={t("keyId")} />
          <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("keyLabel")} />
        </div>
        <Input
          value={publicKey}
          onChange={(e) => setPublicKey(e.target.value)}
          placeholder={t("publicKey")}
          className="font-mono"
        />
        <div className="flex items-center justify-between gap-2">
          <Select
            value={verified ? "yes" : "no"}
            onChange={(e) => setVerified(e.target.value === "yes")}
            className="max-w-xs"
          >
            <option value="no">{t("verifiedNo")}</option>
            <option value="yes">{t("verifiedYes")}</option>
          </Select>
          <Button type="button" variant="outline" onClick={add} disabled={!keyId.trim() || !publicKey.trim()}>
            {t("addKey")}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function MarketplaceAdminPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <MarketplaceInner />
    </Suspense>
  );
}
