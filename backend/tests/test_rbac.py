"""RBAC resolution: per-competition scoping and global-role behaviour (§7.5)."""

from sqlalchemy import select

from auth.deps import user_has_permission
from auth.security import hash_password
from db import SessionLocal
from models.role import Role, RoleAssignment
from models.user import User


async def _make_user(session, email="judge@example.com") -> str:
    user = User(email=email, password_hash=hash_password("x" * 8), display_name="J")
    session.add(user)
    await session.flush()
    return user.id


async def _role_id(session, name: str) -> str:
    return (await session.scalar(select(Role).where(Role.name == name))).id


async def test_competition_scoped_role_is_isolated_to_its_competition():
    async with SessionLocal() as session:
        user_id = await _make_user(session)
        judge_id = await _role_id(session, "Judge")
        # Judge on competition "A" only.
        session.add(
            RoleAssignment(user_id=user_id, competition_id="A", role_id=judge_id)
        )
        await session.commit()

        # Holds a Judge permission on A...
        assert await user_has_permission(
            session, user_id, "challenge_edit", "A"
        )
        # ...but not on competition B (§7.5 — a judge somewhere isn't a judge
        # everywhere).
        assert not await user_has_permission(
            session, user_id, "challenge_edit", "B"
        )
        # ...and never a global permission it wasn't granted.
        assert not await user_has_permission(
            session, user_id, "manage_users", "A"
        )


async def test_global_admin_satisfies_competition_scoped_checks_everywhere():
    async with SessionLocal() as session:
        user_id = await _make_user(session, "admin@example.com")
        admin_id = await _role_id(session, "Administrator")
        session.add(
            RoleAssignment(
                user_id=user_id, competition_id=None, role_id=admin_id
            )
        )
        await session.commit()

        # A global Administrator assignment grants both a global permission...
        assert await user_has_permission(
            session, user_id, "manage_users", None
        )
        # ...and any competition-scoped permission, for any competition (§7.3).
        assert await user_has_permission(
            session, user_id, "challenge_edit", "any-competition"
        )


async def test_no_assignment_means_no_permission():
    async with SessionLocal() as session:
        user_id = await _make_user(session, "nobody@example.com")
        await session.commit()
        assert not await user_has_permission(
            session, user_id, "challenge_view", "A"
        )
