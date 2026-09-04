"""Custom registration-field routes (#350).

Two surfaces, two gates:

- **Definitions** — an organiser authors the field set (``PUT``, gated
  ``edit_competition``); the set is *readable* (``GET``) by anyone who can see
  the competition, because the join / team-creation form needs it to render.
  Field labels are form metadata, not personal data.
- **Values** — a subject's answers are personal data (``PRIVACY.md``): a subject
  reads/writes only their own (``/me``, individual mode); an organiser reads the
  whole roster's for the operator export (``/export``). Never public.

Collection *at entry* (individual join, team creation) lives in those routers;
this one owns definitions, individual self-service, and the export.
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, require_permission
from db import get_db
from utils.competitions import get_visible_competition
from utils.csv_safe import csv_safe
from models.competition import Competition
from models.registration_field import RegistrationFieldValues
from models.role import Role, RoleAssignment
from models.team import Team
from models.user import User
from schemas.registration_field import (
    RegistrationFieldOut,
    RegistrationFieldsUpdate,
    RegistrationValuesIn,
    RegistrationValuesOut,
)
from utils.event_bus import event_bus
from utils.registration_fields import (
    get_values,
    list_fields,
    replace_fields,
    set_values,
    validate_values,
)

router = APIRouter(
    prefix="/api/competitions/{competition_id}/registration-fields",
    tags=["registration-fields"],
)


async def _competition_or_404(db: AsyncSession, competition_id: str) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


@router.get("", response_model=list[RegistrationFieldOut])
async def get_fields(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """The competition's field definitions, in form order. Readable by anyone who
    can *see* the competition — a public competition's fields render on its join
    form before the user is a member; a private competition's fields (and its
    very existence) stay hidden from non-members, so a label like "medical needs"
    can't be enumerated across competitions. The answers are the sensitive part,
    strictly gated below."""
    if await get_visible_competition(db, competition_id, current_user) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return await list_fields(db, competition_id)


@router.put("", response_model=list[RegistrationFieldOut])
async def put_fields(
    competition_id: str,
    body: RegistrationFieldsUpdate,
    current_user: User = Depends(require_permission("edit_competition")),
    db: AsyncSession = Depends(get_db),
) -> list:
    """Replace the competition's field set (organiser only)."""
    await _competition_or_404(db, competition_id)
    fields = await replace_fields(db, competition_id, body.fields)
    await db.commit()
    for field in fields:
        await db.refresh(field)
    await event_bus.emit(
        "registration_field.updated",
        {"competition_id": competition_id, "count": len(fields)},
    )
    return fields


@router.get("/me", response_model=RegistrationValuesOut)
async def get_my_values(
    competition_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> RegistrationValuesOut:
    """The individual competitor's own answers. Team-mode values belong to the
    team and are edited through the team, not here."""
    competition = await _competition_or_404(db, competition_id)
    if competition.participation_mode != "individual":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Team-mode custom fields are edited through the team",
        )
    return RegistrationValuesOut(
        values=await get_values(db, competition_id, current_user.id)
    )


@router.put("/me", response_model=RegistrationValuesOut)
async def put_my_values(
    competition_id: str,
    body: RegistrationValuesIn,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> RegistrationValuesOut:
    """An individual competitor edits their own answers (#350: subjects can edit
    their values later). Required fields stay enforced."""
    competition = await _competition_or_404(db, competition_id)
    if competition.participation_mode != "individual":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Team-mode custom fields are edited through the team",
        )
    fields = await list_fields(db, competition_id)
    cleaned = validate_values(fields, body.values)
    await set_values(db, competition_id, current_user.id, cleaned)
    await db.commit()
    await event_bus.emit(
        "registration_field.value_set",
        {"competition_id": competition_id, "subject_id": current_user.id},
    )
    return RegistrationValuesOut(values=cleaned)


@router.get("/export")
async def export_values(
    competition_id: str,
    current_user: User = Depends(require_permission("edit_competition")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """CSV of every subject's answers, for the operator (organiser only, never
    public). One row per subject (team or competitor), a column per field."""
    competition = await _competition_or_404(db, competition_id)
    fields = await list_fields(db, competition_id)

    # Subjects + display names by mode (§13.2).
    if competition.participation_mode == "team":
        subject_label = "Team"
        rows = (
            await db.execute(
                select(Team.id, Team.name).where(Team.competition_id == competition_id)
            )
        ).all()
    else:
        subject_label = "Competitor"
        rows = (
            await db.execute(
                select(User.id, User.display_name)
                .join(RoleAssignment, RoleAssignment.user_id == User.id)
                .join(Role, Role.id == RoleAssignment.role_id)
                .where(
                    RoleAssignment.competition_id == competition_id,
                    Role.name == "Participant",
                )
                .distinct()
            )
        ).all()

    values_by_subject = {
        v.subject_id: (v.values or {})
        for v in (
            await db.execute(
                select(RegistrationFieldValues).where(
                    RegistrationFieldValues.competition_id == competition_id
                )
            )
        ).scalars()
    }

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    # csv_safe every cell (GHSA-352q): subject names and free-text answers are
    # competitor-controlled, field labels are organiser-controlled, and this file
    # is opened in a spreadsheet by an organiser — a leading =/+/-/@ would execute.
    writer.writerow(
        [csv_safe(subject_label)] + [csv_safe(field.label) for field in fields]
    )
    for subject_id, name in sorted(rows, key=lambda r: (r[1] or "").lower()):
        answers = values_by_subject.get(subject_id, {})
        writer.writerow(
            [csv_safe(name)]
            + [csv_safe(answers.get(field.key)) for field in fields]
        )

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="registration-fields-{competition_id}.csv"'
            )
        },
    )
