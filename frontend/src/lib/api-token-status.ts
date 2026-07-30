// Derives a personal API token's (issue #75) display status. Pure so it's
// unit-testable and shared between the admin panel and the /profile
// self-service card rather than duplicated.

export type ApiTokenStatus = {
  label: "Active" | "Expired" | "Revoked";
  variant: "success" | "destructive" | "muted";
};

export function apiTokenStatus(token: {
  expires_at: string;
  revoked_at: string | null;
}): ApiTokenStatus {
  if (token.revoked_at) return { label: "Revoked", variant: "muted" };
  if (new Date(token.expires_at).getTime() < Date.now()) {
    return { label: "Expired", variant: "destructive" };
  }
  return { label: "Active", variant: "success" };
}
