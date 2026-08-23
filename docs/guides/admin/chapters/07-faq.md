## I've lost administrator access — how do I recover?

In order of preference: another **Administrator** signs in and restores you
(the reason to always have two); or use **Forgot password** if your account
has an email and SMTP is configured. And by design, if the site is ever
left with **no active administrator at all**, the first-run **setup
wizard reopens** so an operator with access to the deployment can create a
new owner account — the site never becomes permanently unadministrable.

## Does closing registration affect existing users?

No — it only stops *new* public sign-ups. Existing accounts sign in as
normal, SSO keeps working per each provider's posture, and you can still
create accounts directly from Admin → Users.

## What does the platform send outside my network?

Only traffic you configure: SMTP mail, automation webhooks, identity-
provider exchanges, and the AI provider if you enabled that module — plus
one **daily update check that sends only the running version number**,
which you can turn off in Site settings. There is no other phone-home.

## What happens the first time someone signs in through SSO?

The account is created automatically as a **Participant** — never anything
higher — and linked to the provider's stable subject, so later email
changes at the IdP don't fork accounts. Grant staff roles yourself
afterwards; sign-in method never implies privilege.

## Can I move a backup to another instance?

Yes — that's what export/import is for. The file carries a schema version
and imports into an instance whose export format matches; when migrating
across versions, upgrade the instance first, then take a fresh export.
Import is **additive**: existing records are never overwritten. Remember
the file carries secrets — move it like a credential.

## How do I block an account without destroying its history?

**Soft-ban** from Admin → Users: sign-in is blocked, every solve, ticket
and audit entry survives with attribution intact, and unbanning restores
access exactly as it was.

## If I toggle a module off for a competition, what changes?

That competition loses the feature's surfaces while the toggle is off —
nothing else on the site is affected, and other competitions keep their own
settings. Toggles are per-competition precisely so one event's choices
never bleed into another's.
