"""Daily update check + anonymous adoption count (issue #111).

One outbound request a day::

    GET {update_check_url}?version={app_version}  ->  {"latest": "1.2.0"}

It does double duty: the response tells administrators they're behind, and the
request itself — counted at the endpoint, never logged — is the project's only
signal for how many deployments are actually running.

**It sends the version and nothing else.** No install identifier, no hostname,
no competition or user counts. That isn't a limitation worked around: counting
*unique* installs would need an identifier, which is attributable to a
deployment; counting *daily check-ins* needs none. Checking exactly once per 24h
and persisting that to the database — so a restart doesn't re-trigger it — makes
``requests per day ≈ deployments per day`` without storing anything identifying.

Three things it deliberately does not do:

- **Never renders anything from the response.** Only a version string is read,
  and only ever compared. A URL, changelog or markup taken from a remote
  response and shown to an administrator would be an injection vector into the
  most privileged browser session on the platform.
- **Never fails loudly.** A missing endpoint, DNS failure or air-gapped network
  is normal, not an error; it records a status and moves on.
- **Never runs on the demo instance.** It resets hourly, so it would report
  ~24 phantom deployments a day and quietly corrupt the metric.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta

import httpx

from auth.setup import instance_needs_setup
from config import settings
from db import ensure_aware_utc, utcnow
from models.site_settings import SITE_SETTINGS_ID, SiteSettings

logger = logging.getLogger("update_check")

CHECK_INTERVAL = timedelta(hours=24)
# A failed attempt backs off to hourly rather than retrying every scheduler
# tick, so an endpoint outage doesn't turn every install into a hammer.
RETRY_INTERVAL = timedelta(hours=1)
_HTTP_TIMEOUT = 10.0
# The answer is `{"latest": "1.2.3"}`. 64 KiB is absurdly generous and still
# bounds what a hostile response can make us allocate.
_MAX_RESPONSE_BYTES = 64 * 1024

# Versions we're willing to parse. Anything else is ignored rather than
# displayed — this is untrusted input from the network, and the only safe thing
# to do with it is compare it or drop it.
# Digits are bounded, not just shaped: `\d+` would let a hostile response hand
# `int()` a 100k-digit string, which CPython refuses above 4300 digits — an
# exception path reachable straight off the wire. Nine digits is more version
# than anyone needs.
_VERSION_RE = re.compile(
    r"^v?(\d{1,9})\.(\d{1,9})\.(\d{1,9})(?:[-+][0-9A-Za-z.\-+]{0,32})?$"
)


def parse_version(raw: str | None) -> tuple[int, int, int] | None:
    """Return ``(major, minor, patch)``, or ``None`` if it isn't a version.

    Pre-release/build suffixes are accepted but ignored for ordering: a `-rc1`
    shouldn't be advertised as an upgrade over the release it precedes, and
    ordering them properly isn't worth the complexity here.
    """
    if not raw or not isinstance(raw, str):
        return None
    match = _VERSION_RE.match(raw.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups()[:3])  # type: ignore[return-value]


def is_newer(latest: str | None, current: str | None) -> bool:
    """Whether ``latest`` is a strictly newer release than ``current``.

    Unparseable input on either side means "don't claim an update": a source
    build reports ``dev``, and telling that operator they're out of date would
    be noise rather than information.
    """
    left, right = parse_version(latest), parse_version(current)
    if left is None or right is None:
        return False
    return left > right


def update_available(site: SiteSettings) -> bool:
    """Whether a newer release exists. **Raw fact, ignoring dismissal.**

    Kept separate from :func:`notice_dismissed` on purpose. Folding the two
    together made the settings page claim "up to date" the moment an admin
    dismissed the banner — which is precisely the page they consult to find out
    whether they're current, so it must state the fact, not the notification
    state.
    """
    return is_newer(site.latest_known_version, settings.app_version)


def notice_dismissed(site: SiteSettings) -> bool:
    """Whether the admin has waved away the *current* latest version.

    Pinned to a version rather than a timer: dismissing hides the banner until
    something newer than the dismissed version ships, so one release nags at
    most once while a genuinely newer one still gets through.
    """
    if not site.dismissed_update_version:
        return False
    return not is_newer(site.latest_known_version, site.dismissed_update_version)


def _due(site: SiteSettings) -> bool:
    now = utcnow()
    last_success = ensure_aware_utc(site.last_update_check_at) if site.last_update_check_at else None
    last_attempt = ensure_aware_utc(site.last_update_attempt_at) if site.last_update_attempt_at else None
    if last_success is not None and now - last_success < CHECK_INTERVAL:
        return False
    # Back off after a failure. Checked second so a success always wins.
    if last_attempt is not None and now - last_attempt < RETRY_INTERVAL:
        return False
    return True


async def run_check(db_factory) -> None:
    """One scheduler tick's worth of work. Returns quietly when not due."""
    if settings.demo_mode:
        return  # hourly resets would inflate the count ~24x
    if not settings.update_check_url.strip():
        return  # disabled at the environment level (air-gapped installs)

    # Two short sessions rather than one held across the HTTP call: a hanging
    # endpoint would otherwise tie up a pooled connection for the full timeout.
    async with db_factory() as db:
        # Nothing goes out before the first-run wizard is done. The public
        # (unauthenticated) GET /site-settings creates the settings row with
        # checks enabled, and the setup page itself calls it — so without this
        # guard the very first check would fire before the operator had read the
        # wizard's disclosure or had any chance to decline. An unconfigured
        # instance also isn't a deployment worth counting.
        if await instance_needs_setup(db):
            return
        site = await db.get(SiteSettings, SITE_SETTINGS_ID)
        if site is None or not site.update_checks_enabled or not _due(site):
            return
        # Stamp the attempt *before* the request. If the process dies mid-call
        # the backoff still applies, so a crash loop can't become a request
        # flood against the endpoint.
        site.last_update_attempt_at = utcnow()
        await db.commit()

    status, latest = await _fetch(settings.app_version)

    async with db_factory() as db:
        site = await db.get(SiteSettings, SITE_SETTINGS_ID)
        if site is None:  # deleted mid-flight; nothing to record
            return
        site.last_update_check_status = status
        if status == "ok":
            site.last_update_check_at = utcnow()
            if latest is not None:
                site.latest_known_version = latest
        await db.commit()


async def _fetch(version: str) -> tuple[str, str | None]:
    """Return ``(status, latest_version)``. Never raises."""
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT, follow_redirects=False
        ) as client:
            # Streamed with a hard cap rather than read whole: the answer is a
            # few dozen bytes, and a compromised endpoint returning an endless
            # body would otherwise be a memory exhaustion of every deployment
            # that asks.
            async with client.stream(
                "GET",
                settings.update_check_url,
                params={"version": version},
                headers={"User-Agent": f"Flagpost/{version}"},
            ) as response:
                if response.status_code != 200:
                    logger.info(
                        "update check: endpoint returned %s", response.status_code
                    )
                    return "error", None
                body = b""
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > _MAX_RESPONSE_BYTES:
                        logger.info("update check: response exceeded the size cap")
                        return "error", None
    except Exception:  # noqa: BLE001 — offline is a normal state, not an error
        logger.info("update check: endpoint unreachable", exc_info=True)
        return "unreachable", None

    try:
        payload = json.loads(body)
    except ValueError:
        logger.info("update check: response was not JSON")
        return "error", None
    if not isinstance(payload, dict):
        return "error", None

    latest = payload.get("latest")
    # Validated, not trusted. An unparseable value is dropped rather than
    # stored, so nothing arbitrary from the network can reach an admin's screen.
    if parse_version(latest) is None:
        logger.info("update check: response carried no usable version")
        return "error", None
    return "ok", latest.strip()
