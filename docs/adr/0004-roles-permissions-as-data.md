# ADR-0004: Roles and permissions as data, not a hardcoded enum

**Status:** Accepted
**Date:** 2026-07-17
**Architecture reference:** `ARCHITECTURE.md` §7

## Context

The platform needs three built-in roles (Administrator, Judge,
Participant) that cover the common case out of the box, but also needs
organisers to be able to create narrower custom roles (e.g. a
challenge-author-only role, a read-only observer) without filing a
feature request. A hardcoded role enum (the simpler implementation) can't
support that — every new role or permission tweak would require a code
change and a deploy.

## Decision

Roles are rows in the database (`id`, `name`, `description`, `is_system`,
`scope`, `permissions: list[str]`), not a hardcoded enum. Permissions are
granular, named, categorized capability strings (`challenge_edit`,
`ticket_assign`) rather than baked into role-check logic. The three
built-ins are seeded rows marked `is_system = true` — undeletable and not
directly editable — so "a Judge can always run their own competition"
stays a safe invariant other features can build on; an admin wanting a
variant clones the built-in into a new, fully editable custom role.

## Consequences

- Positive: creating or fine-tuning a role is a data change (an admin
  action through the UI), never a code change or deploy — directly what
  the custom-role requirement needed.
- Positive: enforcement collapses to one shared dependency
  (`require_permission`, §7.6) instead of per-endpoint role lists, so
  adding a new permission or changing what a role can do never touches
  route code.
- Negative / cost: permission checks are a runtime database lookup
  (role → permission set) rather than a compile-time-checked enum
  comparison — a typo'd permission string fails silently (403s) rather
  than failing to compile. Worth a lint/test step that validates every
  `require_permission(...)` call site references a string that actually
  exists in the permission catalog (§7.1).
- Forecloses: static analysis catching "this role can never reach this
  code path" the way an exhaustive enum match would. That tradeoff is
  accepted deliberately in exchange for runtime configurability being a
  first-class feature, not an afterthought bolted onto an enum later.
