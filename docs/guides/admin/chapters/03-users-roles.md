## The users directory

![Users](assets/users.png)
*Every account on the site — search, inspect, create, and moderate.*

**Admin → Users** lists every account. From here you can create accounts
directly (the only path when registration is closed) and **soft-ban** an
account — it blocks sign-in without deleting anything, so history and
attribution survive; unban restores access. Identity is username-first: the
display name is the unique login handle, and email is optional unless your
registration settings require it.

## Roles: permissions as data

![Roles](assets/roles.png)
*Each role is a named bundle of granular permissions, split between global
scope and competition scope.*

**Admin → Roles** manages the role catalogue. Three system roles ship —
**Administrator** (global), **Judge** and **Participant** (competition-
scoped) — and they track the platform: when an update introduces a new
permission, the system roles pick it up automatically.

Custom roles are where the model earns its keep. Every capability is its
own permission with a **scope**:

- **Global** permissions (manage users, roles, site settings, create
  competitions…) apply site-wide.
- **Competition** permissions (edit challenges, manage the schedule,
  tickets, announcements…) apply inside whichever competition the role is
  granted for.

So "score-keeper who can also see analytics", "challenge author with no
schedule control", or "site moderator who manages users but never touches
events" are each a five-minute custom role, not a code change.

!!! tip "Grant the least that works"
    Start people on the narrowest role that covers their job and widen on
    request. It keeps the audit log meaningful and makes the inevitable
    "who could have done this?" a short list.
