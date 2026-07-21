"""Audit Log module (§3.3, §11.3 required-core).

Owns the admin read/query surface over the audit log — the GitLab-style event
inspector. The event-bus *consumer* that persists every event
(``utils/audit_log.py``) is kernel infrastructure wired in ``main`` (it must be
listening from the first boot, before any module loads); this module simply
mounts the query router admins use to inspect that stream, so the feature shows
up through the same module registration path as everything else (§11.1).
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.audit_log import router as audit_log_router

    app.include_router(audit_log_router)
