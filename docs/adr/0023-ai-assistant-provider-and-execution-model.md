# ADR-0023: AI assistant provider integration and execution model

**Status:** Accepted
**Date:** 2026-08-05
**Architecture reference:** `ARCHITECTURE.md` §12 (AI Integration); reuses the
secret-at-rest facility of ADR-0020; scopes egress against ADR-0013; execution
identity per §6.2 (tenancy) and §7 (RBAC). Full design in
`docs/claude_plans/issue-98-ai-assistants.md` and the spec attached to #98.

## Context

v1.4.0 adds the optional `ai` module (#98): an administrator assistant and a
competitor assistant. Three of its decisions are hard to reverse and cut across
modules, so they are recorded here; the rest of the design (guidance levels, UX,
data model, delivery sequence) lives in the design doc and the issue spec.

The tensions that forced each:

1. **What does Flagpost integrate against?** Ship a bundled model? Hold a
   Flagpost-managed API key? Or bring-your-own? Flagpost is self-hosted software,
   frequently run air-gapped or under privacy constraints (educators, potentially
   minors' data). A bundled model or a managed key would create a vendor
   dependency, a cost centre, and a data-processing relationship the project has
   no business owning.
2. **How much authority does the assistant hold over data?** A CTF competitor is
   an adversarial user by design and will treat the assistant as an unofficial
   extra challenge within the first hour. Prompt injection is the *expected* case,
   not an edge case — so "the model behaves" cannot be a security control.
3. **The self-hosted target is a local inference server** (Ollama, vLLM) on the
   internal network — `http://ollama.internal:11434`, a loopback/private address,
   which is exactly the class our webhook SSRF guard (ADR-0013) refuses.

## Decision

### 1. Bring-your-own OpenAI-compatible endpoint

Flagpost ships **no model, no key, and no vendor SDK**. The operator configures a
`base_url`, an optional `api_key`, and a `model` against **one** integration
surface: the OpenAI-compatible `POST {base_url}/chat/completions` API, including
its tool-calling and SSE streaming sub-protocols. That single surface covers
OpenAI, Anthropic's compatibility endpoint, Azure, OpenRouter — and, critically,
the self-hosted set: Ollama, vLLM, LM Studio, LiteLLM. The `api_key` is stored
**encrypted** (ADR-0020, `EncryptedString`) and is write-only over the API, the
same treatment as the SMTP password and the OIDC/SAML/LDAP provider secrets; it
never reaches the browser. No per-provider native adapters in v1.

### 2. Tools execute as the requesting caller, read-only

Every assistant tool call runs **as the requesting user, under their RBAC
permissions and `competition_id` scope — never a service account**. In v1 there
are **no write tools, no automation-triggering tools, and no model-authored
queries**. The guarantee is architectural, not prompt-based — the design axiom is
*the prompt is a courtesy, the architecture is the guarantee*: a fully jailbroken
assistant can at most read what the human asking could already read, and can
mutate nothing, so "every mutation emits an event" (§3) is untouched. The
competitor-facing tools reuse the existing public serialization paths
(`ChallengeOut` and the visibility queries), so flag material, hidden hints,
correct multiple-choice options, and unpublished challenges are **structurally
unreachable** — never fetched, not filtered after the fact.

### 3. The provider `base_url` is exempt from the ADR-0013 SSRF blocklist

The AI endpoint is a **trusted operator setting in the same class as the SMTP
host and the OIDC issuer**: it is set only by an administrator holding the
provider permission, is never derived from competitor-controlled input, and
pointing it at a loopback or private address (a local inference server) is the
*intended* use, not an attack. It therefore does **not** pass through
`webhook_security.validate_webhook_url`. The webhook blocklist stays exactly as
ADR-0013 defines it for webhooks — whose targets are reachable via
competitor-triggered automation rules and whose substituted values are
adversarial. This exemption is deliberate and load-bearing for self-hosted
deployments and must not be "hardened" away.

## Consequences

- **Positive:** no vendor lock-in, no cost centre, no data-processing
  relationship owned by the project; a genuinely private deployment story
  ("self-hosted Flagpost + local model = no data leaves the building"); prompt
  injection is survivable by construction, bounded to reads the caller could
  already perform and to zero writes; one integration surface instead of a
  matrix of provider adapters; the encrypted-secret and provider-config patterns
  are reused wholesale rather than reinvented.
- **Negative / cost:** "OpenAI-compatible" is a spectrum, not a spec — tool-call
  support and SSE framing vary across local models, so a **test-connection**
  probe (a trivial completion *and* a forced tool call, reported separately) and
  a defensive streaming proxy are required, and token accounting needs a
  fallback for endpoints that omit `usage`. The execution-as-caller guarantee is
  not free: permission checks currently live in the FastAPI route layer, so each
  tool must re-check `user_has_permission` and several reads need extraction into
  reusable, permission-aware service functions first. The SSRF exemption widens
  egress for one operator-set field; the mitigation is precisely that the field
  is admin-only and non-adversarial, unlike a webhook target.
- **Forecloses (v1):** per-provider native adapters (Anthropic/Gemini native
  APIs), write-capable or automation-adjacent tools, embeddings/RAG, multi-model
  routing, and any cross-competition/global assistant (which additionally waits
  on the §6.3 consolidation views).
