"""RBAC resolution: per-competition scoping and global-role behaviour (§7.5)."""

from sqlalchemy import select

from auth.deps import user_has_permission
from auth.security import hash_password
from db import SessionLocal
from models.competition import Competition
from models.role import Role, RoleAssignment
from models.user import User


async def _make_user(session, email="judge@example.com") -> str:
    user = User(email=email, password_hash=hash_password("x" * 8), display_name=email.split("@")[0])
    session.add(user)
    await session.flush()
    return user.id


async def _make_competition(session, name: str) -> str:
    competition = Competition(name=name)
    session.add(competition)
    await session.flush()
    return competition.id


async def _role_id(session, name: str) -> str:
    return (await session.scalar(select(Role).where(Role.name == name))).id


async def test_competition_scoped_role_is_isolated_to_its_competition():
    async with SessionLocal() as session:
        user_id = await _make_user(session)
        judge_id = await _role_id(session, "Judge")
        comp_a = await _make_competition(session, "Comp A")
        comp_b = await _make_competition(session, "Comp B")
        # Judge on competition A only.
        session.add(
            RoleAssignment(
                user_id=user_id, competition_id=comp_a, role_id=judge_id
            )
        )
        await session.commit()

        # Holds a Judge permission on A...
        assert await user_has_permission(
            session, user_id, "challenge_edit", comp_a
        )
        # ...but not on competition B (§7.5 — a judge somewhere isn't a judge
        # everywhere).
        assert not await user_has_permission(
            session, user_id, "challenge_edit", comp_b
        )
        # ...and never a global permission it wasn't granted.
        assert not await user_has_permission(
            session, user_id, "manage_users", comp_a
        )


async def test_global_admin_satisfies_competition_scoped_checks_everywhere():
    async with SessionLocal() as session:
        # Distinct from the seeded admin@example.com (fixture) to avoid a clash.
        user_id = await _make_user(session, "second-admin@example.com")
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


async def test_unscoped_assignment_of_a_competition_role_grants_nothing():
    """A competition-scoped role pinned to no competition is malformed.

    ``routers.roles.assign_role`` refuses to create this shape, but OIDC JIT
    provisioning wrote it directly for every SSO user, and the NULL was read as
    "site-wide" — handing Participant permissions on every competition to
    anyone who could log in through the IdP. Resolution now requires the *role*
    to be global-scoped before an unscoped assignment counts, so such a row
    grants nothing rather than everything.
    """
    async with SessionLocal() as session:
        user_id = await _make_user(session, "sso@example.com")
        participant_id = await _role_id(session, "Participant")
        comp = await _make_competition(session, "Someone else's event")
        session.add(
            RoleAssignment(
                user_id=user_id, competition_id=None, role_id=participant_id
            )
        )
        await session.commit()

        assert not await user_has_permission(
            session, user_id, "challenge_view", comp
        )
        assert not await user_has_permission(
            session, user_id, "challenge_view", "any-other-competition"
        )
        assert not await user_has_permission(
            session, user_id, "challenge_view", None
        )
