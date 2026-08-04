"""LDAP directory bind (#101, ADR-0022 §5).

The protocol half of LDAP login: given a provider's validated ``LdapConfig``
and the credentials a user typed into the ordinary login form, find their
directory entry and prove the password by binding as them. The *identity* half
— which local account the entry becomes — stays in
``auth/external_identity.resolve_identity``, called by the login route.

The security posture is fixed here, not left to per-provider config:

- **TLS always, certificates verified.** ``ldap3``'s default ``Tls()`` does
  *not* validate the peer certificate, so ``ssl.CERT_REQUIRED`` is explicit
  here; a plaintext bind isn't expressible at all (the config validator
  refuses it). The user's directory password transits this process on every
  login — this is the whole reason.
- **The submitted identifier is escaped per RFC 4515** before it enters the
  search filter — LDAP injection is this surface's SQLi. Attribute *names*
  also appear in the filter, but those come from admin config constrained to
  a metacharacter-free pattern at write time (``schemas.auth_providers``).
- **An empty or whitespace password is refused before any network I/O.**
  RFC 4513 §5.1.2 makes a bind with a name but no password an *unauthenticated*
  bind, which succeeds on most servers — the classic LDAP auth bypass.
- The subject is the configured **stable id attribute** (``entryUUID``,
  ``objectGUID``), never the DN — a DN changes on an OU move (ADR-0022 §5).

Everything here is synchronous ``ldap3`` work under short timeouts; the login
route runs it via ``asyncio.to_thread`` so a slow or down directory can't
stall the event loop (ADR-0022 §5).

``ldap3`` is imported inside the functions, not at module scope, so an install
with no LDAP provider never loads it — same convention as ``utils.saml``.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from dataclasses import dataclass

logger = logging.getLogger("ldap")

# ADR-0022 §5: short (3–5s), so the directory leg of /login is bounded — this
# caps both the TCP connect and each LDAP operation.
TIMEOUT_SECONDS = 5


class LdapUnavailable(Exception):
    """The directory couldn't be reached, or refused the *service* bind — an
    operational failure, distinct from "these user credentials are wrong"."""


@dataclass(frozen=True)
class LdapIdentity:
    """A directory entry whose password was just proven by a successful bind."""

    subject: str
    email: str | None
    display_name: str | None


def _make_server(config):
    import ssl

    from ldap3 import Server, Tls

    return Server(
        config.server_url.strip(),
        tls=Tls(validate=ssl.CERT_REQUIRED),
        connect_timeout=TIMEOUT_SECONDS,
        get_info=None,
    )


def _connect(server, user: str, password: str, *, starttls: bool):
    """Open and bind a connection; returns it bound, or raises ``ldap3``'s
    exceptions. The seam tests substitute (with ``MOCK_SYNC`` connections) —
    call it through the module, like ``utils.mailer``'s send seam."""
    from ldap3 import AUTO_BIND_NO_TLS, AUTO_BIND_TLS_BEFORE_BIND, Connection

    return Connection(
        server,
        user=user,
        password=password,
        # For ldap:// the STARTTLS upgrade happens before any bind, so
        # credentials never travel pre-TLS; ldaps:// is TLS from the socket up.
        auto_bind=AUTO_BIND_TLS_BEFORE_BIND if starttls else AUTO_BIND_NO_TLS,
        receive_timeout=TIMEOUT_SECONDS,
        read_only=True,
        raise_exceptions=True,
    )


def search_filter(attribute: str, identifier: str) -> str:
    """The equality filter for the user lookup, with the user-controlled side
    escaped per RFC 4515. Split out so the escaping is directly testable."""
    from ldap3.utils.conv import escape_filter_chars

    return f"({attribute}={escape_filter_chars(identifier)})"


def _single(value):
    """Unwrap ldap3's single-value-or-list attribute shape; multi-valued
    attributes yield their first value (``mail`` is legally multi-valued)."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _text(value) -> str | None:
    """A clean string from one ldap3 attribute value, or ``None``.

    ldap3 usually decodes textual attributes to ``str``, but with no schema
    fetched (``get_info=None``) an attribute it can't confidently decode
    arrives as raw ``bytes`` — and ``str(b"…")`` would store the Python repr
    (``"b'ada@corp.example'"``), not the address. Decode bytes as UTF-8; a
    value that isn't text at all (or is empty) becomes ``None``.
    """
    value = _single(value)
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(value, str):
        return value.strip() or None
    return None


def normalize_subject(value) -> str | None:
    """A stable string form of the directory id attribute, or ``None``.

    ``entryUUID`` arrives as a string; AD's ``objectGUID`` arrives as 16 raw
    bytes (no schema is fetched, so ldap3 applies no formatter), rendered in
    AD's canonical mixed-endian text form so the stored subject matches what
    AD tooling displays. A *multi-valued* id attribute is refused rather than
    guessed at — a subject that could flip between values would re-mint or
    cross-link accounts.
    """
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            return None
        value = value[0]
    if isinstance(value, bytes):
        if len(value) == 16:
            return str(uuid.UUID(bytes_le=bytes(value)))
        return value.hex()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        stripped = value.strip().strip("{}")
        return stripped or None
    return None


def authenticate(
    config, bind_password: str | None, identifier: str, password: str
) -> LdapIdentity | None:
    """Prove ``password`` against the directory; the entry's identity, or None.

    ``None`` means the directory answered and refused — unknown user, wrong
    password, or an ambiguous match. :class:`LdapUnavailable` means we couldn't
    ask. The login route treats both as a failed attempt (it must not leak
    which), but logs the second as the operational problem it is.
    """
    from ldap3.core.exceptions import LDAPException

    identifier = identifier.strip()
    # Refuse the unauthenticated-bind bypass before any network I/O (RFC 4513).
    if not identifier or not password.strip():
        return None
    if not bind_password:
        # No anonymous service bind (ADR-0022 §5). The admin API refuses to
        # enable an LDAP provider without a secret, so reaching this is drift —
        # refuse loudly rather than fall back to an anonymous search.
        raise LdapUnavailable("service bind password is not set")

    starttls = config.server_url.strip().startswith("ldap://")
    server = _make_server(config)
    attributes = [config.subject_attribute]
    if config.email_attribute:
        attributes.append(config.email_attribute)
    if config.name_attribute:
        attributes.append(config.name_attribute)

    # 1. Service bind + search: find the entry (and its DN) for the identifier.
    try:
        service = _connect(server, config.bind_dn, bind_password, starttls=starttls)
    except LDAPException as exc:
        raise LdapUnavailable(f"service bind failed: {exc}") from exc
    try:
        service.search(
            search_base=config.base_dn,
            search_filter=search_filter(config.search_attribute, identifier),
            attributes=attributes,
        )
        entries = [
            r for r in (service.response or []) if r.get("type") == "searchResEntry"
        ]
    except LDAPException as exc:
        raise LdapUnavailable(f"search failed: {exc}") from exc
    finally:
        with contextlib.suppress(Exception):
            service.unbind()

    if not entries:
        return None
    if len(entries) > 1:
        # More than one entry matched the identifier: a directory/config
        # problem. Picking one would be guessing at an identity — refuse.
        logger.warning(
            "LDAP search for %r matched %d entries; refusing the login",
            identifier,
            len(entries),
        )
        return None

    entry_dn = entries[0]["dn"]
    entry_attrs = entries[0].get("attributes") or {}
    subject = normalize_subject(entry_attrs.get(config.subject_attribute))
    if subject is None:
        logger.warning(
            "LDAP entry %s has no usable %s attribute; refusing the login "
            "(the subject must be a stable directory id, ADR-0022 §5)",
            entry_dn,
            config.subject_attribute,
        )
        return None

    # 2. The user's own bind — the actual proof of the password. A fresh
    #    connection, so no state leaks over from the service credentials. The
    #    server just answered the search, so a failure here is treated as bad
    #    credentials, not an outage — the safe direction either way is refusal.
    try:
        user_conn = _connect(server, entry_dn, password, starttls=starttls)
    except LDAPException:
        return None
    with contextlib.suppress(Exception):
        user_conn.unbind()

    return LdapIdentity(
        subject=subject,
        email=_text(entry_attrs.get(config.email_attribute)) if config.email_attribute else None,
        display_name=(
            _text(entry_attrs.get(config.name_attribute)) if config.name_attribute else None
        ),
    )
