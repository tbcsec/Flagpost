The **Challenges** page is where you'll spend the event.

![The challenges page](assets/challenges.png)
*Category chips filter the board (each with your solved/total); cards carry
points, difficulty, tags and a badge: Open, Solved, 🔒 Locked, or Code.
Prefer rows? Switch Cards → List — the choice sticks per device.*

**Locked** means the challenge has prerequisites — solve those first and it
unlocks (opening it shows which). **Code** marks a programming challenge,
which opens on its own page (chapter 4). New challenges can appear mid-event
in waves — watch the announcements.

## Inside a challenge

![A challenge](assets/challenge-dialog.png)
*The challenge view: description, flag entry, solves so far, and your notes
pad — My notes when you play solo, Team notes in a team event.*

Depending on the challenge you'll also see **Files** to download,
**Connection** (where the live target runs, with a copy button), **Hints**
(chapter 5), **Clarifications from the judges**, and how many others have it
open.

## Submitting flags

Most challenges want a flag — usually `flag{...}` — pasted exactly as found.
Surrounding whitespace is trimmed for you; everything else, including case
(unless the authors chose otherwise), must match. A correct flag scores
instantly and marks the card solved. Rapid-fire guessing is rate-limited.

Some challenges are **multiple choice** instead:

- Your **guesses may be capped** — the challenge shows how many remain. Out
  of guesses? Open a support ticket; organisers can reset them.
- Events can enable a **wrong-guess penalty**: each wrong answer lowers what
  that question is worth to you (or your team) by a stated percentage. The
  original value shows struck through next to what it's worth now.

## Your own instance

Some challenges hand each player or team an **isolated running copy** of a
service. In the **Instance** panel, **Launch instance** starts one; once it's
running you get the connection details — an `nc host port` line or a
clickable link — with a countdown. **Extend** restarts the clock a limited
number of times; **Stop** destroys it, and you can launch again. In a team
event the instance is shared by the whole team, and launches can be refused
when you've hit a cap or are launching too quickly.

!!! note "Unique flags"
    Instanced challenges may give every instance its own flag. It's only
    accepted while *your* instance is running (relaunching mints a new one),
    and submitting another team's flag is recorded as flag sharing.

!!! note "Paused competitions"
    Organisers can pause gameplay during an incident. The Challenges page
    shows *⏸ The competition is paused*, and flag submissions, code
    submissions and hint reveals close until play resumes.
