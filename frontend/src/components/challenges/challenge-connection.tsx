"use client";

// Where a competitor connects to a challenge's live service (#262), shown in the
// challenge detail dialog under the description.
//
// The value is free-form by design (it mirrors ctfcli's `connection_info`): it
// may be a URL, a `host:port`, or plain instructions. Display follows CTFd's own
// rule so challenges imported from a ctfcli repo render the way their authors
// expect — a value starting with `http` becomes a link, anything else is shown
// monospace. Either way it's copyable, because retyping a hostname under time
// pressure is how competitors lose minutes to typos.
//
// This component does NOT decide visibility: the server withholds the field for
// a locked challenge (routers.challenges._redact_for_competitor), so if the
// value reached the client it is meant to be readable.

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { toast } from "@/stores/toast";

/** A URL we're willing to render as a link. Anything else — `nc host 1337`,
 *  free-text instructions — stays inert text. Deliberately narrower than
 *  CTFd's `startswith("http")`: that would linkify `httpfoo`, and we won't
 *  render a `javascript:`/`data:` value as a clickable link. */
function asHref(value: string): string | null {
  if (!/^https?:\/\/\S+$/i.test(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

export function ChallengeConnection({ value }: { value: string }) {
  const t = useTranslations("challenges.detail");
  const [copied, setCopied] = useState(false);
  const href = asHref(value);

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast(t("connectionCopyError"), { variant: "destructive" });
    }
  }

  return (
    <div className="grid gap-2 border-t border-border pt-4">
      <span className="text-[13px] font-semibold">{t("connection")}</span>
      <div className="flex items-center gap-2">
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="w-fit break-all rounded-md bg-muted px-3 py-1.5 font-mono text-sm text-primary underline underline-offset-2"
          >
            {value}
          </a>
        ) : (
          <p className="w-fit break-all rounded-md bg-muted px-3 py-1.5 font-mono text-sm">
            {value}
          </p>
        )}
        <Button type="button" size="sm" variant="outline" onClick={onCopy}>
          {copied ? t("connectionCopied") : t("connectionCopy")}
        </Button>
      </div>
    </div>
  );
}
