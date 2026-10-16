## I've lost administrator access — how do I recover?

Another **Administrator** signs in and restores you — the reason to always
have two — or use **Forgot password?** if your account has an email and SMTP
is configured. The setup wizard does **not** reopen on a configured install,
by design; beyond those two paths, recovery is an operator job at the
deployment level (docs.flagpost.io).

## Does closing registration affect existing users?

No — it only stops *new* public sign-ups. Existing accounts sign in as
normal, **closed**-policy identity providers keep admitting their users,
**open** ones stop creating accounts, and you can still create or import
accounts from Admin → Users.

## What does the platform send outside my network?

Only traffic you configure: SMTP mail, automation webhooks, identity-provider
exchanges, the AI provider if enabled, the container runtime behind
instances or the code judge (which pulls language images on first use), and
the marketplace registry — contacted only when you resolve or install a
pack. Plus one **daily update check that sends only the running version
number**, which you can turn off in Site settings → General. There is no
other phone-home.

## What happens the first time someone signs in through SSO?

The account is created with **no role** and becomes a Participant per
competition as they join. It's linked to the provider's stable subject, so a
later email change at the IdP doesn't fork it; it only attaches to an
existing local account when both sides' emails are trusted. Whether a new
account is allowed while registration is closed depends on the provider's
**Sign-in policy** (chapter 4). Staff roles are yours to grant afterwards.

## Someone leaked an API token.

Admin → Users → **API tokens** lists every token on the platform with its
holder; **Revoke** stops it authenticating immediately.

## Can I move a backup to another instance?

Yes — upgrade the target first so the formats match, then import; it's
**additive**, so existing records are never overwritten, and you can move
only some sections. Identity providers, the SMTP password, AI settings, API
tokens and the judge and instance configuration don't travel — re-enter
them on the target (and rotate). The file carries password hashes and
flags: move it like a credential.

## How do I block an account without destroying its history?

**Ban** from Admin → Users: they're signed out immediately and blocked from
signing in, while every solve, ticket and event entry survives with
attribution intact. **Unban** restores access exactly as it was.

## If I toggle a module off for a competition, what changes?

That competition loses the feature's surfaces while the toggle is off —
nothing else on the site is affected. The reverse isn't symmetric for AI
Assistants, Challenge Instances and Code Judge: switching those *on* per
competition does nothing until the matching Site settings tab is configured
and enabled.

## A competitor says the scoreboard "lost" their programming solve.

Judges can rejudge or override verdicts, and the newest verdict counts —
the **Event log** records who did what and why. Ask the competition's judges
first; the override reason is visible to staff on the Judging page.
