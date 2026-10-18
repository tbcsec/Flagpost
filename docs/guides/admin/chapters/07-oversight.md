## Custom pages

![Custom pages](assets/pages.png)
*Admin → Pages: rich-text pages with a sidebar icon, a URL slug and an
audience.*

Pages are **site-wide** — full rules, prizes, venue or sponsor information
— each with an icon, a slug (`/p/slug`; changing it breaks links), and an
audience: **Signed-in users only** or **Anyone, including signed-out
visitors** (public pages are also linked from the sign-in screen). Drafts
stay invisible until published; **Move up** / **Move down** orders the
sidebar.

## The event log

![The event log](assets/audit-log.png)
*Admin → Event log: every event the platform emits, across every
competition.*

Everything that happens lands here — staff actions (publishes, role changes,
bans, score adjustments, overridden verdicts), security-relevant events, and
gameplay (solves and attempts, flag-sharing detections). Filter by text,
**Event type**, **Competition**, **Team**, **Actor** and a time range (UTC);
click a row for its full payload. It's the first stop when something looks
off mid-event, and the record that makes post-event disputes short. Judges
don't have it — point them at their dashboard's Moderation feed.

## Skills

![The skills matrix](assets/skills.png)
*Admin → Skills: every competitor's strength per category, across every
competition.*

One row per competitor, one column per skill (a challenge category),
accumulated across every event they've played. Each cell shows points over
solved/available challenges and first bloods, shaded as a percentile
*within the column* — the right comparator, since raw points don't normalise
across events. Search, narrow the **Activity window**, sort, click a row for
the full breakdown, or **Export CSV**. Competitors see only their own
skills (Profile → Skills).

## Marketplace

**Admin → Marketplace** installs **content packs** from a registry: paste an
**Import code**, **Resolve**, review it (*Signed* or *Unsigned*, the
publisher, what it requests), pick a **Target competition** for a challenge
pack, and **Install** — signatures are verified locally first. Challenge
packs land as challenges; brand-theme packs appear under Appearance.
**Registry & trust** holds the on/off switch (off blocks every install
path), the **Registry URL** — point it at a private mirror for air-gapped
installs — the **Trust policy** and **Trusted keys**. The registry is
contacted only when you resolve or install. Importing and configuring are
separate grants.

## Global automations

**Admin → Automations** holds **global rules** that run across every
competition (per-competition rules are the judges'). Each shows what it
fires on and how often; Edit, Enable or Disable, Delete. Webhook egress is
locked down by design: no calls into private networks.

## Backups

**Site settings → Backup** exports selected sections — site settings &
branding, user accounts, roles & assignments, competitions (challenges,
teams, scores, tickets…), automation rules, the audit log — to one JSON
file, and imports one **additively**: records that already exist (a
competition by name, a user by name or email) are skipped, never
overwritten. Each section beyond site settings needs the permission that
governs it — roles *manage roles*, automation rules *view* and *create automations*,
and competitions every competition permission plus *create competitions*.
Two depend on the direction: accounts import with *manage users* but export
(every password hash and email) only for a full Administrator, and the audit
log exports with *view audit log* but imports only for a full
Administrator. Custom pages travel with site settings only for holders of
*manage pages*, and a file whose site settings would change the mail server
or From address imports only for a full Administrator. A delegate is offered
only the sections they may move.

!!! note "What travels, and what doesn't"
    The file holds password and flag hashes, emails, uploaded files and
    programming test data — store it like a credential. Deliberately **left
    out**: identity-provider configuration, the SMTP password, AI settings
    and key, API tokens, sessions, and the judge and instance
    infrastructure. Re-enter those after a restore — a good moment to
    rotate them.

Take one before risky changes (imports, big deletions, upgrades) and after
each event — restore-tested backups are the difference between an incident
and an anecdote.

---

That's the site side. Event operations live in the **Judge guide**,
competitor-facing behaviour in the **Competitor guide**, and deployment,
scaling and integrations at **docs.flagpost.io**.
