## My flag is right but it was rejected — why?

Leading and trailing whitespace is trimmed, but everything else is graded
exactly: the full string, the `flag{...}` wrapper when shown, and case
unless that challenge was authored case-insensitive. Paste rather than
retype. On an instanced challenge the flag belongs to *your running
instance* — a stopped or relaunched instance has a different one. Still
stuck? Open a support ticket with the related challenge selected.

## A challenge was worth 500 — why is it 380 now?

That's **dynamic scoring**: the value decays as more people solve it, and
every solver holds the current value. On a multiple-choice question it can
also be the **wrong-guess penalty** — each wrong answer lowers what the
question is worth *to you or your team*.

## I solved something but the scoreboard didn't move.

Near the end of an event the board is often **frozen** — your solve counted
the moment you submitted, and standings update at the reveal. Mid-event,
remember the board ranks totals: a 100-point solve may not change your rank.

## My code was Accepted — why did the points disappear?

Judges can rejudge a problem or decide a verdict by hand, and the **newest
verdict counts**. The entry in *Your submissions* is marked *Rejudged* or
*Judge's decision*. If you think it's wrong, ask through Support.

## Can I use Flagpost on my laptop and phone at once?

Yes — sign in on as many devices as you like. Challenge notes sync live
between them; code drafts written in the browser stay on the device you
wrote them on.

## What if I forget my password mid-event?

**Forgot password?** on the sign-in page emails a reset link — provided
your account has an email address. Add one *now*, under Profile → Account →
Email → **Add email**, before you need it.

## I'm out of guesses on a multiple-choice question.

Open a support ticket. Organisers can restore attempts for you or your
team — nothing about your history is lost.

## I can't join — it says to verify my email.

This site requires a verified email before joining. Profile → Account shows
**Verify your email** with **Resend verification email**; click the link in
the mail and try again.

## How do I get into the next event on this site?

Open the invite link your organisers send, or go to `/lobby` to see public
competitions and enter an invite code. Your account carries over.

## Who can read my challenge notes?

Your team, and only your team (in individual mode, only you). Write freely.

## Can my tools talk to Flagpost directly?

Yes — Profile → **API tokens** → **Create token**: a description, an
optional expiry, and your current password. The token is shown **once**;
send it as an `Authorization: Bearer` header. Tokens act as you, so treat
them like your password and **Revoke** any you stop using.
