"""Roles Admin module (§7.4, §11.3 required-core).

Mounts the custom-role editor + assignment routes. RBAC enforcement itself is
kernel (auth/deps.py); this module only adds the management surface, the same
way the audit-log module adds a query router over the kernel event consumer.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.roles import router as roles_router

    app.include_router(roles_router)
