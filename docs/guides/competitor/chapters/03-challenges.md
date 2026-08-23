The **Challenges** page is where you'll spend the competition. Challenges are
shown as cards grouped by category chips (Web, Crypto, Pwn, …), each chip
carrying your solved-count for that category. Prefer a compact view? Switch
the layout toggle from **Cards** to **List** — Flagpost remembers your choice
on that device.

## Reading a challenge card

Each card shows the challenge's category, title, point value, solve count,
and any difficulty or topic tags the organisers assigned. Two states matter:

- **Locked** — the challenge has **prerequisites**: solve the listed
  challenges first and it unlocks. Locked challenges show which solves they
  need when opened.
- **Open** — ready to attempt. Click the card for the full challenge.

New challenges can appear mid-event: organisers release waves on a schedule
or by hand. Watch the announcements (chapter 6).

## Inside a challenge

Opening a challenge shows its description, current value, and solve count,
plus — depending on the challenge:

- **Connection info** — where the live target runs, e.g.
  `nc chal.example.org 1337` or a URL, with a copy button.
- **Attachments** — downloadable files (binaries, captures, source).
- **Hints** — see chapter 4.
- **Who's here** — a presence indicator when teammates or other competitors
  have the same challenge open.

## Submitting flags

Most challenges want a flag — usually in a `flag{...}` format — pasted into
the submission field. Submit it **exactly as you found it**: flags are graded
precisely, including case, unless the authors chose otherwise for that
challenge.

Some challenges are **multiple choice** instead. Two things to know:

- Your **guesses may be capped** — the challenge shows how many attempts you
  have left. Out of guesses? Open a support ticket; organisers can reset them.
- Events can enable a **wrong-guess penalty** that permanently reduces what
  *that question* is worth to you (or your team) with each wrong answer. The
  reduced value is shown struck through next to the original.

A correct flag locks in your points immediately, updates the scoreboard live,
and marks the card solved. Repeat submissions of a solved challenge don't
score twice.

!!! note "Paused competitions"
    Organisers can pause gameplay (for example, during an infrastructure
    issue). A banner appears and flag submissions are closed until play
    resumes — you keep access to everything else.
