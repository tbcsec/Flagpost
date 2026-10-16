Open **Manage challenges** from the challenges page: your challenge list on
the left, the editor for the selected challenge on the right.

![Managing challenges](assets/manage.png)
*The list pane searches and filters by category, and carries New challenge,
Export and Import (plus problem-package import when the code judge is on);
the editor keeps Save, Publish and Delete together above the fields.*

## The lifecycle: draft → published

New challenges are **drafts** — invisible to competitors, so you can build
openly during the event. Each type has its own publish requirement: a static
or regex challenge needs a flag, multiple choice a correct option, a
programming problem at least one test case. Unpublishing hides a challenge
again without deleting anything; deleting removes it *and* its attachments,
hints and solve history.

## What a challenge can carry

- **Challenge type** — fixed once created. *Static* (exact match, with a
  **Case-insensitive flag** option), *Regex* (pattern-graded), *Multiple
  choice* (up to ten options, one marked correct; pairs with guess caps), or
  *Programming* (solved by submitting code — chapter 3).
- **Scoring** — *Static (fixed points)* or *Dynamic (decays as more solve)*:
  the value falls from the initial points toward a minimum over roughly the
  stated number of solves. Every solver holds the current value.
- **More options** (collapsed) — **Connection info** (`nc host 1337`, a URL;
  shown with a copy button once unlocked), **Release at** (a published
  challenge stays hidden until then — waves with no one awake to push a
  button), **Prerequisites** (an unlock chain), **Difficulty** and **Tags**
  (once defined in Settings → Challenges).

The flag itself is **write-only**: the editor shows *that* one is set, never
its value — so a shared screen never leaks it.

## After creating

**Create challenge** first; the sections that need a saved challenge appear
below it: **Attachments**, **Hints** (free or costing points, optionally
*Hidden until released* at a set time), **Guesses** (multiple choice —
chapter 6), **Deployment** (instanced challenges — chapter 4) and **Test
cases** (programming — chapter 3).

## Categories, difficulty & tags

**Settings → Challenges** owns the vocabulary: categories (the chips
competitors filter by), difficulty tiers, and tags. Set them early —
consistent tagging is what makes a 40-challenge board navigable.

## Import & export

**Export** downloads the set as a ctfcli-format zip and **Import** loads one
(challenges whose title already exists are skipped, never overwritten).
Descriptions, regex patterns, hints, attachments, prerequisites and
deployments round-trip; **static flags do not** — they're stored hashed — so
keep flags in your own source and re-add them after an import.
Multiple-choice options aren't carried either, and programming problems
export separately as problem packages (chapter 3).
