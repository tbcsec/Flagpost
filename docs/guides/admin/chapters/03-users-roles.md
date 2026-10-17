## The users directory

![Users](assets/users.png)
*Every account on the site — search, create, import, moderate — and every
API token below.*

**Admin → Users** lists every account. **Create account** adds one with a
password that works immediately; **Import CSV** bulk-creates a roster (up to
200 rows, with an optional role per row — the file carries plaintext
passwords, so treat it as sensitive and delete it afterwards). Identity is
username-first: the display name is the unique login handle, and email is
optional unless your registration settings require it.

Per account: **Edit** (rename, change email, or set a new password — which
signs the user out everywhere), **Ban** / **Unban** (a ban signs them out at
once and blocks sign-in; everything they did survives with attribution),
**Remove picture**, and **Delete** (permanent — submissions, tickets and
team memberships included; prefer a ban). You cannot ban or delete
yourself, or the last active Administrator.

Changing someone's email marks the new address verified — you vouch for
it, as when you create an account — and cancels any reset or verification
links sent to the old address. Changing only its capitalisation does neither.

The **API tokens** panel at the bottom lists every personal token on the
platform; **Revoke** kills any of them immediately. That's your lever when a
credential leaks.

## Roles: permissions as data

![Roles](assets/roles.png)
*Each role is a named bundle of granular permissions, split between global
and competition scope. Roles are granted in the Assignments card further
down the page.*

**Admin → Roles** manages the catalogue. Three system roles ship —
**Administrator** (global), **Judge** and **Participant** (competition-
scoped) — read-only, and they track the platform: a new permission in an
update reaches them automatically. **Clone** one for an editable variant, or
**New role** with a name and a **Scope**:

- **Global** permissions (manage users, roles, site settings, create
  competitions, the event log, marketplace, judge and instance
  infrastructure…) apply site-wide.
- **Competition** permissions (edit challenges, manage the schedule,
  tickets, announcements, judging, instances…) apply inside whichever
  competition the role is granted for.

So "ticket handler who can also see analytics" or "site moderator who
manages users but never touches events" are each a five-minute custom role,
not a code change.

## Granting a role

The **Assignments** card: pick a **User**, a **Role**, and a **Competition**
(or **Site-wide** for a global role), then **Assign**. You can't grant, or
take away, more than you hold yourself, and the last Administrator can't be
unassigned. The same goes for accounts: someone delegated user management
looks after ordinary players, but can't reset, ban or delete a Judge or an
Administrator.
Someone who signs in through an identity provider arrives with *no* role;
they become a Participant per competition as they join, and staff roles are
yours to grant — sign-in method never implies privilege.

!!! tip "Grant the least that works"
    Start people on the narrowest role that covers their job and widen on
    request. The Auth, AI, Instances and Code judge tabs each have their own
    grant, as do most Admin pages, so an Auth delegate needn't be a full
    administrator; General, Email, Rules, Backup and Appearance share
    *manage site settings* — though changing the mail server or the From
    address needs an Administrator, since password-reset links travel through
    them. Treat *manage
    auth providers* as administrator-level too.
