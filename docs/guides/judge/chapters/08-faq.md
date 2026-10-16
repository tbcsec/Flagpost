## What do competitors see of a draft?

Nothing — no card, no count, no scoreboard trace. Drafts (including
unpublished-again challenges) exist only for staff, so you can build and
repair openly during a live event.

## I edited a live challenge — what happens to points already scored?

Description, connection info, hints and attachments apply immediately. On a
**static** challenge, existing solves keep the value they scored and future
solves earn the new one; on a **dynamic** challenge every solver is
re-valued as the decay moves. If a mistake cost competitors points,
compensate with an award or score adjustment rather than retro-editing
values.

## A test case was wrong. Now what?

Fix it, then on the **Judging** page pick the problem and **Rejudge this
problem…** → *Only submissions that weren't accepted*. Newly accepted
submissions score from their original submission time, so first blood and
ordering come out right. Run the reference check again afterwards — it tells
you when it's stale.

## Where's the Judging page?

It appears in the sidebar only when the competition's Code Judge module is
on *and* the competition has at least one programming problem (drafts
count). If *Programming* isn't selectable in the challenge editor, either
the competition's Code Judge module is off (Settings → Modules) or the
administrator hasn't finished the judge setup — the editor says which.

## Can I grant bonus points?

In an **individual-mode** competition, yes: Participants → **Create award**
(points can be zero or negative). In a team competition, awards and score
changes go through an automation's *Create award* / *Update score* action.

## A team legitimately burned all their guesses.

Open the challenge in the editor — its **Guesses** section restores attempts
for one team/competitor or for everyone. History is kept.

## Pause or stop — which do I want?

**Pause** for incidents: flag and code submissions and hint reveals close,
the Challenges page shows a banner, the schedule keeps its dates, and staff
can still submit to verify a fix. **Stop** ends gameplay. If an incident ate
meaningful time, pause, fix, extend the end time in Controls, then resume.

## When can I safely test challenges myself?

Opening and downloading is always safe. **Submitting flags on the live
competition is not** — staff solves take first blood and decay dynamic
values (and need a team in team mode). Rehearse in a clone; for programming
problems, *Run examples* and the reference check never score.

## Import said it skipped or couldn't import some challenges.

The ctfcli importer **skips** challenges whose title already exists and
never overwrites; static flags aren't in the export, so re-add them. The
problem-package importer lists *Skipped* (title exists) and *Couldn't
import* with the reason — a custom checker, an interactive or scored problem
— which Flagpost can't judge faithfully. Imported problems arrive as drafts:
review the converted statement and confirm the time limit with the
reference check.

## Why can't a competitor join my private competition?

The invite code or a **join link** (Settings → Sharing) is the only
self-serve way in. Join links also honour the registration window in
Controls, and stop working once the event ends.
