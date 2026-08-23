## Custom pages

![Custom pages](assets/pages.png)
*Admin → Pages: rich-text pages with sidebar entries and an audience
setting.*

Pages carry event-adjacent content — rules in full, prizes, venue, sponsor
information — authored in the rich-text editor, each with an icon, a
sidebar entry, and an **audience**: members of a competition, any signed-in
user, or everyone *including signed-out visitors* (public pages are also
linked from the sign-in screen). Drafts stay invisible until published.

## The audit log

![The audit log](assets/audit-log.png)
*Admin → Events: who did what, where, across every competition.*

Staff actions and security-relevant events land here — challenge edits,
publishes, role changes, bans, sign-ins, resets — filterable by competition
and actor. When something looks off mid-event, this is the first stop; it's
also the record that makes post-event disputes short.

## Backups

**Site settings → Backup** exports the whole instance — competitions,
challenges, users, configuration — to a single file, and imports one
additively (existing records aren't overwritten). Two things to internalise:

!!! note "The export is sensitive"
    The backup contains everything, **including secrets** (provider
    credentials, configuration). Store it like a credential: encrypted at
    rest, access-controlled, not in a shared drive folder named "backups".

Take one before risky changes (imports, big deletions, upgrades) and after
each event — restore-tested backups are the difference between an incident
and an anecdote.

## Automations

Each competition can run **automations** (if its module is on): visual
if-this-then-that rules reacting to events — solves, first bloods, ticket
activity, schedule times — with actions like announcements, notifications,
and webhooks. As the admin you'll care that **webhook egress is
locked down** by design (no internal-network calls), and that the builder
is permission-gated like everything else.

---

That's the site side. Event operations live in the **Judge guide**,
competitor-facing behaviour in the **Competitor guide**, and deployment,
scaling and integrations at **docs.flagpost.io**.
