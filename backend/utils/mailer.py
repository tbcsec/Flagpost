"""Async SMTP delivery (ARCHITECTURE.md §5.3 ``send_email``).

The one place outbound email leaves the platform. Deliberately minimal: email
exists **only** as an automation action target for now (§4.4 — baseline
notifications are in-app; email/push are "just another notify action target",
not a second notification system). Unconfigured SMTP (no ``smtp_host``) makes
sending a logged no-op rather than an error, so an install without a mail
server can still enable rules whose other actions matter.

``send_email`` is swapped out in tests (and could be for other transports);
callers import the module and call through it so monkeypatching works.
"""

from __future__ import annotations

import logging
from email.message import EmailMessage

from config import settings

logger = logging.getLogger("mailer")


async def _effective_smtp():
    """Resolve the SMTP config: the DB SiteSettings row wins when its host is set
    (Admin → Site settings), otherwise fall back to the env config. Returns a
    dict of connection kwargs, or None if no host is configured anywhere."""
    from db import SessionLocal
    from models.site_settings import SITE_SETTINGS_ID, SiteSettings

    row = None
    try:
        async with SessionLocal() as db:
            row = await db.get(SiteSettings, SITE_SETTINGS_ID)
    except Exception:  # noqa: BLE001 — never let a settings-read failure block delivery attempts
        row = None

    if row is not None and row.smtp_host:
        return {
            "host": row.smtp_host,
            "port": row.smtp_port,
            "username": row.smtp_username,
            "password": row.smtp_password,
            "from": row.smtp_from,
            "starttls": row.smtp_starttls,
        }
    if settings.smtp_host:
        return {
            "host": settings.smtp_host,
            "port": settings.smtp_port,
            "username": settings.smtp_username,
            "password": settings.smtp_password,
            "from": settings.smtp_from,
            "starttls": settings.smtp_starttls,
        }
    return None


async def send_email(to: list[str], subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True if handed to the SMTP server."""
    smtp = await _effective_smtp()
    if smtp is None:
        logger.info(
            "SMTP not configured (no host in DB or env); dropping email %r to %s",
            subject,
            to,
        )
        return False

    import aiosmtplib  # imported lazily so an unconfigured install never needs it

    message = EmailMessage()
    message["From"] = smtp["from"]
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=smtp["host"],
        port=smtp["port"],
        username=smtp["username"],
        password=smtp["password"],
        start_tls=smtp["starttls"],
    )
    return True
