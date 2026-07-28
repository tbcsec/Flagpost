"""Public self-serve registration policy: the email-domain allowlist (#56).

Kept separate from ``auth/identity.py`` (which is about matching an *existing*
user) — this is a pre-account admission check, and only ``POST /register``
calls it. Admin-created accounts (``routers/users.py``) and a later email edit
are deliberately unaffected.
"""

from __future__ import annotations


def domain_allowed(email: str, allowed_domains: list[str]) -> bool:
    """Whether ``email``'s domain matches one of ``allowed_domains``, or a
    subdomain of one (an entry for ``example.com`` also allows
    ``mail.example.com``)."""
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].strip().lower()
    return any(
        domain == allowed or domain.endswith(f".{allowed}")
        for allowed in allowed_domains
    )
