"""Category routes (ROADMAP #9) — simple tagging/grouping for challenges.

Nested under the competition path so every query is scoped (§6.2). Managing
categories is part of authoring challenges, so writes are gated on
``challenge_edit``; reading uses ``challenge_view`` (§7.1 — no separate
category permission exists, deliberately).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.challenge import Category
from models.user import User
from schemas.category import CategoryCreate, CategoryOut
from utils.event_bus import event_bus

router = APIRouter(
    prefix="/api/competitions/{competition_id}/categories", tags=["categories"]
)


@router.get("", response_model=list[CategoryOut])
async def list_categories(
    competition_id: str,
    _user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[Category]:
    result = await db.execute(
        select(Category)
        .where(Category.competition_id == competition_id)
        .order_by(Category.name)
    )
    return list(result.scalars().all())


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    competition_id: str,
    body: CategoryCreate,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
) -> Category:
    exists = await db.scalar(
        select(Category).where(
            Category.competition_id == competition_id,
            Category.name == body.name,
        )
    )
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A category with that name already exists",
        )
    category = Category(competition_id=competition_id, name=body.name)
    db.add(category)
    await db.commit()

    await event_bus.emit(
        "category.created",
        {
            "competition_id": competition_id,
            "category_id": category.id,
            "user_id": current_user.id,
            "name": category.name,
        },
    )
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    competition_id: str,
    category_id: str,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
) -> None:
    category = await db.scalar(
        select(Category).where(
            Category.competition_id == competition_id, Category.id == category_id
        )
    )
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )
    await db.delete(category)  # challenges keep existing; FK is SET NULL
    await db.commit()

    await event_bus.emit(
        "category.deleted",
        {
            "competition_id": competition_id,
            "category_id": category_id,
            "user_id": current_user.id,
        },
    )
