"""Users Admin module (§7, §11.3 required-core).

Mounts the admin user-management routes (directory + create/edit/ban/delete)
and personal API tokens (issue #75, mint/list/revoke). Auth/RBAC enforcement
itself is kernel (auth/deps.py); this module only adds the management
surface, the same way the roles + audit-log modules add their routers over
kernel machinery.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.api_tokens import router as api_tokens_router
    from routers.users import router as users_router

    app.include_router(users_router)
    app.include_router(api_tokens_router)
