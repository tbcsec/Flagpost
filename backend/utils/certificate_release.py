"""DB-facing certificate logic — standings→tokens, recipients, release (#219).

Kept apart from the pure renderer (``plugins.certificates.render``) so that
module stays PIL-only; this one owns the scoreboard read, recipient enumeration,
and the release/notification wiring. Reuses the live scoreboard (``live=True`` —
a post-event certificate reflects the *true* final board, not the public freeze
snapshot) so certificates always agree with what the scoreboard showed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update

from db import ensure_aware_utc, utcnow
from models.certificate import CertificateFont, CertificateTemplate
from models.competition import Competition
from models.notification import Notification
from models.role import Role, RoleAssignment
from models.submission import Submission
from models.team import TeamMembership
from models.user import User
from plugins.certificates.assets import placement_label
from utils.notifications import create_notifications
from utils.scoreboard import compute_scoreboard
from utils.scoring import resolve_subject


_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
# An element font ref for an organiser-uploaded font: ``custom:<font-id>``.
CUSTOM_FONT_RE = re.compile(rf"^custom:({_UUID})$")


@dataclass
class Recipient:
    """One participant's certificate identity: the account (for download scoping
    + a ZIP filename) and the resolved token values for the render."""

    user_id: str
    user_name: str
    subject_id: str
    tokens: dict[str, str]


# --- render-spec + asset resolution (shared by routes + the export scheduler) --


def spec_from_template(t: CertificateTemplate) -> dict:
    """The render spec for a template — background config (incl. per-preset colour
    overrides and the uploaded-background key) + elements. One source of truth so
    the single self-download and the bulk ZIP export render identically."""
    return {
        "background_kind": t.background_kind,
        "background_preset": t.background_preset,
        "background_color": t.background_color,
        "preset_accent": t.preset_accent,
        "preset_base": t.preset_base,
        "background_object_key": t.background_object_key,
        "elements": t.elements or [],
    }


def custom_font_ids(elements: list) -> set[str]:
    """The distinct ``custom:<id>`` font refs used by ``elements``."""
    out: set[str] = set()
    for el in elements or []:
        font = el.get("font") if isinstance(el, dict) else None
        if isinstance(font, str) and CUSTOM_FONT_RE.match(font):
            out.add(font)
    return out


def gather_image_bytes(storage, elements: list, competition_id: str) -> dict[str, bytes]:
    """Fetch every image element's bytes, keyed by storage key. Defence-in-depth:
    only ever reads keys under THIS competition's namespace (§6.2 tenancy), so a
    stale/out-of-scope key can't pull another tenant's object into a render."""
    prefix = f"{competition_id}/certificates/"
    out: dict[str, bytes] = {}
    for el in elements or []:
        if isinstance(el, dict) and el.get("type") == "image":
            key = el.get("image_key")
            if key and key not in out and key.startswith(prefix):
                try:
                    out[key] = storage.get(key)
                except Exception:
                    pass
    return out


async def load_custom_font_bytes(
    db, storage, competition_id: str, elements: list
) -> dict[str, bytes]:
    """Resolve the ``custom:<id>`` fonts an ``elements`` list references into
    ``{ref: bytes}`` for the renderer. Scoped to this competition's rows, so a ref
    to another competition's font (or a deleted one) simply isn't returned — the
    renderer then falls back to a bundled default."""
    refs = custom_font_ids(elements)
    if not refs:
        return {}
    ids = [m.group(1) for f in refs if (m := CUSTOM_FONT_RE.match(f))]
    rows = (
        await db.execute(
            select(CertificateFont).where(
                CertificateFont.competition_id == competition_id,
                CertificateFont.id.in_(ids),
            )
        )
    ).scalars().all()
    out: dict[str, bytes] = {}
    for row in rows:
        try:
            out[f"custom:{row.id}"] = storage.get(row.object_key)
        except Exception:
            pass
    return out


def _fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return ""
    dt = ensure_aware_utc(dt)
    return f"{dt.day} {dt.strftime('%B %Y')}"


async def _solve_counts(db, competition: Competition) -> dict[str, int]:
    """subject_id → distinct challenges solved, mirroring the scoreboard's
    subject rule (team in team-mode; the user's own non-team rows individually)."""
    team_mode = competition.participation_mode == "team"
    subj = Submission.team_id if team_mode else Submission.user_id
    stmt = (
        select(subj, func.count(func.distinct(Submission.challenge_id)))
        .where(
            Submission.competition_id == competition.id,
            Submission.is_correct.is_(True),
            Submission.is_duplicate.is_(False),
            subj.is_not(None),
        )
        .group_by(subj)
    )
    if not team_mode:
        stmt = stmt.where(Submission.team_id.is_(None))
    rows = await db.execute(stmt)
    return {sid: n for sid, n in rows if sid}


async def _load_context(db, competition: Competition):
    board = await compute_scoreboard(db, competition, live=True)
    entries = {e["subject_id"]: e for e in board["entries"]}
    solves = await _solve_counts(db, competition)
    return entries, solves, len(board["entries"])


def _scored(entry: dict, solve_count: int) -> bool:
    return entry["points"] > 0 or solve_count > 0


def _passes_rule(template: CertificateTemplate, entry: dict, solve_count: int) -> bool:
    if template.recipient_rule == "solvers":
        return _scored(entry, solve_count)
    return True


def _build_tokens(
    competition: Competition, entry: dict, solve_count: int, participant_count: int, now: datetime
) -> dict[str, str]:
    return {
        "recipient_name": entry["name"],
        "competition_name": competition.name,
        "placement": placement_label(entry["rank"], is_scorer=_scored(entry, solve_count)),
        "points": f"{entry['points']:,}",
        "solve_count": str(solve_count),
        "bracket": entry.get("bracket") or "",
        "participant_count": str(participant_count),
        "competition_end_date": _fmt_date(competition.end_at),
        "issue_date": _fmt_date(now),
    }


async def build_recipients(
    db, competition: Competition, template: CertificateTemplate, *, now: datetime | None = None
) -> list[Recipient]:
    """Every participant who should receive a certificate under the template's
    recipient rule — one per **user** (team-mode users share their team's
    standing), used for notifications and the bulk ZIP export."""
    now = now or utcnow()
    entries, solves, count = await _load_context(db, competition)
    recipients: list[Recipient] = []

    if competition.participation_mode == "team":
        rows = (
            await db.execute(
                select(TeamMembership.user_id, TeamMembership.team_id, User.display_name)
                .join(User, User.id == TeamMembership.user_id)
                .where(TeamMembership.competition_id == competition.id)
            )
        ).all()
        for user_id, team_id, display_name in rows:
            entry = entries.get(team_id)
            if entry is None:
                continue
            sc = solves.get(team_id, 0)
            if not _passes_rule(template, entry, sc):
                continue
            recipients.append(
                Recipient(user_id, display_name, team_id, _build_tokens(competition, entry, sc, count, now))
            )
    else:
        rows = (
            await db.execute(
                select(User.id, User.display_name)
                .join(RoleAssignment, RoleAssignment.user_id == User.id)
                .join(Role, Role.id == RoleAssignment.role_id)
                .where(
                    RoleAssignment.competition_id == competition.id,
                    Role.name == "Participant",
                )
                .distinct()
            )
        ).all()
        for user_id, display_name in rows:
            entry = entries.get(user_id)
            if entry is None:
                continue
            sc = solves.get(user_id, 0)
            if not _passes_rule(template, entry, sc):
                continue
            recipients.append(
                Recipient(user_id, display_name, user_id, _build_tokens(competition, entry, sc, count, now))
            )
    return recipients


async def resolve_one(
    db,
    competition: Competition,
    template: CertificateTemplate,
    user: User,
    *,
    now: datetime | None = None,
) -> Recipient | None:
    """This user's certificate identity, or None if they aren't an eligible
    recipient (team-mode not on a team, or excluded by the recipient rule)."""
    now = now or utcnow()
    subject = await resolve_subject(db, competition, user)
    if subject is None:
        return None
    entries, solves, count = await _load_context(db, competition)
    entry = entries.get(subject.id)
    if entry is None:
        return None
    sc = solves.get(subject.id, 0)
    if not _passes_rule(template, entry, sc):
        return None
    return Recipient(user.id, user.display_name, subject.id, _build_tokens(competition, entry, sc, count, now))


async def release_template(
    db, competition: Competition, template: CertificateTemplate, *, now: datetime | None = None
) -> list[Notification] | None:
    """Atomically mark the template released and create a notification per
    recipient. Returns the created rows, or **None** if it was already released
    (a concurrent caller won) — the caller then skips the broadcast + emit.

    Does **not** commit or broadcast — the caller commits (so the release is
    durable before any handler runs, CLAUDE.md "commit before emitting"), then
    broadcasts the returned rows and emits ``certificate.released``."""
    now = now or utcnow()
    # Guard the transition on ``released_at IS NULL`` in the UPDATE itself, so two
    # concurrent releases (or a manual release racing the scheduled tick) can't
    # both pass a read-then-write check and double-notify — only the row-flipping
    # caller proceeds.
    result = await db.execute(
        update(CertificateTemplate)
        .where(
            CertificateTemplate.id == template.id,
            CertificateTemplate.released_at.is_(None),
        )
        .values(released_at=now)
    )
    if result.rowcount == 0:
        return None
    template.released_at = now  # reflect on the in-memory instance for the response
    recipients = await build_recipients(db, competition, template, now=now)
    return await create_notifications(
        db,
        [r.user_id for r in recipients],
        type="certificate.released",
        title="Your certificate is ready",
        body=f"View and download your certificate for {competition.name}.",
        link="/profile?tab=certificates",
        competition_id=competition.id,
    )
