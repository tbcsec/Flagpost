# ADR-0003: JWT access + refresh tokens, shared across REST and WebSocket

**Status:** Accepted
**Date:** 2026-07-17
**Architecture reference:** `ARCHITECTURE.md` §4.1, §7.7

## Context

RBAC (§7) needs a resolved, trustworthy `current_user` before any
permission check means anything, and that identity has to work across
two transports: ordinary REST requests and the WebSocket connections the
real-time layer (§4) depends on for presence, live updates, and
collaborative editing. Two separate concerns had to be settled together:
how identity is issued/refreshed at all, and whether REST and WebSocket
need separate auth schemes.

## Decision

Use JWT access tokens (short-lived, e.g. 15 minutes) paired with a
longer-lived refresh token issued at login and stored as an httpOnly
cookie — never `localStorage`, so it isn't readable by injected or
third-party JS. The same access token is reused for both transports:
`Authorization: Bearer` header for REST, and the first frame sent after
a WebSocket connects (§4.1) — never a WS-specific token type, and never
a token embedded in the WS URL as a query parameter (URL-embedded tokens
leak into proxy logs, browser history, and the `Referer` header).

## Consequences

- Positive: one issuance and refresh path to reason about instead of
  two, and one place (`require_permission`, §7.6) that resolves identity
  for every permission check regardless of which transport the request
  arrived over.
- Positive: the WebSocket first-frame handshake closes off an entire
  class of token-leak vector that a query-parameter approach would leave
  open, at no extra implementation cost over choosing the leaky approach.
- Negative / cost: a WebSocket connection has a few-hundred-millisecond
  window between `connect` and the auth frame being processed where the
  server has accepted a connection it doesn't yet trust — has to be
  bounded (a short server-side timeout that closes the connection if no
  auth frame arrives) rather than left open-ended.
- Forecloses: session-cookie-only auth (no bearer token at all), which
  would have been simpler for REST but doesn't extend cleanly to the WS
  handshake pattern chosen here. SSO providers (§7.7, deferred) plug
  into this same "produces a `current_user` and a session" contract
  rather than requiring a second auth path later.
