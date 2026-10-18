A **programming problem** is solved by submitting a program rather than a
flag — the ICPC-style problem: read standard input, print the answer. It's
available once an administrator has set up the **code judge** (Admin → Site
settings → Code judge) and the competition's **Code judge** module is on.

## Authoring a problem

Choose the challenge type *Programming (solved by submitting code)*, write
the statement in the description, and **Create challenge**. The **Test
cases** section then appears.

![Test cases](assets/test-cases.png)
*Each submitted program runs on every test case. Examples are shown with the
statement; hidden cases are only used for judging.*

- **Add test case** — *Type or paste* an input and its expected output, or
  *Upload files* for large or binary data. Tick **Show to competitors as an
  example** for the ones that illustrate the problem; keep at least one
  hidden, or a program could just print the answers.
- **Advanced** — per-problem **time**, **memory** and **output limits**
  (blank uses the site default), **how output is checked** (*Ignore extra
  spaces and blank lines*, *Must match exactly*, or *Numbers may differ
  slightly*), **Ignore upper/lower case**, and which **Languages** are
  allowed.
- **Check with a reference solution** — run a solution you know is right
  against every test, through the real judge. It reports each test, never
  scores or blocks publishing, and tells you when the tests or limits have
  changed since. Make it a habit: it catches a wrong expected output or a
  too-tight limit before competitors do.

The time limit competitors see is per language — each language's multiplier
(set by the administrator) is applied, so Python gets proportionally longer
than C++.

## Problem packages

**Import problem package…** on the Manage challenges page accepts a problem
package in the open ICPC format — one problem or a contest zip — and creates
each as a **draft**, with a list of things to check. Flagpost imports what
it can judge faithfully (pass/fail problems with the standard output check)
and **refuses the rest with the reason** — custom checkers, interactive or
scored problems. Statements are converted from Markdown or LaTeX as best
they can be, with the original attached. Most packages don't state a time
limit: the dialog asks for one, and the package's accepted solution is
pre-filled into the reference check so you can confirm it in one click.

**Export problem packages** writes every problem back out in the same
format; a single problem's **Export package** sits in its Test cases
section.

## The Judging page

![The Judging page](assets/judging.png)
*Every code submission as it's judged: the queue, per-test results,
compiler messages and the submitted code.*

**Judging** appears in the sidebar once the competition has a programming
problem. Filter by **Problem** and **Result**, and **Include example runs**
to see competitors' unscored trial runs. Open a submission for its tests,
**Submitted code** and **History**, then:

- **Rejudge** one submission; or, with a problem selected, **Rejudge this
  problem…** — *Every submission*, *Only accepted submissions* (to check a
  fix broke nothing) or *Only submissions that weren't accepted* (after
  fixing a wrong test). Verdicts a judge set by hand are left alone.
- **Override verdict…** with a **Reason (shown to staff)**. It replaces the
  judge's verdict immediately and is recorded with your name.

The **newest verdict counts**: points, the scoreboard and the activity feed
follow it, so a revoked solve takes its points back and a late acceptance
scores from the original submission time. Competitors see *Rejudged* or
*Judge's decision* on the entry, never the reason.
