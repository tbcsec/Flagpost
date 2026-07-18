# ADR-0008: Refresh tokens are stateful, hashed, rotating DB sessions

**Status:** Accepted
**Date:** 2026-07-18
**Architecture reference:** `ARCHITECTURE.md` §7.7 (refines ADR-0003)

## Context

ADR-0003 settled that auth uses short-lived JWT access tokens plus a
longer-lived refresh token in an httpOnly cookie. It did *not* settle
whether the refresh token is itself a self-contained JWT (stateless) or a
handle to server-side session state, nor how logout and revocation work.
That gap had to be closed to build login/logout at all.

The tension: a purely stateless refresh JWT is simple and DB-free, but it
cannot be revoked before it expires. "Log me out," "log out my other
devices," and "this refresh token was stolen" all require the server to be
able to invalidate a refresh credential on demand — impossible if the only
proof of validity is the token's own signature.

## Decision

Refresh tokens are **stateful**. Each is a high-entropy opaque random
string handed to the client in the httpOnly cookie; the server stores only
its SHA-256 hash in a `refresh_sessions` row (`user_id`, `token_hash`,
`expires_at`, `revoked_at`). On every refresh the presented session is
revoked and a fresh one issued (**rotation**); logout revokes the current
session. Access tokens stay stateless JWTs — they are *not* checked against
the DB on each request.

## Consequences

- Positive: logout and revocation actually work, and rotation bounds the
  usefulness of a stolen refresh token to the window until the next
  legitimate refresh (after which the stolen copy is already revoked).
- Positive: the DB never stores a usable credential — only a hash — so a
  database disclosure doesn't hand out working refresh tokens. Access
  tokens remain verifiable offline, so the per-request hot path adds no DB
  lookup; only the (infrequent) refresh call touches `refresh_sessions`.
- Negative / cost: `refresh_sessions` grows over time and needs periodic
  pruning of expired/revoked rows — housekeeping that isn't built yet.
  Access-token revocation is still not immediate: a compromised *access*
  token remains valid until it expires (mitigated by the short, ~15-minute
  TTL from ADR-0003), because revocation acts on the refresh session, not
  the access token.
- Forecloses: purely-stateless auth (no server session state), given up
  deliberately in exchange for revocability. If horizontal scaling makes
  the per-refresh DB write a bottleneck, the session store can move to
  Redis without changing this contract — the decision is "refresh is
  stateful," not "refresh state lives in Postgres specifically."
