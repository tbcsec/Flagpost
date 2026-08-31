"""Custom registration fields: definitions, per-subject values, and boundary
validation (#350).

One module owns "what fields does this competition collect and are these
answers valid", because that question is asked at every entry point (individual
join, team creation) and every edit surface (a subject editing their own
answers, a captain editing the team's), and they must never disagree. Validation
is at the boundary — required-ness and type/choice are enforced here before a
values row is written, mirroring ``utils/brackets.set_bracket``'s validate-then-
upsert shape.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.registration_field import RegistrationField, RegistrationFieldValues

# A single free-text answer is capped so a value row can't grow without bound.
MAX_VALUE_LENGTH = 2000


async def list_fields(
    db: AsyncSession, competition_id: str
) -> list[RegistrationField]:
    """The competition's field definitions, in form order (§6.2 scoped)."""
    rows = await db.execute(
        select(RegistrationField)
        .where(RegistrationField.competition_id == competition_id)
        .order_by(RegistrationField.position, RegistrationField.key)
    )
    return list(rows.scalars().all())


async def replace_fields(
    db: AsyncSession, competition_id: str, specs
) -> list[RegistrationField]:
    """Replace the competition's whole field set (the managed-vocab idiom). Values
    are keyed by field ``key``, so a subject's answers survive as long as the key
    is kept — a removed/renamed field simply leaves its old value unreferenced,
    the same not-cascaded behaviour a removed tag has on a challenge."""
    await db.execute(
        delete(RegistrationField).where(
            RegistrationField.competition_id == competition_id
        )
    )
    created: list[RegistrationField] = []
    for spec in specs:
        field = RegistrationField(
            competition_id=competition_id,
            key=spec.key,
            label=spec.label,
            field_type=spec.field_type,
            options=spec.options or None,
            required=spec.required,
            position=spec.position,
        )
        db.add(field)
        created.append(field)
    return created


def validate_values(
    fields: list[RegistrationField],
    submitted: dict,
    *,
    require_required: bool = True,
) -> dict:
    """Coerce + validate ``submitted`` against ``fields``, returning the cleaned
    ``{key: value}`` to store. Enforces required-ness (when asked), type coercion
    (checkbox → bool, everything else → a length-bounded string), and select
    membership. Unknown keys are dropped — the definitions are the authority, so
    a client can't smuggle arbitrary data into the values blob. Raises 422 at the
    boundary on the first violation."""
    cleaned: dict = {}
    for field in fields:
        raw = submitted.get(field.key)
        present = raw is not None and not (isinstance(raw, str) and not raw.strip())
        if not present:
            if field.required and require_required:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"'{field.label}' is required",
                )
            continue
        cleaned[field.key] = _coerce(field, raw)
    return cleaned


def _coerce(field: RegistrationField, raw: object) -> object:
    if field.field_type == "checkbox":
        # Defensive: a client sending the *string* "false"/"0" must not become
        # True (a non-empty string is truthy). Only genuine truthy tokens count.
        if isinstance(raw, str):
            return raw.strip().lower() in ("true", "1", "yes", "on")
        return bool(raw)
    value = str(raw).strip()
    if len(value) > MAX_VALUE_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{field.label}' is too long",
        )
    if field.field_type == "select" and value not in (field.options or []):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{value}' is not a valid choice for '{field.label}'",
        )
    return value


async def get_values(
    db: AsyncSession, competition_id: str, subject_id: str
) -> dict:
    """A subject's stored answers, or ``{}`` if none yet."""
    row = (
        await db.execute(
            select(RegistrationFieldValues).where(
                RegistrationFieldValues.competition_id == competition_id,
                RegistrationFieldValues.subject_id == subject_id,
            )
        )
    ).scalar_one_or_none()
    return dict(row.values) if row and row.values else {}


async def set_values(
    db: AsyncSession, competition_id: str, subject_id: str, cleaned: dict
) -> None:
    """Upsert a subject's cleaned answers (one row per subject, §13.2). A no-op
    write of ``{}`` is skipped so entering a competition with no custom fields
    doesn't create an empty row."""
    row = (
        await db.execute(
            select(RegistrationFieldValues).where(
                RegistrationFieldValues.competition_id == competition_id,
                RegistrationFieldValues.subject_id == subject_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        if not cleaned:
            return
        db.add(
            RegistrationFieldValues(
                competition_id=competition_id,
                subject_id=subject_id,
                values=cleaned,
            )
        )
    else:
        row.values = cleaned
