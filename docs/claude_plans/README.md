# Implementation plans (historical)

Working plans written before a large piece of work started, kept as a record of
**what was intended and why**, not of what the code does now.

**None of these are live.** Every plan here has been executed; the phase
sequences in `phase_0.md`–`phase_3.md` are finished, and the issue plans
describe features that shipped. Read them for the reasoning behind a design —
which options were considered, which owner decisions were made, what was
deliberately left out — and read the code, `ARCHITECTURE.md`, or the ADRs for
current state. Where a plan and the code disagree, the code won: the plan
predates it.

| File | Covers | Status |
|---|---|---|
| `phase_0.md` | Tier 0 — foundation | Shipped |
| `phase_1.md` | Tier 1 — minimum viable competition | Shipped |
| `phase_2.md` | Tier 2 — dashboard, tickets, presence, theming, roles | Shipped |
| `phase_3.md` | Tier 3 — automation engine, DnD dashboard, CRDT, polish, and the ad-hoc Phase 9/10 tranches | Shipped |
| `issue-55-challenge-list-view.md` | Alternative challenge view | Shipped in v1.3.0 |
| `issue-57-rules-code-of-conduct.md` | Rules / code of conduct | Shipped in v1.2.0 |
| `issue-76-submissions-browser.md` | Submissions browser | Shipped in v1.2.0 |

Work after v1.0.0 is planned as GitHub issues against version milestones rather
than as phase documents, so this directory is unlikely to grow much — a plan
gets written here only when an issue is large enough that the design needs
settling before any code is written.
