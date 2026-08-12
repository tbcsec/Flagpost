"""Mass user import from CSV (#171).

The bulk counterpart to admin single-create (``POST /api/users``): parse a
roster CSV, validate every row against the same rules the single path enforces,
and — on the commit pass — create the accounts (and optional role assignments)
atomically. Two-phase by design: the router runs this planner twice, once as a
``dry_run`` preview (no writes) and once to commit, so the admin sees every
duplicate/typo before a single row lands and the commit pass has nothing left
that can surprise-fail on a unique constraint (the failure mode CTFd's
best-effort per-row importer is known for).

Row semantics (issue #171, resolved decisions):
- **create-only and non-destructive** — an existing account (case-insensitive
  ``display_name`` or ``email`` match) is a *skip*, never an update, so
  re-running a corrected file is safe;
- **data errors kill the row** (bad email, short password, unknown role,
  unknown/ambiguous competition name) — fix the file;
- **authorization limits only warn**: a role the actor can't grant (missing
  ``manage_roles``, or the role exceeds their own permission set — the
  ``routers.roles._assert_may_grant`` bound) still creates the account and
  skips the role with a per-row warning. Ease of use first; a privilege change
  is never silent and never beyond the actor's own grant.

Competitions resolve by **name only** (ids are internal, never user-facing);
an ambiguous name is a row error the UI's default-competition selector solves.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from pydantic import TypeAdapter
from pydantic.networks import EmailStr
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.membership import effective_permissions
from models.competition import Competition
from models.role import Role, RoleAssignment
from models.user import User

# Bounds "how mass": argon2 hashing is deliberately CPU-slow — the 500-user
# load test measured ~64 ms/row on a 4-vCPU box — and the commit pass costs
# O(rows) hash time even off-thread. The old 1000 cap was dishonest: a
# full-size import ran ~64 s and blew past a 30 s client/proxy timeout while
# *succeeding server-side*, so the operator saw a failure for an import that
# actually landed (docs/load-testing/2026-08-12-500user-multicomp.md, #1). 200
# rows ≈ 13 s — comfortably under a default timeout. Larger rosters are split
# into batches by the caller (the load harness dogfoods this); a background
# import job for bigger single uploads is the deferred follow-up (#189).
MAX_IMPORT_ROWS = 200

_KNOWN_COLUMNS = frozenset(
    {"display_name", "name", "email", "password", "role", "competition"}
)
_EMAIL = TypeAdapter(EmailStr)


class UserImportError(ValueError):
    """A malformed file (encoding, header, structure) — the 400 class."""


class UserImportTooLarge(UserImportError):
    """More data rows than ``MAX_IMPORT_ROWS`` — the 413 class."""


@dataclass
class ParsedRow:
    """One data row, whitespace-stripped; empty string means the cell was blank."""

    line: int
    display_name: str
    email: str
    password: str
    role: str
    competition: str


@dataclass
class RowPlan:
    """A validated row with its outcome and (for executable rows) the resolved
    references the commit pass needs. ``password`` never leaves this process —
    the report schema deliberately has no field for it."""

    line: int
    display_name: str
    email: str | None
    role_name: str | None
    competition_name: str | None
    status: str  # "create" | "skip" | "error"
    reason: str | None = None
    role_action: str | None = None  # "assign" | "skip" | None
    role_reason: str | None = None
    # Execution refs (excluded from the report by the response schema).
    password: str = field(default="", repr=False)
    existing_user_id: str | None = None
    role_id: str | None = None
    target_competition_id: str | None = None


def parse_users_csv(
    data: bytes, *, max_rows: int = MAX_IMPORT_ROWS
) -> tuple[list[ParsedRow], list[str]]:
    """Parse the uploaded CSV into rows plus the list of ignored column names.

    Header-driven (column order doesn't matter) and BOM-tolerant so an
    Excel-authored file works. ``name`` is accepted as an alias for
    ``display_name`` (CTFd-shaped files mostly just work); unknown columns are
    ignored but reported, so a typo'd optional header (``rolle``) is visible in
    the preview instead of silently dropping every role.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UserImportError("The file must be UTF-8 encoded CSV") from exc

    reader = csv.reader(io.StringIO(text))
    try:
        raw_header = next(reader)
    except StopIteration:
        raise UserImportError("Empty file — the first row must be a header") from None

    header = [h.strip().lower() for h in raw_header]
    known_seen: set[str] = set()
    for h in header:
        if h in _KNOWN_COLUMNS:
            if h in known_seen:
                raise UserImportError(f"Duplicate column: {h}")
            known_seen.add(h)
    ignored = sorted({h for h in header if h and h not in _KNOWN_COLUMNS})

    index = {h: i for i, h in enumerate(header) if h in _KNOWN_COLUMNS}
    if "display_name" in index and "name" in index:
        # Prefer the native header; the alias column is then just extra data.
        ignored.append("name")
        ignored.sort()
    name_col = index["display_name"] if "display_name" in index else index.get("name")

    missing = []
    if name_col is None:
        missing.append("display_name")
    if "password" not in index:
        missing.append("password")
    if missing:
        raise UserImportError(
            "Missing required column(s): " + ", ".join(missing)
        )

    def cell(values: list[str], col: int | None) -> str:
        if col is None or col >= len(values):
            return ""
        return values[col].strip()

    rows: list[ParsedRow] = []
    for values in reader:
        if not any(v.strip() for v in values):
            continue  # blank/trailing lines aren't data
        rows.append(
            ParsedRow(
                line=reader.line_num,
                display_name=cell(values, name_col),
                email=cell(values, index.get("email")),
                password=cell(values, index.get("password")),
                role=cell(values, index.get("role")),
                competition=cell(values, index.get("competition")),
            )
        )
        if len(rows) > max_rows:
            raise UserImportTooLarge(
                f"Too many rows — the limit is {max_rows} accounts per import"
            )
    return rows, ignored


def _valid_email(value: str) -> bool:
    try:
        _EMAIL.validate_python(value)
    except ValueError:
        return False
    return True


async def plan_user_import(
    db: AsyncSession,
    actor: User,
    rows: list[ParsedRow],
    default_competition_id: str | None,
) -> list[RowPlan]:
    """Validate every row and decide its outcome. Read-only — this is both the
    ``dry_run`` response and the commit pass's worklist, so preview and commit
    can never disagree about what a row means."""
    effective = await effective_permissions(db, actor.id)
    actor_global = set(effective["global"])
    can_assign_roles = "manage_roles" in actor_global

    roles_by_name: dict[str, list[Role]] = {}
    for role in (await db.scalars(select(Role))).all():
        roles_by_name.setdefault(role.name.lower(), []).append(role)

    wanted_comps = {r.competition.lower() for r in rows if r.competition}
    comps_by_name: dict[str, list[str]] = {}
    if wanted_comps:
        for comp_id, comp_name in (
            await db.execute(
                select(Competition.id, Competition.name).where(
                    func.lower(Competition.name).in_(wanted_comps)
                )
            )
        ).all():
            comps_by_name.setdefault(comp_name.lower(), []).append(comp_id)

    names = {r.display_name.lower() for r in rows if r.display_name}
    emails = {r.email.lower() for r in rows if r.email}
    conditions = []
    if names:
        conditions.append(func.lower(User.display_name).in_(names))
    if emails:
        conditions.append(func.lower(User.email).in_(emails))
    users_by_name: dict[str, User] = {}
    users_by_email: dict[str, User] = {}
    if conditions:
        for user in (await db.scalars(select(User).where(or_(*conditions)))).all():
            users_by_name[user.display_name.lower()] = user
            if user.email:
                users_by_email[user.email.lower()] = user

    # Existing role assignments for the matched users, so "already holds this
    # role" is a skip rather than a doomed duplicate insert.
    held: set[tuple[str, str, str | None]] = set()
    existing_ids = {u.id for u in users_by_name.values()} | {
        u.id for u in users_by_email.values()
    }
    if existing_ids:
        for user_id, role_id, comp_id in (
            await db.execute(
                select(
                    RoleAssignment.user_id,
                    RoleAssignment.role_id,
                    RoleAssignment.competition_id,
                ).where(RoleAssignment.user_id.in_(existing_ids))
            )
        ).all():
            held.add((user_id, role_id, comp_id))

    plans: list[RowPlan] = []
    seen_names: dict[str, int] = {}
    seen_emails: dict[str, int] = {}
    for row in rows:
        plan = RowPlan(
            line=row.line,
            display_name=row.display_name,
            email=row.email or None,
            role_name=row.role or None,
            competition_name=row.competition or None,
            status="create",
            password=row.password,
        )
        plans.append(plan)

        def fail(reason: str) -> None:
            plan.status = "error"
            plan.reason = reason
            plan.role_action = None
            plan.role_reason = None

        # --- field validation (mirrors schemas.user.UserCreate) -------------
        if not row.display_name:
            fail("display_name is required")
            continue
        if len(row.display_name) > 120:
            fail("display_name is longer than 120 characters")
            continue
        if not row.password:
            fail("password is required")
            continue
        if not 8 <= len(row.password) <= 256:
            fail("password must be 8–256 characters")
            continue
        if row.email and not _valid_email(row.email):
            fail("invalid email address")
            continue

        # --- duplicates within the file --------------------------------------
        name_l = row.display_name.lower()
        email_l = row.email.lower() if row.email else None
        dup_line = seen_names.get(name_l) or (
            seen_emails.get(email_l) if email_l else None
        )
        if dup_line is not None:
            plan.status = "skip"
            plan.reason = f"duplicate of row {dup_line} in this file"
            continue
        seen_names[name_l] = row.line
        if email_l:
            seen_emails[email_l] = row.line

        # --- duplicates against the directory (create-only, never update) ----
        by_name = users_by_name.get(name_l)
        by_email = users_by_email.get(email_l) if email_l else None
        if by_name is not None and by_email is not None and by_name.id != by_email.id:
            fail("display_name and email belong to two different existing accounts")
            continue
        existing = by_name or by_email
        if existing is not None:
            plan.status = "skip"
            plan.reason = "already exists"
            plan.existing_user_id = existing.id
            # Fall through: a role on the row still applies to the account.

        # --- role resolution (data errors kill the row) -----------------------
        if not row.role:
            continue
        candidates = roles_by_name.get(row.role.lower(), [])
        if not candidates:
            fail(f"unknown role {row.role!r}")
            continue
        if len(candidates) > 1:
            fail(f"ambiguous role name {row.role!r}")
            continue
        role = candidates[0]
        plan.role_name = role.name  # canonical casing for the report + events

        target_competition: str | None = None
        if role.scope == "global":
            if row.competition:
                fail("a global role is assigned site-wide — leave competition empty")
                continue
        else:
            if row.competition:
                comp_ids = comps_by_name.get(row.competition.lower(), [])
                if not comp_ids:
                    fail(f"unknown competition {row.competition!r}")
                    continue
                if len(comp_ids) > 1:
                    fail(
                        f"ambiguous competition name {row.competition!r} "
                        f"({len(comp_ids)} competitions share it)"
                    )
                    continue
                target_competition = comp_ids[0]
            elif default_competition_id is not None:
                target_competition = default_competition_id
            else:
                fail(
                    "a competition-scoped role needs a competition "
                    "(column or the import's default)"
                )
                continue

        # --- grant containment (authorization limits only warn) --------------
        if not can_assign_roles:
            plan.role_action = "skip"
            plan.role_reason = "you don't hold manage_roles"
            continue
        shortfall = sorted(set(role.permissions) - actor_global)
        if shortfall:
            plan.role_action = "skip"
            plan.role_reason = (
                "role exceeds your own permissions: " + ", ".join(shortfall)
            )
            continue
        if (
            plan.existing_user_id is not None
            and (plan.existing_user_id, role.id, target_competition) in held
        ):
            plan.role_action = "skip"
            plan.role_reason = "already holds this role"
            continue
        plan.role_action = "assign"
        plan.role_id = role.id
        plan.target_competition_id = target_competition

    return plans
