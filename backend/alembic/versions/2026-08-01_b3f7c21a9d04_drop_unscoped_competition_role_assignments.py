"""drop unscoped assignments of competition-scoped roles

Revision ID: b3f7c21a9d04
Revises: 9eafb0c1d2e3
Create Date: 2026-08-01

OIDC JIT provisioning wrote ``RoleAssignment(role=Participant,
competition_id=NULL)`` for every user it created. An assignment with no
competition is the *site-wide* grant (``deps.user_has_permission``), so those
rows gave every SSO user Participant permissions on every competition on the
install — and, via ``membership.has_global_role``, visibility of every private
competition together with its invite code.

The code no longer creates them and no longer honours them, but deployed
installs with SSO enabled already have the rows. Delete them: they were never a
legitimate shape (``routers.roles.assign_role`` refuses to create one), so
there is nothing to preserve. Affected users are unaffected in practice —
Participant is granted per-competition by ``membership.ensure_participant_role``
when they join, which is how locally-registered users have always worked.

Scoped assignments and global assignments of genuinely global roles
(Administrator) are untouched.
"""

from __future__ import annotations

from alembic import op

revision = "b3f7c21a9d04"
down_revision = "9eafb0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Subquery rather than a join: SQLite's UPDATE/DELETE ... FROM support
    # differs from Postgres, and `IN (subquery)` is portable across both.
    op.execute(
        """
        DELETE FROM role_assignments
        WHERE competition_id IS NULL
          AND role_id IN (SELECT id FROM roles WHERE scope = 'competition')
        """
    )


def downgrade() -> None:
    # Deliberately empty. The deleted rows were malformed — recreating them
    # would reintroduce the vulnerability, and we cannot tell which users had
    # one without keeping a copy of the very data that was the problem.
    pass
