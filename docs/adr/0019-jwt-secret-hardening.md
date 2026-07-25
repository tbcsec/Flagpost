# ADR-0019: Derive a per-install JWT secret instead of shipping a public default

**Status:** Accepted
**Date:** 2026-07-25
**Architecture reference:** `ARCHITECTURE.md` §7.7 (auth), ADR-0003 (JWT
access + refresh), ADR-0008 (stateful refresh sessions)

## Context

Auth tokens are HS256-signed (ADR-0003), so `JWT_SECRET` is the entire root
of trust for authentication: anyone who knows it can mint a valid access token
for any account, including Administrator. For local dev and `docker compose`
first-run to work with zero configuration, `config.py` shipped a **default**
secret value — which means that default is *public knowledge* the moment the
repo is public. An operator who deploys without setting `JWT_SECRET` (a single
forgotten env var) is then signing every token with a value printed in the
source tree. That's not a weak secret; it's a *known* one — a silent, complete
authentication bypass and privilege escalation, indistinguishable from a
correct install until someone forges an admin token. The Tier 3 Phase 10
pre-public security review flagged this as the highest-severity finding.

The real options were:

1. **Status quo — rely on the operator to set `JWT_SECRET`.** A loud comment
   and hope. One missed env var = total compromise, with no runtime signal that
   anything is wrong. Rejected: "secure only if every operator reads the docs"
   is not a security property.
2. **Fail hard at startup** if the secret is unset or a known default — refuse
   to boot. Safe, but it breaks the zero-config promise: `uvicorn main:app` and
   `docker compose up` would both require the operator to generate and wire a
   secret before the app runs at all, for dev and prod alike. High friction on
   the exact first-run path we want to stay frictionless.
3. **Auto-derive a strong per-install secret** when the configured value is
   unset or a known public default, and persist it so tokens survive restarts.
   Keeps zero-config dev working while guaranteeing no deployment ever signs
   with a repo-public value.

## Decision

Option 3. `config._resolve_jwt_secret`, applied through a pydantic
`model_validator(mode="after")` so every code path that reads
`settings.jwt_secret` sees the hardened value:

- An **explicit, non-default** `JWT_SECRET` always wins — production and
  multi-host deployments set it and nothing changes for them.
- Otherwise (unset, or one of the enumerated known-public defaults in
  `_INSECURE_JWT_DEFAULTS`), generate a strong secret (`secrets.token_urlsafe(64)`)
  and **persist it** to `JWT_SECRET_FILE` (default: next to `config.py`;
  docker-compose points it at a mounted volume, `/data/.jwt_secret`, so it also
  survives container recreation), `chmod 0600`, and log a warning naming the
  file and telling the operator to set `JWT_SECRET` explicitly for multi-host.
- If that file can't be written (read-only filesystem), fall back to an
  **ephemeral per-process** secret — sessions won't survive a restart, but the
  app still never signs with a public default.

The known public defaults are treated as "unset" precisely because publishing
them made them worthless as secrets. HS256 is unchanged (ADR-0003); this ADR is
only about where the key comes from, not the algorithm.

## Consequences

- **Positive:** no deployment — not even a zero-config one — can run on a
  forgeable, repo-public auth root of trust. The frictionless dev/compose
  first-run is preserved, and a generated secret is persisted so tokens (and
  therefore sessions) survive normal restarts. The fix is centralized: one
  validator hardens the value for every consumer, rather than scattering checks
  through the auth code.
- **Negative / cost:** multi-host / replicated deployments **must** set
  `JWT_SECRET` explicitly — otherwise each replica generates its own secret and
  rejects tokens signed by its peers (documented in the startup warning and the
  `config.py` comment). The persisted secret file is sensitive key material and
  must be protected like any key (hence `0600` + a mounted volume, not object
  storage). A read-only filesystem silently degrades to ephemeral secrets, so
  every restart invalidates outstanding sessions there — an acceptable, still-safe
  fallback, but a surprising one if not expected.
- **Forecloses:** nothing structural — an operator can always override with an
  explicit `JWT_SECRET`. This does **not** provide secret *rotation* (rotating
  invalidates all live tokens; a graceful multi-key rotation scheme is a separate,
  unbuilt concern) and does not move auth to asymmetric keys (RS256/EdDSA); HS256
  with a single shared secret stays the model per ADR-0003.
