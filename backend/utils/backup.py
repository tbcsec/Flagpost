"""Platform export / import — a full-fidelity, selective backup (Phase 9 owner ask).

Export serialises whole tables to a single versioned JSON document; the admin
picks which **sections** to include (checkboxes). Import reads that document back
**additively** — it *creates records that don't already exist and never modifies
or deletes* what's there (owner decision). See ADR-0016.

Design: rather than hand-code every entity, a generic column (de)serialiser plus
a declared ``SPECS`` registry does the work. Each :class:`Spec` names a table,
its section, which FK columns to remap (via id maps built during import), whether
it is *owned by a competition* (so it's skipped wholesale when that competition
already exists), and how to detect an already-present row (``natural_key``). New
ids are minted on create and cross-references rewritten through the id maps, so a
document restores cleanly into a different install.

Excluded by design: ``refresh_sessions`` (secrets), and the transient/derived
``notifications`` / ``collab_documents`` / ``dashboard_layouts`` — none belong in
a portable backup.
"""

from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable
from uuid import uuid4

from sqlalchemy import DateTime, LargeBinary, func, inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from db import UtcDateTime, utcnow
from models.announcement import Announcement
from models.attachment import Attachment
from models.audit_log import AuditLogEntry
from models.automation import Achievement, AutomationRule
from models.challenge import Category, Challenge
from models.competition import Competition, generate_invite_code
from models.competition_module import CompetitionModule
from models.feedback import Survey, SurveyAnswer, SurveyQuestion, SurveyResponse
from models.hint import Hint, HintReveal
from models.role import Role, RoleAssignment
from models.score_adjustment import ScoreAdjustment
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.submission import Submission
from models.team import Team, TeamMembership
from models.ticket import Ticket, TicketMessage
from models.user import User
from storage.base import ObjectStorage

SCHEMA_VERSION = 1

# The selectable export/import units, in the order the UI lists them.
SECTIONS: tuple[str, ...] = (
    "site_settings",
    "users",
    "roles",
    "competitions",
    "automations",
    "audit_log",
)


# --- generic column (de)serialisation ---------------------------------------

def serialize_row(obj) -> dict:
    """A JSON-safe dict of every column: datetimes → ISO strings, bytes → base64,
    everything else (incl. ``JSON`` list/dict columns) passes through."""
    out: dict = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            out[col.name] = val.isoformat()
        elif isinstance(val, (bytes, bytearray)):
            out[col.name] = base64.b64encode(val).decode("ascii")
        else:
            out[col.name] = val
    return out


def _typed_cols(model) -> tuple[set[str], set[str]]:
    dt = {c.name for c in model.__table__.columns if isinstance(c.type, (DateTime, UtcDateTime))}
    bin_ = {c.name for c in model.__table__.columns if isinstance(c.type, LargeBinary)}
    return dt, bin_


def load_row(model, row: dict) -> dict:
    """Inverse of :func:`serialize_row`, keyed off column types; drops any keys
    that aren't real columns (e.g. the attachment's side-car ``_object_data``)."""
    dt_cols, bin_cols = _typed_cols(model)
    cols = {c.name for c in model.__table__.columns}
    out: dict = {}
    for key, val in row.items():
        if key not in cols:
            continue
        if val is not None and key in dt_cols:
            val = datetime.fromisoformat(val)
        elif val is not None and key in bin_cols:
            val = base64.b64decode(val)
        out[key] = val
    return out


# --- registry ----------------------------------------------------------------

NaturalKey = Callable[[AsyncSession, dict], Awaitable[str | None]]


@dataclass(frozen=True)
class Spec:
    table: str
    model: type
    section: str
    id_map: str | None = None
    # (column, map_name, required): if the column is non-null it's rewritten via
    # the map; ``required`` non-null values that don't resolve skip the whole row,
    # otherwise the column is nulled (mirrors SET NULL vs CASCADE FKs).
    remaps: tuple[tuple[str, str, bool], ...] = ()
    owned_by_competition: bool = False
    natural_key: NaturalKey | None = None
    regenerate: tuple[str, ...] = ()
    singleton: bool = False
    keep_id: bool = False


async def _nk_user(db: AsyncSession, row: dict) -> str | None:
    name = (row.get("display_name") or "").strip().lower()
    hit = await db.scalar(select(User.id).where(func.lower(User.display_name) == name))
    if hit is None and row.get("email"):
        hit = await db.scalar(
            select(User.id).where(func.lower(User.email) == row["email"].strip().lower())
        )
    return hit


async def _nk_role(db: AsyncSession, row: dict) -> str | None:
    return await db.scalar(select(Role.id).where(Role.name == row["name"]))


async def _nk_competition(db: AsyncSession, row: dict) -> str | None:
    return await db.scalar(select(Competition.id).where(Competition.name == row["name"]))


async def _nk_assignment(db: AsyncSession, row: dict) -> str | None:
    stmt = select(RoleAssignment.id).where(
        RoleAssignment.user_id == row.get("user_id"),
        RoleAssignment.role_id == row.get("role_id"),
        RoleAssignment.competition_id.is_(None)
        if row.get("competition_id") is None
        else RoleAssignment.competition_id == row.get("competition_id"),
    )
    return await db.scalar(stmt)


async def _nk_automation(db: AsyncSession, row: dict) -> str | None:
    stmt = select(AutomationRule.id).where(
        AutomationRule.name == row.get("name"),
        AutomationRule.trigger_type == row.get("trigger_type"),
        AutomationRule.competition_id.is_(None)
        if row.get("competition_id") is None
        else AutomationRule.competition_id == row.get("competition_id"),
        AutomationRule.owner_user_id.is_(None)
        if row.get("owner_user_id") is None
        else AutomationRule.owner_user_id == row.get("owner_user_id"),
    )
    return await db.scalar(stmt)


async def _nk_audit(db: AsyncSession, row: dict) -> str | None:
    return await db.scalar(select(AuditLogEntry.id).where(AuditLogEntry.id == row.get("id")))


_COMP = ("competition_id", "competition", True)

# Order matters: a table's referenced entities must be imported before it.
SPECS: tuple[Spec, ...] = (
    Spec("site_settings", SiteSettings, "site_settings", singleton=True),
    Spec("users", User, "users", id_map="user", natural_key=_nk_user),
    Spec("roles", Role, "roles", id_map="role", natural_key=_nk_role),
    Spec("competitions", Competition, "competitions", id_map="competition",
         natural_key=_nk_competition, regenerate=("invite_code",)),
    # Competition-owned live data (skipped wholesale when the competition exists).
    Spec("categories", Category, "competitions", id_map="category",
         remaps=(_COMP,), owned_by_competition=True),
    Spec("challenges", Challenge, "competitions", id_map="challenge",
         remaps=(_COMP, ("category_id", "category", False)), owned_by_competition=True),
    Spec("hints", Hint, "competitions", id_map="hint",
         remaps=(_COMP, ("challenge_id", "challenge", True)), owned_by_competition=True),
    Spec("attachments", Attachment, "competitions",
         remaps=(_COMP, ("challenge_id", "challenge", True)), owned_by_competition=True),
    Spec("teams", Team, "competitions", id_map="team",
         remaps=(_COMP,), owned_by_competition=True, regenerate=("invite_code",)),
    Spec("team_memberships", TeamMembership, "competitions",
         remaps=(_COMP, ("team_id", "team", True), ("user_id", "user", True)),
         owned_by_competition=True),
    Spec("submissions", Submission, "competitions",
         remaps=(_COMP, ("challenge_id", "challenge", True), ("user_id", "user", True),
                 ("team_id", "team", False)), owned_by_competition=True),
    Spec("score_adjustments", ScoreAdjustment, "competitions",
         remaps=(_COMP, ("user_id", "user", False), ("team_id", "team", False),
                 ("rule_id", "automation_rule", False)), owned_by_competition=True),
    Spec("surveys", Survey, "competitions", id_map="survey",
         remaps=(_COMP,), owned_by_competition=True),
    Spec("survey_questions", SurveyQuestion, "competitions", id_map="survey_question",
         remaps=(_COMP, ("survey_id", "survey", True)), owned_by_competition=True),
    Spec("survey_responses", SurveyResponse, "competitions", id_map="survey_response",
         remaps=(_COMP, ("survey_id", "survey", True), ("user_id", "user", True)),
         owned_by_competition=True),
    Spec("survey_answers", SurveyAnswer, "competitions",
         remaps=(_COMP, ("response_id", "survey_response", True),
                 ("question_id", "survey_question", True)), owned_by_competition=True),
    Spec("tickets", Ticket, "competitions", id_map="ticket",
         remaps=(_COMP, ("challenge_id", "challenge", False), ("opener_user_id", "user", True),
                 ("team_id", "team", False), ("assignee_user_id", "user", False)),
         owned_by_competition=True),
    Spec("ticket_messages", TicketMessage, "competitions",
         remaps=(_COMP, ("ticket_id", "ticket", True), ("author_user_id", "user", True)),
         owned_by_competition=True),
    Spec("hint_reveals", HintReveal, "competitions",
         remaps=(_COMP, ("hint_id", "hint", True), ("challenge_id", "challenge", True),
                 ("user_id", "user", True), ("team_id", "team", False)),
         owned_by_competition=True),
    Spec("announcements", Announcement, "competitions",
         remaps=(_COMP, ("created_by", "user", False)), owned_by_competition=True),
    Spec("achievements", Achievement, "competitions",
         remaps=(_COMP, ("user_id", "user", False), ("team_id", "team", False),
                 ("rule_id", "automation_rule", False)), owned_by_competition=True),
    Spec("competition_modules", CompetitionModule, "competitions",
         remaps=(_COMP,), owned_by_competition=True),
    # Cross-cutting collections — additive per row (own natural key), imported
    # after competitions so their competition refs resolve.
    Spec("role_assignments", RoleAssignment, "roles",
         remaps=(("user_id", "user", True), ("role_id", "role", True),
                 ("competition_id", "competition", True)), natural_key=_nk_assignment),
    Spec("automation_rules", AutomationRule, "automations", id_map="automation_rule",
         remaps=(("competition_id", "competition", True), ("owner_user_id", "user", True)),
         natural_key=_nk_automation),
    Spec("audit_log", AuditLogEntry, "audit_log", natural_key=_nk_audit, keep_id=True),
)


# --- export ------------------------------------------------------------------

async def export_data(
    db: AsyncSession, storage: ObjectStorage, sections: list[str]
) -> dict:
    picked = [s for s in SECTIONS if s in sections]
    data: dict[str, list[dict]] = {}
    for spec in SPECS:
        if spec.section not in picked:
            continue
        stmt = select(spec.model)
        # Undefer any deferred columns (e.g. the site-settings logo blob) so
        # serialising them here doesn't trigger a forbidden async lazy-load.
        deferred = [a.key for a in sa_inspect(spec.model).column_attrs if a.deferred]
        if deferred:
            stmt = stmt.options(*[undefer(getattr(spec.model, k)) for k in deferred])
        rows = (await db.scalars(stmt)).all()
        serialised: list[dict] = []
        for r in rows:
            d = serialize_row(r)
            if spec.table == "attachments":
                try:
                    d["_object_data"] = base64.b64encode(storage.get(r.object_key)).decode("ascii")
                except Exception:  # noqa: BLE001 — a missing object shouldn't abort the export
                    d["_object_data"] = None
            serialised.append(d)
        data[spec.table] = serialised
    return {
        "flagpost_export": True,
        "schema_version": SCHEMA_VERSION,
        "exported_at": utcnow().isoformat(),
        "sections": picked,
        "data": data,
    }


# --- import ------------------------------------------------------------------

@dataclass
class _State:
    maps: dict[str, dict[str, str]] = field(default_factory=lambda: defaultdict(dict))
    skipped_competitions: set[str] = field(default_factory=set)


class ImportError_(ValueError):
    """Raised for a malformed or unsupported export document."""


async def import_data(
    db: AsyncSession, storage: ObjectStorage, payload: dict, sections: list[str]
) -> dict[str, dict[str, int]]:
    if not isinstance(payload, dict) or not payload.get("flagpost_export"):
        raise ImportError_("Not a Flagpost export file")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ImportError_(
            f"Unsupported export version {payload.get('schema_version')!r} "
            f"(this install reads v{SCHEMA_VERSION})"
        )
    data = payload.get("data") or {}
    picked = [s for s in SECTIONS if s in sections]
    state = _State()
    result: dict[str, dict[str, int]] = {}

    for spec in SPECS:
        if spec.section not in picked:
            continue
        created = skipped = 0
        for raw in data.get(spec.table, []):
            row = dict(raw)
            object_data = row.pop("_object_data", None)

            if spec.singleton:
                await _upsert_singleton(db, spec.model, row)
                created += 1
                continue

            # A row belonging to an already-present competition is skipped whole.
            if spec.owned_by_competition and row.get("competition_id") in state.skipped_competitions:
                skipped += 1
                continue

            if not _remap(row, spec, state):
                skipped += 1
                continue

            old_id = row.get("id")
            if spec.natural_key is not None:
                existing = await spec.natural_key(db, row)
                if existing is not None:
                    if spec.id_map and old_id is not None:
                        state.maps[spec.id_map][old_id] = existing
                    if spec.table == "competitions" and old_id is not None:
                        state.skipped_competitions.add(old_id)
                    skipped += 1
                    continue

            new_id = old_id if spec.keep_id else str(uuid4())
            if "id" in row:
                row["id"] = new_id
            for col in spec.regenerate:
                row[col] = generate_invite_code()
            if spec.table == "attachments" and object_data:
                row["object_key"] = f"{row['competition_id']}/{row['challenge_id']}/{uuid4().hex}_{row.get('filename', 'file')}"

            obj = spec.model(**load_row(spec.model, row))
            db.add(obj)
            await db.flush()

            if spec.table == "attachments" and object_data:
                storage.put(row["object_key"], base64.b64decode(object_data), obj.content_type)
            if spec.id_map and old_id is not None:
                state.maps[spec.id_map][old_id] = new_id
            created += 1

        result[spec.table] = {"created": created, "skipped": skipped}

    await db.commit()
    return result


def _remap(row: dict, spec: Spec, state: _State) -> bool:
    """Rewrite FK columns through the id maps. Returns False if the row must be
    dropped (a required reference didn't resolve)."""
    for col, map_name, required in spec.remaps:
        old = row.get(col)
        if old is None:
            continue
        new = state.maps[map_name].get(old)
        if new is None:
            if required:
                return False
            row[col] = None
        else:
            row[col] = new
    return True


async def _upsert_singleton(db: AsyncSession, model, row: dict) -> None:
    obj = await db.get(model, SITE_SETTINGS_ID)
    if obj is None:
        obj = model(id=SITE_SETTINGS_ID)
        db.add(obj)
    for key, val in load_row(model, row).items():
        if key == "id":
            continue
        setattr(obj, key, val)
