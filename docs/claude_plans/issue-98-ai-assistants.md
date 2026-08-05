# Design: AI Assistants Module (`ai`) — self-hosted architecture & delivery plan

**Issue:** #98 · **Milestone:** v1.4.0 · **Status:** in design (no code yet)
**Architecture references:** §12 (AI Integration), §11.3 (module taxonomy), §7
(RBAC), §6.2 (tenancy), §13.2 (flag storage)
**Prior art in the issue:** the full `FEATURE-AI-ASSISTANTS.md` spec is attached
to #98 and is the authority on the security model, guidance levels, and open
questions. **This document does not restate it** — it records what the planning
pass added on top: the self-hosted picture, what was verified against the actual
code, the UX/interaction model, the delivery sequence, and the decisions taken.
Where this doc and the issue spec disagree, this doc is the newer thinking.

---

## 1. What this design commits to

Locked during planning (2026-08-04), not open for re-litigation in build:

- **Both assistants ship in v1** (administrator + competitor), not split across
  releases — but sequenced admin-first *within* the build to de-risk (§9).
- **Bring-your-own OpenAI-compatible endpoint.** One integration surface
  (`POST {base_url}/chat/completions` + its tool-calling and SSE sub-protocols).
  Flagpost ships no model, no key, no vendor dependency. This is what makes
  "self-hosted Flagpost + local Ollama = AI where no data leaves the building"
  real, and it's the headline of the feature, not a footnote.
- **Execution-as-caller (non-negotiable).** Every tool call runs as the
  requesting user under their RBAC permissions and `competition_id` scope, never
  a service account. A fully jailbroken assistant can at most read what the human
  asking could already read.
- **Read-only in v1.** No write tools, no automation-triggering tools, no
  model-authored queries. The "every mutation emits an event" rule is untouched
  because there are no mutations.
- **The prompt is a courtesy, the architecture is the guarantee** (spec axiom).
  No security or data-scoping property depends on prompt wording or model
  behaviour.

---

## 2. How it works in a self-hosted environment

The operator configures three things under Admin → Site settings → AI: a
`base_url`, an optional `api_key`, and a `model` string. That single OpenAI-
compatible surface covers OpenAI, Anthropic's compatibility endpoint, Azure,
OpenRouter — and, for the self-hosted audience, **Ollama, vLLM, LM Studio, and
LiteLLM** on the internal network. Point `base_url` at
`http://ollama.internal:11434/v1`, leave the key blank, and no competitor- or
staff-authored content ever leaves the deployment.

- **The `api_key` is stored encrypted** via `utils/crypto.EncryptedString`
  (ADR-0020, Fernet) — the same write-only-over-the-API treatment as the SMTP
  password and the OIDC/SAML/LDAP provider secrets. It never reaches the browser.
- **The module ships disabled and inert.** New optional module `ai`, same class
  as `feedback`/`automations`. When it's off or the upstream endpoint is dead,
  nothing else degrades (§10 of the spec). No other feature may depend on it.
- **Streaming is proxied server-side over the existing WebSocket layer** (a
  per-conversation room, the same infrastructure as notifications/collab). The
  browser talks to Flagpost; Flagpost talks to the model.

---

## 3. Verified against the code (the load-bearing checks)

Two claims the whole design rests on were checked against the current codebase,
not assumed.

### 3.1 Competitor flag-exclusion is structural today — CONFIRMED

The competitor assistant must be unable, structurally, to see flags, correct
multiple-choice options, hidden hints, unpublished challenges, or solution notes.
This holds in the current code with no new work:

- `ChallengeOut` (`backend/schemas/challenge.py`) is the single canonical public
  challenge serializer. `flag_hash` / `flag_salt` / `flag_regex` are simply never
  declared on it — Pydantic can't emit a field that isn't there. Structural, not
  a filter.
- Multiple-choice: only the public `choices` list is exposed; the correct option
  is stored hashed like a static flag, never marked.
- Hints: `HintRevealOut` sets `body = None` for any hint the subject hasn't
  unlocked.
- Unpublished / not-yet-released challenges are excluded at the query level and
  404 via `load_visible_challenge()`.

**Consequence:** the competitor tool that returns public challenge info reuses
`ChallengeOut` and the existing visibility query — no new serialization, and the
guarantee is inherited, not re-implemented.

### 3.2 Admin-tool permissions live at the route layer — PREREQUISITE WORK

The admin assistant's tools are thin wrappers over existing reads, but the
"execution-as-caller" guarantee is **not free**:

- `compute_scoreboard` (`utils/scoreboard.py`) and `challenge_analytics`
  (`utils/analytics.py`) are already reusable, competition-scoped service
  functions — but the permission checks (`challenge_view`, `scoreboard_freeze`,
  `view_competition_analytics`) and the module-enabled gate live in the FastAPI
  route dependencies, **outside** those functions.
- The ticket, feedback, competition-overview, and announcement reads have their
  logic embedded in routers with private helpers — no reusable service function
  exists.

**Two consequences for the build:**

1. Every AI tool must **explicitly re-check `user_has_permission(...)`** (and any
   module-enabled gate) before calling its backing read. The permission model is
   route-scoped, so calling a service function directly would otherwise skip it.
2. ~4 reads need **extraction into reusable, permission-aware service functions**
   first: tickets (`_load_visible_ticket` + `_ticket_detail`), feedback
   aggregation, competition-overview visibility (`_can_see`), and the
   announcement visibility query. This lands as its own pre-req PR (§9, Phase 0):
   pure extraction plus tests, no behaviour change, reviewable in isolation.

---

## 4. Self-hosted engineering specifics (beyond the spec)

These are where pointing at arbitrary local inference actually bites:

- **SSRF exemption for `base_url` — decided: exempt.** Our webhook egress guard
  (`utils/webhook_security.validate_webhook_url`, ADR-0013) refuses *every*
  loopback/private/link-local address — which is exactly where self-hosted Ollama
  lives. The AI endpoint therefore does **not** go through that guard. It sits in
  the same trust class as the SMTP host and the OIDC issuer: an operator-only
  setting, not adversarial input. An ADR will record this so it isn't
  "hardened" later and made to break every local deployment. (Contrast: the
  webhook target is reachable via competitor-triggered automation rules; the AI
  `base_url` is set only by an admin holding the provider permission.)
- **Tool-calling support varies wildly across local models — the #1 footgun.**
  The admin assistant is entirely tool calls; many small models (7–8B) can't do
  them or do them badly. The spec's **Test connection** action — a trivial
  completion *and* a forced tool call, reported separately — is therefore a
  first-class, must-build part of v1, so an operator discovers the gap before an
  event, not during one.
- **Token accounting can't assume the provider returns usage.** Hosted APIs
  populate `usage`; local endpoints often don't. The usage counter and the
  context-window truncation need a fallback (a local tokenizer estimate) so the
  cost guard and history budget still work against Ollama.
- **"OpenAI-compatible" is a spectrum.** Ollama/vLLM/LiteLLM differ in SSE
  framing, where `usage` lands, and tool-call delta formats. The streaming proxy
  must be defensive rather than assume OpenAI's exact wire format.
- **Guidance-level adherence degrades on small models** — disclosed honestly in
  the UI (the behavioural controls are best-effort layer-4 anyway; the hard
  guarantees are the data-derived ones in §3.1).

---

## 5. Security model

Unchanged from the issue spec §7 — summarised here only for the load-bearing
shape:

- **Five-layer hierarchy; layers 4–5 (system prompt, the model) are never
  load-bearing.** What the model can *see* (layer 1: tool catalogue +
  serialization) and *do* (layer 2: read-only, caller identity) are the hard
  guarantees; the output-side flag-format scan (layer 3) is belt-and-braces.
- **Guidance level and challenge-solving refusals are explicitly semantic
  (layers 4–5), not guarantees** — documented to organisers as "controls how the
  assistant behaves", never "prevents competitors from getting X". Adherence is
  improved by compiled instructions and made *reviewable* by transcript
  visibility; it is not made guaranteed.
- **Challenge-metadata access is a hard, code-enforced data toggle** (default
  off), distinct from the behavioural guidance level. The two must never be
  conflated in the UI or docs.
- **Events** `ai.query` / `ai.error` carry usage metadata, never message content.

---

## 6. UX / interaction model

Decided during planning; an interactive mockup was reviewed and approved.

- **One audience-aware launcher in the app shell.** A single, understated bubble
  (`app-shell.tsx`), present on every in-app page, rendering the assistant
  appropriate to the viewer via the same `useAccess` role-gating the nav already
  uses — admin assistant for staff who hold the permission, competitor assistant
  for participants where the toggle is on, nothing when neither applies or the
  module is off.
- **It must not appear on the `/public/*` (venue/spectator) or auth/setup
  shells** — those have no authenticated caller, and execution-as-caller has no
  principal without one. Clean boundary: those live outside the `(app)` shell.
- **Opens as a docked side panel, not a modal** — the page you're on stays
  visible. **Expandable** to a wide/full view (the admin assistant returns
  data-dense answers a 340px dock renders badly), and the same conversation is
  also addressable as a route for full-screen/mobile. Competitor experience is
  bubble-centric; admin experience graduates to the expanded view.
- **Context-passing policy — decided.** The panel may pass *navigational* context
  ("user is on the scoreboard") but, for the competitor assistant, **never**
  challenge specifics as free context — those may only enter through the guarded
  tool + `ChallengeOut` path, and only when the metadata toggle is on. The admin
  assistant has no such constraint (it executes as the organiser).
- **First-run disclosure** (external model + staff-readable transcripts,
  acceptance recorded) is gated on the competitor's first bubble open.
- **Launcher shows state, doesn't vanish** — an "unavailable" state when the
  endpoint is dead or the competition is outside its availability window (§10),
  rather than disappearing and reading as broken. Holds a WS room only while
  open (concurrent-stream cap is 1).
- **Understated, not salesy** — a plain message glyph, no pulsing "Ask AI". Right
  register for a technical audience, and it keeps the hint channel from being
  pushed.
- **Transcript review is a separate manager page** (permission-gated) — oversight
  tooling, not the live chat.

---

## 7. Data model notes

Per the spec §12 sketch, plus one clarification from the code: the
`competition_modules` table is only an on/off boolean (`models/competition_module.py`).
So the per-competition AI controls (assistant on/off, `guidance_level`, per-level
depth-descriptor overrides, challenge-metadata access) live in an **AI-owned
settings table**, not that toggle — "the module's own settings" means module-owned
storage, the way `feedback`/`automations` own their rule/survey tables. New tables:
`ai_conversations`, `ai_messages`, an AI site-settings row (or keys), and a
per-competition AI settings row. The AI site-settings row also carries the
**`default_guidance_level`** (§10.2) that a per-competition row inherits at
creation and may override. `ai_conversations`/`ai_messages` are competition-scoped
and **follow the competition's archive/retention lifecycle** (§10.4) — no separate
retention timer. All of these stay out of the backup `SPECS` allowlist (they carry
the endpoint secret and competitor content), same posture as the identity-provider
tables.

---

## 8. Rate limiting, cost & degradation

Per spec §9/§10, shipped in v1 (not later): per-user message caps (admin 60/h,
competitor 20/h), one concurrent stream per user, a 20-exchange conversation cap,
oldest-first history truncation to a token budget, a server-side max-token cap
(lower for the competitor), and a per-competition running token counter surfaced
to the organiser. Upstream timeout/5xx → clean "assistant unavailable" + one
retry with backoff, never a crash.

---

## 9. Delivery plan (phased; both assistants in v1)

**Phase 0 — read extraction (pre-req PR, no behaviour change).** Extract
reusable, permission-checking service functions for the reads the admin assistant
needs but that currently live in routers: tickets, feedback aggregate,
competition-overview visibility, announcement visibility. Pure refactor + tests,
reviewable alone. (`compute_scoreboard` / `challenge_analytics` already qualify.)

**Phase 1 — provider plumbing + module scaffold.** The `ai` optional module
(`plugin.yaml` + `setup`); site-settings config (base_url / api_key
[EncryptedString] / model / caps / timeouts / prompt overrides); the OpenAI-
compatible client (SSE streaming + tool-calling, SSRF-exempt egress, defensive
about dialects); the **Test connection** action (completion + forced tool call);
the WS streaming proxy (per-conversation room); `ai.query` / `ai.error` events;
the data model; the rate-limit + usage-counter skeleton with the token-accounting
fallback.

**Phase 2 — administrator assistant.** Tool catalogue wrapping the Phase-0
service reads, each re-checking `user_has_permission` and executing as the caller;
the admin chat UI (bubble + docked panel + expand + route) in the manager
context; the usage-counter surface; injection-smoke and scoping tests.

**Phase 3 — competitor assistant.** Per-competition controls (assistant on/off,
guidance-level enum, editable depth descriptors, challenge-metadata toggle); the
competitor tool catalogue reusing `ChallengeOut` and the public paths; the
output-side flag-format scan; guidance-level prompt compilation with worked-
example tests; the first-run disclosure; the competitor bubble UI; the
transcript-review surface + `ai_view_transcripts` permission; end-to-end against
a local Ollama model and one hosted provider (spec §14).

---

## 10. Decisions taken

Owner decisions, resolved during planning (2026-08-04):

1. **Competitor availability window → active only.** The assistant is offered
   only while the competition is running; the launcher shows an unavailable state
   (and no bubble opens) pre-start and post-end. Simplest gating; no pre-event
   rules Q&A in v1 — a possible fast-follow if demand appears.
2. **Site-level default guidance level → yes.** A site-wide default that new
   competitions inherit at creation and can override. Adds a `default_guidance_level`
   field to the AI site settings and an inherit-then-override read at the
   per-competition layer.
3. **Competitor usage disclosure → organiser-only (v1).** Usage is logged
   (`ai.query`) and staff can review transcripts; there is **no** competitor-facing
   indicator or scoreboard badge in v1. Revisit once there's real usage data.
4. **Transcript retention → follow the competition lifecycle.** Transcripts are
   competition-scoped, so `ai_conversations`/`ai_messages` purge/archive with the
   competition's data under the existing archive-retention policy. No separate AI
   timer, and not blocked on the still-open event-log retention question.

Defaulted with a recommendation (will proceed unless the owner objects):

- **Transcript-review permission:** a new `ai_view_transcripts` — distinct
  sensitivity from analytics/ticket permissions.
- **Level count:** three (`platform_only` / `conceptual` / `guided`); no fourth
  "unrestricted" level — that collapses the product into "we bolted ChatGPT on"
  and invites endpoint abuse (spec §7.5).
- **Depth-descriptor format:** a small structured allow/refuse list compiled to
  prose; revisit after the default descriptors exist.
- **Prompt-override versioning:** when a shipped default prompt changes in an
  upgrade, notify admins holding an override that the baseline moved.
- **History budget:** fixed oldest-first truncation for v1; summarisation deferred
  pending real usage data.

---

## 11. Doc follow-ups when this is scheduled

- Move AI integration off the **Explicitly Deferred** list in `docs/ROADMAP.md`
  into the milestone proper.
- Update the **"Don't build yet"** note in `.claude/CLAUDE.md`.
- Reconcile `docs/ARCHITECTURE.md` §12 with the shipped design, and add an **ADR**
  for the bring-your-own-endpoint + execution-as-caller decisions (and record the
  SSRF exemption there).
- The issue spec header still says "target v1.3.0" — stale; it's v1.4.0 (SAML/LDAP
  took v1.3.0).
