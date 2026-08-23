Open **Manage challenges** from the challenges page to reach the authoring
surface: your challenge list on the left, the editor for the selected
challenge on the right.

![Managing challenges](assets/manage.png)
*The list pane searches and filters, and carries New / Import / Export; the
editor keeps Save, Publish and Delete together above the fields.*

## The lifecycle: draft → published

New challenges are **drafts** — invisible to competitors, so you can build
openly during the event. Publishing requires a flag to be set. Unpublishing
hides a challenge again without deleting anything; deleting removes it *and*
its attachments, hints, and solve history.

## What a challenge can carry

- **Flag types** — `static` (exact match, optionally case-insensitive),
  `regex` (pattern-graded), or `multiple choice` (options with one correct
  answer; pairs with guess caps).
- **Scoring** — static points, or **dynamic**: the value decays from a
  starting value toward a floor as solves accumulate. Every solver holds the
  current value.
- **Prerequisites** — an unlock chain: competitors must solve the listed
  challenges first.
- **Release schedule** — a published challenge can stay hidden until a set
  time, for mid-event waves that need no one awake to push a button.
- **Connection info** — where the live target runs (`nc host 1337`, a URL);
  shown with a copy button once unlocked.
- **Attachments** and **hints** — hints can be free or cost points, and can
  be authored hidden with their own release time.

The flag itself is **write-only**: the editor shows *that* one is set, never
its value — so a shared screen never leaks it.

## Categories, difficulty & tags

The **Challenges tab in Settings** owns the vocabulary: categories (the
chips competitors filter by), difficulty tiers, and topic tags. Set them
early — consistent tagging is what makes a 40-challenge board navigable.

## Import & export

**Export** downloads the whole set as a ctfcli-format zip; **Import** loads
one. That's the path for versioning challenges in git, moving an event
between instances, or bulk-authoring outside the browser.
