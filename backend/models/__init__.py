"""SQLAlchemy models.

Importing this package imports every model module so ``Base.metadata`` is
fully populated — Alembic autogenerate and metadata-create both rely on that.
Add new model modules to the imports below as domains are built.
"""

from models.audit_log import AuditLogEntry
from models.competition import Competition
from models.role import Role, RoleAssignment
from models.user import RefreshSession, User

__all__ = [
    "AuditLogEntry",
    "Competition",
    "Role",
    "RoleAssignment",
    "RefreshSession",
    "User",
]
