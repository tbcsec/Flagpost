"use client";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useAiSettings,
  useTestAiConnection,
  useUpdateAiSettings,
} from "@/lib/hooks/use-ai";
import type { AiConnectionResult, AiSettings, AiSettingsUpdate } from "@/lib/types";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast";

// Admin → Site settings → AI (#98, ADR-0023, Phase 2). The site-wide provider
// config for a bring-your-own OpenAI-compatible endpoint. The API key is
// write-only, exactly like the SMTP password: only whether one is stored is
// read back, an empty field leaves it untouched, and "clear" sends "".
//
// Only the administrator-assistant controls are surfaced — the competitor
// assistant and its guidance levels arrive in a later phase, so their columns
// (competitor prompt, guidance default) aren't shown yet even though the API
// carries them.
export function AiSettingsPanel() {
  const { data, isLoading } = useAiSettings();
  if (isLoading || !data) return <Skeleton className="h-64 w-full" />;
  // Reseed the form from the server after each save (clears the write-only key
  // field) by remounting on the row's save timestamp — the same trick the SMTP
  // form uses.
  return <AiSettingsForm key={data.updated_at ?? "initial"} data={data} />;
}

function AiSettingsForm({ data }: { data: AiSettings }) {
  const update = useUpdateAiSettings();
  const test = useTestAiConnection();

  const [enabled, setEnabled] = useState(data.enabled);
  const [baseUrl, setBaseUrl] = useState(data.base_url ?? "");
  const [model, setModel] = useState(data.model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [maxTokens, setMaxTokens] = useState(String(data.max_output_tokens));
  const [timeout, setTimeoutS] = useState(String(data.request_timeout_s));
  const [adminPrompt, setAdminPrompt] = useState(data.admin_prompt_override ?? "");
  const [result, setResult] = useState<AiConnectionResult | null>(null);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // Mirror the server invariant for instant feedback: no "enabled but
    // unconfigured" state is reachable.
    if (enabled && (!baseUrl.trim() || !model.trim())) {
      toast("Set a base URL and model before enabling the AI module", {
        variant: "destructive",
      });
      return;
    }
    const payload: AiSettingsUpdate = {
      enabled,
      base_url: baseUrl.trim() || null,
      model: model.trim() || null,
      max_output_tokens: Math.min(32000, Math.max(1, Number(maxTokens) || 1024)),
      request_timeout_s: Math.min(600, Math.max(1, Number(timeout) || 60)),
      admin_prompt_override: adminPrompt.trim() || null,
      // Only touch the key when the admin typed a new one or asked to clear it.
      ...(clearKey ? { api_key: "" } : apiKey ? { api_key: apiKey } : {}),
    };
    update.mutate(payload, {
      onSuccess: () => toast("AI settings saved", { variant: "success" }),
      onError: (err) =>
        toast("Couldn't save", {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  function onTest() {
    setResult(null);
    test.mutate(undefined, {
      onSuccess: (r) => setResult(r),
      onError: (err) =>
        toast("Couldn't test the connection", {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  const keyPlaceholder = clearKey
    ? "Will be cleared on save"
    : data.api_key_set
      ? "•••••••• (unchanged)"
      : "Not set — leave blank for a keyless endpoint";

  return (
    <form onSubmit={onSubmit} className="grid max-w-2xl gap-5">
      <Card>
        <CardHeader>
          <CardTitle>Provider</CardTitle>
          <CardDescription>
            Point Flagpost at any OpenAI-compatible chat-completions endpoint —
            a hosted API or a local model (Ollama, vLLM, LM Studio). The model
            must support tool calling; the assistant answers entirely through
            read-only tools. The base URL is a trusted operator setting, so it is
            not subject to the outbound-request blocklist a local address needs.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="ai-enabled">Status</Label>
            <Select
              id="ai-enabled"
              value={enabled ? "on" : "off"}
              onChange={(e) => setEnabled(e.target.value === "on")}
              className="max-w-xs"
            >
              <option value="off">Off — the assistants are unavailable</option>
              <option value="on">On — enable the assistants</option>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ai-base-url">Base URL</Label>
            <Input
              id="ai-base-url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
              autoComplete="off"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ai-model">Model</Label>
            <Input
              id="ai-model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="gpt-4o-mini"
              autoComplete="off"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ai-key">API key</Label>
            <Input
              id="ai-key"
              type="password"
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                if (e.target.value) setClearKey(false);
              }}
              disabled={clearKey}
              autoComplete="new-password"
              placeholder={keyPlaceholder}
            />
            {data.api_key_set && (
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={clearKey}
                  onChange={(e) => {
                    setClearKey(e.target.checked);
                    if (e.target.checked) setApiKey("");
                  }}
                />
                Remove the stored key (use a keyless endpoint)
              </label>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Response limits</CardTitle>
          <CardDescription>
            Caps that bound each answer&apos;s length and how long Flagpost waits
            on the provider — the guardrails against a slow endpoint or a runaway
            token bill.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3">
          <div className="grid gap-2">
            <Label htmlFor="ai-max-tokens">Max output tokens</Label>
            <Input
              id="ai-max-tokens"
              type="number"
              min={1}
              max={32000}
              value={maxTokens}
              onChange={(e) => setMaxTokens(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ai-timeout">Request timeout (seconds)</Label>
            <Input
              id="ai-timeout"
              type="number"
              min={1}
              max={600}
              value={timeout}
              onChange={(e) => setTimeoutS(e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Administrator assistant prompt</CardTitle>
          <CardDescription>
            An optional override for the assistant&apos;s system prompt. It
            governs tone and focus only — the assistant is read-only and every
            tool re-checks your permissions, so no wording can widen what it can
            see. Leave blank to use the built-in prompt.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <textarea
            id="ai-admin-prompt"
            value={adminPrompt}
            onChange={(e) => setAdminPrompt(e.target.value)}
            rows={5}
            maxLength={20000}
            placeholder="Use the built-in administrator-assistant prompt."
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" className="w-fit" disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save changes"}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onTest}
          disabled={test.isPending || !data.base_url || !data.model}
          title={
            !data.base_url || !data.model
              ? "Save a base URL and model first"
              : "Probe the saved configuration"
          }
        >
          {test.isPending ? "Testing…" : "Test connection"}
        </Button>
        {data.updated_at && (
          <span className="text-xs text-muted-foreground">
            Last saved {new Date(data.updated_at).toLocaleString()}
          </span>
        )}
      </div>

      {result && <TestResult result={result} />}
    </form>
  );
}

/** The two-leg probe result: a completion and a forced tool call, reported
 *  apart so an operator sees the common "model can't tool-call" gap directly. */
function TestResult({ result }: { result: AiConnectionResult }) {
  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle className="text-base">
          Connection test — <span className="font-mono text-sm">{result.model}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <TestLeg label="Completion" check={result.completion} />
        <TestLeg label="Tool calling" check={result.tool_call} />
      </CardContent>
    </Card>
  );
}

function TestLeg({
  label,
  check,
}: {
  label: string;
  check: { ok: boolean; detail: string };
}) {
  return (
    <div className="grid gap-1">
      <div className="flex items-center gap-2">
        <Badge variant={check.ok ? "success" : "destructive"}>
          {check.ok ? "OK" : "Failed"}
        </Badge>
        <span className="text-sm font-medium">{label}</span>
      </div>
      <p className={cn("text-xs", check.ok ? "text-muted-foreground" : "text-destructive")}>
        {check.detail}
      </p>
    </div>
  );
}
