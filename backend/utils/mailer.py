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


async def send_email(to: list[str], subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True if handed to the SMTP server."""
    if not settings.smtp_host:
        logger.info(
            "SMTP not configured (smtp_host unset); dropping email %r to %s",
            subject,
            to,
        )
        return False

    import aiosmtplib  # imported lazily so an unconfigured install never needs it

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        start_tls=settings.smtp_starttls,
    )
    return True
