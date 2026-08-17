// Derives a personal API token's (issue #75) display status. Pure so it's
// unit-testable and shared between the admin panel and the /profile
// self-service card rather than duplicated.

export type ApiTokenStatus = {
  /** Key into profile.tokens.status.* — extracted callers translate through it. */
  key: "active" | "expired" | "revoked";
  /** English label, transitional: still consumed by the not-yet-extracted admin
   *  tokens panel; drop when that surface reaches next-intl (ADR-0029). */
  label: "Active" | "Expired" | "Revoked";
  variant: "success" | "destructive" | "muted";
};

export function apiTokenStatus(token: {
  expires_at: string;
  revoked_at: string | null;
}): ApiTokenStatus {
  if (token.revoked_at) return { key: "revoked", label: "Revoked", variant: "muted" };
  if (new Date(token.expires_at).getTime() < Date.now()) {
    return { key: "expired", label: "Expired", variant: "destructive" };
  }
  return { key: "active", label: "Active", variant: "success" };
}
