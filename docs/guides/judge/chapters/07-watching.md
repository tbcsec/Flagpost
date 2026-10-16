## Reading the room

The dashboard's sections are your event telemetry:

- **Challenge health** — solves vs. attempts per challenge. Many attempts
  and no solves can mean *good and hard* — or broken. **Unsolved
  challenges** lists the ones nobody has cracked.
- **Recent solves** — the live stream. A burst right after a hint tells you
  the hint priced correctly; a first blood minutes after release tells you
  it didn't.
- **Brute-force watch** — the teams submitting the most wrong flags; **Team
  activity** shows who's gone quiet.
- **Support queue** — an open count trending up is the earliest warning of
  an infrastructure or clarity problem.

On the **Scoreboard**, staff see live standings even while it's frozen, can
**Freeze board** / **Unfreeze board**, and in a divisioned event assign each
competitor's **Division** from the table. The public board has a **Venue
mode** for projectors.

## Optional instrumentation

If the modules are on for your competition (Settings → Modules):

- **Analytics** — *Overview*: a per-challenge table (solves, completion,
  average time, attempts, hints, tickets, rating), the teams or competitors
  table, and insight cards (least solved, most attempted, most tickets, most
  first bloods). *Submissions*: a filterable browser of every submission
  with **Export CSV**.
- **Feedback** — challenge ratings (once enabled in Settings → Challenges)
  and **surveys**: **New survey** with rating, text and multiple-choice
  questions, **Open for responses**, **Results** and **Export CSV**.
- **Automations** — rules built as *When this happens* → *And these are all
  true* → *Do this*: announce or award on first blood, release a hint or
  freeze the board at a set time remaining, alert staff on flag sharing.
  Actions include hints, unlocks, announcements, awards and score updates,
  notifications, email and webhooks. **My rules** holds personal
  notification rules.
- **Assistant** (Settings) — the competitor AI assistant's **Availability**,
  **Guidance level** (*Platform only*, *Conceptual* or *Guided* — never full
  solutions) and whether it can see **Challenge details**. The sidebar's **AI
  transcripts** is how you verify it's behaving; staff also get a read-only
  **Organiser assistant**.
- **Certificates** (Settings) — a visual designer; **Recipients** (*All
  participants* or *Only participants who scored*); **Release timing**
  (manual, at the end, or a set time after); **Export all as ZIP**; and a
  reusable template. Save the design before releasing — the saved one is
  what ships.
- **Reports** (Settings) — once the competition has ended, **Generate
  report**: an audience preset (*Executive*, *Technical*, *Full*) or your own
  sections, as PDF and/or HTML, kept in a version history.

## Closing out

When the schedule ends (or you press Stop), submissions close and the board
settles. Unfreeze the scoreboard at your ceremony, release certificates,
generate the report, and skim the feedback while memories are fresh. Export
the challenge set for next year — the ctfcli zip (minus flags) and
**Export problem packages** — and hand archiving and backups to your
administrator.

The deeper operational reference — deployment, scaling, integrations — lives
at **docs.flagpost.io**.
