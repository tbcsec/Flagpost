"""First-run setup wizard (ADR-0017).

Public, single-use provisioning: while the instance has no Administrator, an
operator posts the owner account + initial branding here. It creates the admin
(with a global Administrator assignment — the one path above Participant), applies
the site settings, and logs the new admin in. Once an admin exists it 409s, so it
can't be used to mint a second owner or reset an install.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth.identity import display_name_taken, email_taken
from auth.security import hash_password
from auth.setup import ADMINISTRATOR_ROLE_NAME, setup_is_complete
from db import get_db, utcnow
from models.role import Role, RoleAssignment
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import User
from routers.auth import _issue_session
from routers.site_settings import get_or_create_settings
from schemas.auth import TokenResponse, UserOut
from schemas.setup import SetupRequest, SetupStatusOut
from utils.event_bus import event_bus

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatusOut)
async def setup_status(db: AsyncSession = Depends(get_db)) -> SetupStatusOut:
    """Public: the frontend redirects to the wizard while this is true.

    Keyed on whether setup has ever completed, not on whether an administrator
    currently exists — so an install that has lost its admins is never sent to a
    wizard that will (correctly) refuse it.
    """
    return SetupStatusOut(needs_setup=not await setup_is_complete(db))


@router.post("", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def complete_setup(
    body: SetupRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    # Deliberately *not* `instance_needs_setup`. "No administrator right now" is
    # a recoverable operator problem; "never provisioned" is the only state in
    # which an unauthenticated caller may mint an owner. Conflating them let a
    # configured install be re-claimed by anyone once its admin count hit zero.
    if await setup_is_complete(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This instance is already set up.",
        )

    if await display_name_taken(db, body.admin.display_name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That display name is already taken",
        )
    if body.admin.email is not None and await email_taken(db, body.admin.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    admin_role = await db.scalar(
        select(Role).where(Role.name == ADMINISTRATOR_ROLE_NAME)
    )
    if admin_role is None:
        # System roles are seeded on startup / by the migration; their absence is
        # an install fault, not a client error.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Administrator role missing — run migrations",
        )

    settings = await get_or_create_settings(db)

    # Claim first-run atomically, before writing anything. The guard above is a
    # plain SELECT, so two requests arriving together would both read "not set
    # up" and both provision an owner — on a fresh public deployment that is a
    # race an attacker polling /api/setup/status can enter deliberately. A
    # conditional UPDATE makes the database the arbiter: the loser blocks on the
    # row, re-evaluates the predicate against the winner's committed value, and
    # matches nothing. Everything below shares this transaction, so a later
    # failure rolls the claim back and the wizard stays open.
    claimed = await db.execute(
        update(SiteSettings)
        .where(
            SiteSettings.id == SITE_SETTINGS_ID,
            SiteSettings.setup_completed_at.is_(None),
        )
        .values(setup_completed_at=utcnow())
    )
    if claimed.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This instance is already set up.",
        )

    admin = User(
        email=body.admin.email,
        password_hash=hash_password(body.admin.password),
        display_name=body.admin.display_name,
    )
    db.add(admin)
    await db.flush()
    db.add(RoleAssignment(user_id=admin.id, competition_id=None, role_id=admin_role.id))

    await db.refresh(settings)
    settings.platform_name = body.platform_name
    settings.default_palette = body.default_palette
    settings.accent = body.accent
    settings.registration_open = body.registration_open
    settings.update_checks_enabled = body.update_checks_enabled
    await db.commit()

    await event_bus.emit("user.created", {"user_id": admin.id, "email": admin.email})
    await event_bus.emit(
        "site.settings_updated",
        {
            "user_id": admin.id,
            "platform_name": settings.platform_name,
            "default_palette": settings.default_palette,
            "accent": settings.accent,
        },
    )

    access_token = await _issue_session(db, admin, response)
    return TokenResponse(access_token=access_token, user=UserOut.model_validate(admin))
