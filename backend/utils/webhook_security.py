"""Webhook action hardening (ARCHITECTURE.md §5.4, ADR-0013).

The webhook action is uniquely exposed: its **target and template are
admin-authored**, but the **values substituted into them** — team names,
challenge titles, ticket subjects — are competitor-controlled by design (§5.4:
"team and challenge names are adversarial input"). That splits into four
independent hardenings, all applied by ``_execute_webhook``:

1. :func:`validate_webhook_url` — SSRF guard run **before every call** (not
   just at rule save): the host is resolved and *every* resolved IP checked
   against the blocked ranges, so a name that resolves partly to a public and
   partly to an internal address (DNS-rebinding) is refused. An unresolvable
   host is refused too (can't prove it safe). Redirects are not followed by the
   caller, so a 302 to an internal target can't bounce past this.
2. :func:`sanitize_headers` — strips caller-uncontrollable headers from the
   admin header set so a rule can't forge origin or smuggle credentials.
3. :func:`escape_for_content_type` — escapes a substituted value for the body's
   declared type, so a value with quotes can't break out of its field and
   inject sibling JSON keys.
4. :func:`defang_chat_tokens` — neutralises Slack/Discord/Teams broadcast and
   mention tokens (and markdown links) in substituted values, so a competitor
   can't rename their team to ``@everyone`` and mass-ping through an
   organiser's rule.

The resolve-then-connect TOCTOU is now closed by :func:`resolve_pinned_target`,
which pins the connection to a validated IP (ADR-0013 amendment, GHSA-r7rp), and
``_execute_webhook`` streams the response without buffering its body so a hostile
target can't exhaust memory. Residual risk (see ADR-0013): destination-rate
limiting is still the open §15 question, deliberately out of this phase.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
from typing import NamedTuple
from urllib.parse import quote, urlsplit, urlunsplit

logger = logging.getLogger("automation")

_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Case-insensitive header names an admin rule may never set: identity/origin
# forgery and transport headers the client owns (§5.4). ``x-forwarded-*`` is
# matched by prefix; ``content-type``/``content-length`` are set by the caller
# from the action's own config, never the admin header map.
_FORBIDDEN_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "host",
        "content-length",
        "content-type",
        "forwarded",
        "x-real-ip",
    }
)
_FORBIDDEN_HEADER_PREFIXES = ("x-forwarded-",)

_ZWSP = "​"  # zero-width space: breaks a token while staying readable


class WebhookSecurityError(Exception):
    """A webhook target failed a §5.4 safety check; the call is refused."""


# --- 1. SSRF URL validation --------------------------------------------------


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Any non-globally-routable address is blocked: loopback, private,
    link-local (incl. the 169.254.169.254 cloud metadata endpoint), reserved,
    multicast, shared address space, and the unspecified address."""
    # Unwrap IPv4-mapped IPv6 (``::ffff:169.254.169.254``) so it can't smuggle
    # a blocked v4 target past the v6 checks.
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # `is_global` is the property this docstring actually describes; the
    # predicates below only enumerate most of it. The gap that mattered was
    # 100.64.0.0/10 (RFC 6598 shared address space), which is `is_global == False`
    # but satisfies none of them — so it was reachable. That range is the default
    # for Tailscale, several Kubernetes CNI layouts and ISP CGNAT, and on Alibaba
    # Cloud it carries the instance metadata service at 100.100.100.200.
    #
    # The enumeration is kept alongside rather than replaced: `is_global` treats
    # NAT64 (64:ff9b::/96) as global, and `is_reserved` catches it.
    if not ip.is_global:
        return True
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _resolve_host(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    # sockaddr[0] is the numeric address for both AF_INET and AF_INET6.
    return [sockaddr[0] for *_, sockaddr in infos]


class PinnedTarget(NamedTuple):
    """A validated webhook target whose connection is pinned to a checked IP.

    ``url`` points at the literal IP (so the HTTP client connects there and can't
    re-resolve to a different address); ``host_header`` and ``sni_hostname``
    carry the original hostname so routing and TLS still work. Pass
    ``extensions={"sni_hostname": t.sni_hostname}`` on the request when set.
    """

    url: str
    host_header: str
    sni_hostname: str | None

    @property
    def extensions(self) -> dict[str, str]:
        return {"sni_hostname": self.sni_hostname} if self.sni_hostname else {}


async def _resolve_validated(url: str) -> tuple[str, int, str, list[str]]:
    """Parse + SSRF-check ``url``; return (scheme, port, host, validated IPs).

    Resolves the host once and checks *every* resolved IP against the blocked
    ranges, so a name that resolves partly to a public and partly to an internal
    address (DNS rebinding) is refused. An unresolvable host is refused too
    (can't prove it safe). Raises :class:`WebhookSecurityError` on any failure.
    """
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise WebhookSecurityError(f"scheme {parts.scheme!r} not allowed")
    host = parts.hostname
    if not host:
        raise WebhookSecurityError("missing host")
    port = parts.port or (443 if parts.scheme == "https" else 80)

    try:
        addresses = await _resolve_host(host, port)
    except socket.gaierror as exc:
        # Can't resolve → can't prove safe → refuse.
        raise WebhookSecurityError(f"host {host!r} does not resolve") from exc

    if not addresses:
        raise WebhookSecurityError(f"host {host!r} does not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if _ip_is_blocked(ip):
            raise WebhookSecurityError(
                f"host {host!r} resolves to blocked address {address}"
            )
    return parts.scheme, port, host, addresses


async def validate_webhook_url(url: str) -> None:
    """Raise :class:`WebhookSecurityError` unless ``url`` is a safe http(s)
    target (§5.4). Used at rule-save time; the fire path uses
    :func:`resolve_pinned_target` so the checked address is the connected one."""
    await _resolve_validated(url)


async def resolve_pinned_target(url: str) -> PinnedTarget:
    """SSRF-check ``url`` and return a :class:`PinnedTarget` that pins the
    connection to a **validated** IP (ADR-0013 amendment).

    This closes the resolve-then-connect TOCTOU: the SSRF check resolved the
    host, and the request must connect to one of *those* addresses — not to
    whatever a rebinding DNS server answers on a second, independent lookup at
    connect time. We rewrite the URL host to the first validated IP and carry the
    original hostname in the Host header and (for https) the TLS SNI, so the
    origin still routes correctly and the certificate is still verified against
    the real hostname.
    """
    scheme, port, host, addresses = await _resolve_validated(url)
    parts = urlsplit(url)
    ip = addresses[0]
    ip_host = f"[{ip}]" if ":" in ip else ip  # bracket IPv6 in the URL authority
    pinned_url = urlunsplit(
        (scheme, f"{ip_host}:{port}", parts.path or "/", parts.query, "")
    )
    default_port = 443 if scheme == "https" else 80
    # Mirror the Host header the client would have sent for the original URL:
    # bare host on the default port, host:port otherwise.
    host_header = host if port == default_port else f"{host}:{port}"
    return PinnedTarget(
        url=pinned_url,
        host_header=host_header,
        sni_hostname=host if scheme == "https" else None,
    )


# --- 2. Header sanitisation --------------------------------------------------


def sanitize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Drop caller-uncontrollable headers from an admin-defined set (§5.4)."""
    if not headers:
        return {}
    clean: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.strip().lower()
        if lowered in _FORBIDDEN_HEADERS:
            continue
        if any(lowered.startswith(p) for p in _FORBIDDEN_HEADER_PREFIXES):
            continue
        clean[key] = value
    return clean


# --- 3 + 4. Value escaping and chat-token defanging --------------------------


def defang_chat_tokens(value: str) -> str:
    """Neutralise broadcast/mention tokens and markdown links (§5.4).

    Inserts a zero-width space to break the token for the renderer while
    keeping it human-readable — covers Discord plain-text ``@everyone``/
    ``@here``/``@channel`` (which ping on Discord), Slack's angle-bracket
    control/mention sequences (``<!channel>``, ``<@U…>``, ``<#C…>``,
    ``<!subteam…>``), and markdown link/image syntax (``](``).
    """
    value = re.sub(r"@(everyone|here|channel)", rf"@{_ZWSP}\1", value)
    value = re.sub(r"<([!@#&])", rf"<{_ZWSP}\1", value)
    return value.replace("](", f"]{_ZWSP}(")


def escape_for_content_type(value: str, content_type: str) -> str:
    """Defang then structurally escape a substituted value for ``content_type``.

    JSON string escaping (quotes/backslashes/control chars) for a JSON body,
    percent-encoding for a form body, defang-only for plain text — so an
    adversarial value can't break out of the field it's substituted into.
    """
    value = defang_chat_tokens(value)
    base = content_type.split(";", 1)[0].strip().lower()
    if base == "application/json":
        # json.dumps yields a fully-escaped, quote-wrapped string; strip the
        # surrounding quotes to get the inner fragment for interpolation.
        return json.dumps(value)[1:-1]
    if base == "application/x-www-form-urlencoded":
        return quote(value, safe="")
    return value  # text/plain and anything else: defang is the only guard


_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def render_webhook_body(
    template: str, payload: dict, content_type: str
) -> str:
    """Fill ``{field}`` placeholders from ``payload`` with each value escaped
    for ``content_type`` (§5.4). Unknown fields are left verbatim (debuggable);
    the template itself is admin-authored and trusted, only the values aren't."""

    def _sub(match: re.Match) -> str:
        field = match.group(1)
        if field not in payload:
            return match.group(0)
        return escape_for_content_type(str(payload[field]), content_type)

    return _PLACEHOLDER.sub(_sub, template)
