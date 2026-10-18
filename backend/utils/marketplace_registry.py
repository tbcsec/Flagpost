"""Marketplace registry client (#389, ADR-0040) — on-demand code resolution + fetch.

Speaks the registry protocol (docs/spec/resolve-response.schema.json):
``GET {registry_url}/resolve/{code}`` returns the confirmation payload the instance
renders and then verifies. Used **only** when an operator resolves or installs —
never in the background — and it sends no instance data.

``registry_url`` is a trusted operator setting, the same class as the AI
``base_url`` / SMTP host / OIDC issuer (ADR-0023 §3): it may legitimately point at
a private mirror on a loopback/private address (air-gap), so it is deliberately
**not** run through the ``utils.webhook_security`` SSRF blocklist. The artifact URL
the registry returns is trusted transitively, for the same reason — the operator
chose to trust this registry by configuring it.

The client is injectable-transport (the AI-client pattern), so it is fully
exercisable against ``httpx.MockTransport`` with no live registry.

Trusting the registry's *content* is not trusting its *size or pace*: both calls
read through ``utils.http_bounded`` (a byte cap that holds against compressed
bodies too) under an overall deadline (GHSA-r7rp-46pp-x55q), and the resolve
payload is shape-checked before anything uses it, so a hostile or compromised
registry or artifact host can refuse an install but can't exhaust worker memory,
hold the request open indefinitely, or turn a malformed answer into a 500.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import httpx

from utils import http_bounded

# httpx's timeout is per operation (connect, each read), not per request: it
# never fires while bytes keep arriving, however slowly. The overall deadlines
# below are what bound a call in time.
_TIMEOUT_S = 15
# A resolve payload is a few KiB of JSON (docs/spec/resolve-response.schema.json);
# 256 KiB is generous and still bounds what a hostile response can make us hold.
_MAX_RESOLVE_BYTES = 256 * 1024
# A connect plus one read window for a payload that small: 2 x the per-read timeout.
_RESOLVE_DEADLINE_S = 2 * _TIMEOUT_S
# Long enough for the largest artifact the caller accepts (200 MiB) at roughly
# 1 MiB/s, rounded up; a body still flowing past this is refused, not awaited.
_ARTIFACT_DEADLINE_S = 300.0


class RegistryError(Exception):
    """The registry could not be reached, or returned an unusable response. The
    route maps it to a 400/404 with the message."""


async def _get_capped(
    url: str, *, max_bytes: int, transport: httpx.AsyncBaseTransport | None
) -> tuple[int, bytes]:
    """GET ``url`` and return ``(status, body)``, the body read through
    ``http_bounded`` so it is never held past ``max_bytes`` (a non-2xx status
    returns it unread). Raises ``http_bounded.BodyTooLarge`` over the cap;
    transport and decoding failures propagate as ``httpx.HTTPError``. The caller
    owns the overall deadline."""
    async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=transport) as http:
        resp, body = await http_bounded.fetch(http, "GET", url, max_bytes=max_bytes)
    return resp.status_code, body


@dataclass(frozen=True)
class ResolvedArtifact:
    id: str
    name: str
    version: str
    kind: str  # "pack" | "module"
    pack_type: str | None
    trust_tier: str | None
    publisher: dict
    artifact_url: str
    digest: str
    signature: dict | None  # {algorithm, key_id, value}
    requires_flagpost: dict
    capabilities: list
    raw: dict  # the full resolve payload (for the confirmation screen)


_SCALARS = (str, int, float, bool, type(None))


def _malformed(what: str) -> RegistryError:
    return RegistryError(f"malformed resolve response: {what}")


def _string(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise _malformed(f"{field} is not a string")
    return value


def _flat_object(value: object, field: str) -> dict:
    """The spec's publisher / signature / requires_flagpost: an object of
    scalars. Anything nested is refused here, because it would otherwise reach
    the confirmation response, whose serializer refuses deep nesting with a 500."""
    if not isinstance(value, dict) or not all(isinstance(v, _SCALARS) for v in value.values()):
        raise _malformed(f"{field} is not a flat object")
    return value


def _artifact_url(value: object) -> str:
    """An absolute http(s) URL. Checked as httpx will parse it, so a malformed
    one is a clean refusal here rather than an ``httpx.InvalidURL`` at fetch."""
    url = _string(value, "artifact.url")
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise _malformed("artifact.url is not a valid URL") from exc
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise _malformed("artifact.url is not an absolute http(s) URL")
    return url


def _parse(data: object) -> ResolvedArtifact:
    if not isinstance(data, dict):
        raise RegistryError("registry returned a non-object resolve response")
    try:
        resolved = data["resolved"]
        artifact = data["artifact"]
        if not isinstance(resolved, dict) or not isinstance(artifact, dict):
            raise _malformed("resolved and artifact must be objects")
        signature = data.get("signature")
        capabilities = data.get("capabilities") or []
        if not isinstance(capabilities, list) or not all(
            isinstance(c, str) for c in capabilities
        ):
            raise _malformed("capabilities is not a list of strings")
        return ResolvedArtifact(
            id=_string(resolved["id"], "resolved.id"),
            name=_string(resolved["name"], "resolved.name"),
            version=_string(resolved["version"], "resolved.version"),
            kind=_string(resolved["kind"], "resolved.kind"),
            pack_type=_string(resolved.get("pack_type"), "resolved.pack_type", optional=True),
            trust_tier=_string(resolved.get("trust_tier"), "resolved.trust_tier", optional=True),
            publisher=_flat_object(data.get("publisher") or {}, "publisher"),
            artifact_url=_artifact_url(artifact["url"]),
            digest=_string(artifact["digest"], "artifact.digest"),
            signature=None if signature is None else _flat_object(signature, "signature"),
            requires_flagpost=_flat_object(
                data.get("requires_flagpost") or {}, "requires_flagpost"
            ),
            capabilities=capabilities,
            raw=data,
        )
    except KeyError as exc:
        raise _malformed(f"missing {exc}") from exc


async def resolve(
    registry_url: str, code: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> ResolvedArtifact:
    """Resolve an import ``code`` against ``registry_url``. ``code`` must already be
    validated safe (the route enforces the pattern) so it can't traverse the path."""
    url = f"{registry_url.rstrip('/')}/resolve/{code}"
    try:
        async with asyncio.timeout(_RESOLVE_DEADLINE_S):
            status_code, body = await _get_capped(
                url, max_bytes=_MAX_RESOLVE_BYTES, transport=transport
            )
    except TimeoutError as exc:
        raise RegistryError(
            f"the registry did not answer within {_RESOLVE_DEADLINE_S:.0f}s"
        ) from exc
    except http_bounded.BodyTooLarge as exc:
        raise RegistryError("the registry's resolve response is too large") from exc
    except httpx.HTTPError as exc:
        raise RegistryError(f"could not reach the registry: {exc}") from exc
    if status_code == 404:
        raise RegistryError("no artifact was found for that code")
    if status_code >= 400:
        raise RegistryError(f"the registry returned {status_code}")
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise RegistryError("the registry returned a non-JSON response") from exc
    except RecursionError as exc:  # deeply nested arrays/objects, within the cap
        raise RegistryError("the registry's resolve response is nested too deeply") from exc
    return _parse(data)


async def fetch_artifact(
    url: str,
    *,
    max_bytes: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    """Download the artifact at ``url`` (registry-provided, operator-trusted).
    Refuses a body over ``max_bytes`` without buffering past it, and a download
    still running at the overall deadline."""
    try:
        async with asyncio.timeout(_ARTIFACT_DEADLINE_S):
            status_code, content = await _get_capped(
                url, max_bytes=max_bytes, transport=transport
            )
    except TimeoutError as exc:
        raise RegistryError(
            f"the artifact download did not finish within {_ARTIFACT_DEADLINE_S:.0f}s"
        ) from exc
    except http_bounded.BodyTooLarge as exc:
        raise RegistryError("the artifact is too large") from exc
    except httpx.HTTPError as exc:
        raise RegistryError(f"could not fetch the artifact: {exc}") from exc
    if status_code >= 400:
        raise RegistryError(f"the artifact fetch returned {status_code}")
    return content
