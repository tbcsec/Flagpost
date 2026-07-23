# ADR-0015: Display name is the primary identifier; email is optional

**Status:** Accepted
**Date:** 2026-07-23
**Architecture reference:** `ARCHITECTURE.md` §7.7 (authentication mechanism),
§7 (Users & Roles)
**Supersedes:** the email-only identity assumed by ADR-0003/0007/0010 (auth
mechanism, first-user bootstrap, seeded admin) — those remain correct on tokens,
sessions and the seeded admin; only "email is *the* identifier" changes.

## Context

The original model made **email** the sole login identifier and a required field
on every account (`User.email` NOT NULL UNIQUE; login by email). For a CTF
platform this is awkward operationally:

- Competitors often don't want to hand over an email just to play, and organisers
  frequently bulk-create accounts (handles on a sheet) with no addresses.
- The name people actually recognise on a scoreboard is the **display name**, not
  an email — but that field was free-form and non-unique, so it couldn't identify
  anyone.

The owner asked to make **email non-required** and use the **username / display
name** as the primary identifier, with local login accepting *either* the display
name or the email.

## Decision

1. **The display name IS the username** — one field, not a new separate handle.
   It becomes the **primary login identifier**: required, and **case-insensitively
   unique**, enforced by a functional unique index on `lower(display_name)`
   (portable across SQLite ≥3.9 and Postgres) plus an application-level
   case-insensitive check for a friendly 409. Consequence, accepted: two users
   can't share a display name (no two "John Smith"; the second picks another).
2. **Email is optional** — `User.email` becomes nullable, still **unique when
   present** (a UNIQUE column permits multiple NULLs on both engines). It's a
   secondary handle, not identity.
3. **Login accepts display name *or* email**, matched case-insensitively. The
   lookup tries email first, then display name (two queries, not an `OR`), so the
   resolution is deterministic even in the unlikely case one user's email equals
   another's display name. The request field is `identifier` (with an `email`
   JSON alias kept for back-compat).
4. **Everything that referenced a user by email still works for email-less
   accounts**: Admin → Roles assignment resolves by display name *or* email; the
   admin user directory searches both; `user_email` is nullable in API shapes.

## Alternatives considered

- **A separate `username` field** (slug-like, unique) alongside a free-form
  non-unique display name — the "proper" model many platforms use. Rejected as
  more than asked: a new column, a new sign-up field, and a backfill (slugify
  existing display names), for little gain at this stage. Reusing display name is
  the smaller, owner-chosen change; a separate handle can still be added later
  without breaking this contract.
- **Case-sensitive usernames.** Rejected — "Alice" vs "alice" as distinct
  accounts is surprising and an impersonation vector; case-insensitive uniqueness
  + login is the least-surprising behaviour.
- **Keeping email required but also allowing username login.** Rejected — it
  doesn't address the actual ask (accounts without an email).

## Consequences

- Sign-up needs only a username + password; the email field is optional on
  register, admin-create, and edit.
- Display names are now globally unique — a behaviour change for any assumption
  that two users could share one. Test helpers that reused a fixed display name
  were updated to derive unique names.
- Clearing an existing email via the admin edit form is **not** supported yet
  (blank = leave unchanged); only setting/replacing one is. A future change can
  add an explicit clear if needed.
- SSO (deferred) is unaffected: it still plugs into the same session contract;
  an SSO-provisioned account simply arrives with whatever identifier the provider
  supplies mapped onto display name/email.
