# ADR-0018: Containing ReDoS in regex flag matching

**Status:** Accepted
**Date:** 2026-07-24
**Architecture reference:** `ARCHITECTURE.md` §13.2 (flag verification), §2 (fixed
stack — a new dependency needs sign-off), ADR-0005 (single-process async runtime)

## Context

A challenge author can set a **regex flag** (`flag_type = "regex"`). At submit
time `utils/flags.verify_regex_flag` compiles the stored pattern and runs
`re.fullmatch(pattern, submitted)` against the **competitor-supplied** flag
(`routers/submissions.submit_flag`). This crosses a trust boundary in an unusual
direction:

- the **pattern** is authored by staff (`challenge_create` / `challenge_edit` —
  Judge or Administrator), and
- the **input** is authored by a competitor (bounded to 500 chars by the schema).

Python's `re` engine backtracks. A pathological pattern — `(a+)+$`,
`(.*a){20}`, nested quantifiers — turns a short input into exponential work.
Because the whole backend is a **single-process async runtime** (ADR-0005) and
`re` **holds the GIL while matching**, one catastrophic match doesn't just slow
the one submission: it **blocks the entire event loop**, freezing every other
request and every competition on the instance until it finishes (which may be
"never, in practice"). That turns a per-competition authoring mistake into a
**platform-wide denial of service**.

The threat is real without assuming a fully malicious insider: a Judge is
semi-trusted (they can already disrupt their *own* competition), but the harm
here **escapes the tenant boundary** — it takes down other organisers' events
too. And it doesn't even require malice: an honest author can paste a
legitimate-looking regex that happens to backtrack badly on a crafted string a
competitor then submits deliberately.

The crux that shapes the options: **stdlib `re` cannot be interrupted.** It has
no timeout parameter, and running it in a thread via `asyncio.to_thread` does
*not* help, because it never releases the GIL — the thread pins the interpreter
just as hard as an inline call would. So "just add a timeout" is not available
with the current engine; a real fix has to change *what runs the match*.

Options actually on the table:

1. **`regex` module with `timeout=`** (third-party, drop-in-ish for `re`). It
   releases the GIL during matching and honours a wall-clock `timeout`, so run
   under `asyncio.to_thread(pattern.fullmatch, submitted, timeout=…)` and a
   runaway match is actually aborted *and* the loop keeps serving other
   requests. Preserves full Python regex semantics (authors' existing patterns
   keep working). Cost: a new runtime dependency (§2).
2. **`re2` / `google-re2`** — a linear-time engine (RE2) with **no
   backtracking**, so ReDoS is impossible *by construction*, no timeout tuning
   needed. Cost: a C-extension dependency, and it drops backreferences and
   lookaround — features CTF flag patterns almost never use, but a hard
   semantic change for anyone who did.
3. **Author-time complexity lint** — reject patterns with known-dangerous
   shapes (nested/adjacent unbounded quantifiers) on challenge create/update.
   Zero runtime cost, no dependency. But ReDoS detection is undecidable in
   general: it both misses cleverly-built patterns and false-positives on some
   safe ones. Useful only as a cheap *extra* layer, never the whole answer.
4. **Process-pool isolation** — run the match in a worker process with a hard
   kill on overrun. Robust and engine-agnostic, but a per-submission process
   hop on the one hot adversarial path, plus IPC of the pattern/input — heavy
   for what it buys over option 1.
5. **Accept the risk** (status quo) — lean on the 500-char input cap and
   "Judges are trusted". Rejected as the standing decision: the input cap
   doesn't stop exponential blowup, and cross-tenant DoS is exactly the class
   of thing a *security* platform must not ship with a shrug.

## Decision

Make regex flag matching **interruptible and loop-safe** by swapping the engine
behind `verify_regex_flag` from stdlib `re` to the **`regex` module** (owner
approved the dependency, §2). `regex` is PCRE-compatible — so every existing
staff-authored pattern keeps working, including backreferences and lookaround —
and it both honours a match `timeout=` and releases the GIL.

As implemented:

- `verify_regex_flag` (`utils/flags.py`) calls `regex.fullmatch(…,
  timeout=REGEX_MATCH_TIMEOUT_SECONDS)` with the budget set to **250 ms** —
  orders of magnitude above any honest flag check. A `TimeoutError` (runaway
  match) and a `regex.error` (malformed pattern) are handled identically:
  **fail closed** — treated as "did not match", never a 500. This reuses the
  posture already in place for a malformed pattern.
- `submit_flag` (`routers/submissions.py`) grades via
  `await asyncio.to_thread(_flag_matches, …)`, so the bounded match runs off the
  event-loop thread and — because `regex` drops the GIL — never stalls other
  requests during the window.

`re2` (guaranteed-linear-time, no backtracking) was the considered alternative
but rejected: dropping backreferences/lookaround is a semantic regression on
authors' existing patterns, and the `regex` timeout closes the same hole without
that cost. The author-time complexity lint (a cheap second layer) is **not**
built — the runtime budget is sufficient on its own; the lint stays available as
a future nicety, not a requirement.

## Consequences

- Positive:
  - The platform-wide DoS is closed: a pathological pattern can burn at most
    one timeout's worth of one thread, then fails that single submission — the
    blast radius shrinks from "the whole instance" to "one wrong answer".
  - Fail-closed on timeout reuses the exact posture already in place for a
    malformed pattern (`re.error` → `False`), so behaviour stays predictable.
  - Moving the match off the event-loop thread also removes an incidental
    latency spike on every regex submission, not just the malicious case.
- Negative / cost:
  - **A new runtime dependency** (`regex`), added deliberately per §2 — the one
    external addition since the stack was fixed, justified by there being no
    stdlib way to bound a match.
  - The engine stays a **backtracking** one (unlike `re2`), so the timeout is
    load-bearing: correctness of the guarantee rests on the budget firing, not on
    the engine being linear-time by construction.
  - A per-submission thread hop and a timeout knob to tune (too low rejects a
    legitimately heavy pattern; too high still lets a burst of matches each
    consume the budget — see below).
- Forecloses: nothing. The author-time lint, a stricter engine swap, or a
  future move of all CPU-bound work to a process pool remain additive. The
  **aggregate** angle — many simultaneous near-budget matches from a submission
  flood still costing real CPU — is *not* closed by a per-match timeout and
  stays part of the open §15 rate/throughput question, alongside the webhook
  destination-rate residual (ADR-0013).
