// Post-auth return-path validation (#427, shared with the SSO callback).
//
// A `?next=` is attacker-influenceable (it arrives in a URL someone was handed),
// so it may only ever be a same-origin absolute path. The regex matches the
// backend's `_safe_return_to` (routers/oidc.py) deliberately: "starts with / but
// not //" alone misses `/\evil.com`, which browsers normalise into a
// protocol-relative URL. Frontend validation here is the second lock on the SSO
// path (the backend validates return_to too) and the only lock on the local
// login/register forms, which never round-trip the value through a server.

const SAFE_NEXT = /^\/(?!\/)[A-Za-z0-9\-._~!$&'()*+,;=:@%/?#[\]]*$/;
const MAX_LENGTH = 512; // mirror the backend cap

/** The validated same-origin path, or null when the value is absent/unsafe. */
export function safeNextPath(raw: string | null | undefined): string | null {
  if (!raw || raw.length > MAX_LENGTH) return null;
  return SAFE_NEXT.test(raw) ? raw : null;
}
