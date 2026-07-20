"""SQLAlchemy models.

Importing this package imports every model module so ``Base.metadata`` is
fully populated — Alembic autogenerate and metadata-create both rely on that.
Add new model modules to the imports below as domains are built.
"""

from models.announcement import Announcement
from models.attachment import Attachment
from models.audit_log import AuditLogEntry
from models.challenge import Category, Challenge
from models.competition import Competition
from models.hint import Hint, HintReveal
from models.role import Role, RoleAssignment
from models.submission import Submission
from models.team import Team, TeamMembership
from models.user import RefreshSession, User

__all__ = [
    "Announcement",
    "Attachment",
    "AuditLogEntry",
    "Category",
    "Challenge",
    "Competition",
    "Hint",
    "HintReveal",
    "Role",
    "RoleAssignment",
    "Submission",
    "RefreshSession",
    "Team",
    "TeamMembership",
    "User",
]
