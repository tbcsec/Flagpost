# ADR-0013: Webhook action egress policy — SSRF blocklist + value hardening

**Status:** Accepted
**Date:** 2026-07-22
**Architecture reference:** `ARCHITECTURE.md` §5.4 (implements it); §15 (leaves
the rate-limiting question open)

## Context

The automation engine's `webhook` action (§5.3) makes an outbound HTTP request
to an **admin-authored** URL, with **competitor-authored** values (team names,
challenge titles, ticket subjects) substituted into its body/headers. That
combination is more dangerous on a CTF platform than on most SaaS: team and
challenge names are adversarial input by design, and the request originates
from *inside* the deployment's network. §5.4 spells out four required
hardenings; this ADR records how they're implemented and, more importantly,
what is deliberately **not** yet covered, so the residual risk isn't rediscovered
as a surprise.

Two design forks had real alternatives:

- **SSRF: allowlist vs blocklist.** An allowlist of permitted destinations is
  stricter but wrong for this feature — organisers point rules at arbitrary
  Slack/Discord/custom endpoints we can't enumerate ahead of time. So it's a
  **blocklist of non-routable IP ranges**, checked against the *resolved*
  address(es), not the hostname string.
- **When to validate.** At rule-save only (cheap, but a hostname can be
  re-pointed at an internal IP after approval — DNS rebinding), or on **every
  call** (a little DNS cost per fire). §5.4 explicitly says "before every
  call", so it's per-call.

## Decision

Implement all four §5.4 hardenings in `utils/webhook_security.py`, applied by
`_execute_webhook`:

1. **Per-call SSRF blocklist.** Resolve the URL host and reject if **any**
   resolved IP is loopback / private / link-local (incl. the
   `169.254.169.254` metadata endpoint) / reserved / multicast / unspecified;
   IPv4-mapped IPv6 is unwrapped first. An unresolvable host is refused (can't
   prove safe). Only `http`/`https`. The caller keeps redirects off so a `302`
   can't bounce past the check.
2. **Header stripping.** `Authorization`, `Cookie`, `Host`, `Forwarded`,
   `X-Real-IP`, and `X-Forwarded-*` are dropped from the admin header set;
   `Content-Type`/`Content-Length` are owned by the sender.
3. **Content-Type-aware value escaping.** Substituted values are JSON-string /
   percent / plain escaped for the declared body type, so a value with quotes
   can't inject sibling JSON keys.
4. **Chat-token defang.** Discord `@everyone`/`@here`/`@channel`, Slack
   `<!…>`/`<@…>`/`<#…>`, and markdown links are broken with a zero-width space
   in substituted values before they can reach a chat webhook.

Escaping + defang apply to **template-body** webhooks (where an admin builds a
message with `{field}` placeholders). A webhook with no `body_template` sends
the structured event as `json=` (serialisation-safe) to a generic endpoint and
carries no admin-built message for a value to break out of.

## Consequences

- Positive: the four adversarial-input classes §5.4 names are closed; the SSRF
  check is DNS-rebinding-aware (all resolved IPs, every call) and defeats the
  redirect bounce.
- Negative / residual risk (carried forward, not hidden):
  - **Resolve-then-connect TOCTOU.** Validation resolves the host, then httpx
    resolves again to connect — a rebind in that window isn't caught. Closing
    it needs pinning the connection to the validated IP (custom transport);
    deferred as a deeper hardening. The per-call check already removes the
    much larger rule-save-only hole.
    - **No destination rate-limiting / coalescing / runaway-loop specifics** —
    that's the still-open §15 question (a rule can legitimately fire thousands
    of times on a large event, so a naive cap is wrong). The engine's
    cascade-depth guard (ADR-0012/Phase 1) bounds *rule-chain* loops, not
    destination volume.
- Forecloses nothing: connection pinning and the §15 rate scheme are additive
  on top of this module.
