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
stream with a byte cap and run under an overall deadline (GHSA-r7rp-46pp-x55q),
so a hostile or compromised registry or artifact host can refuse an install but
can't exhaust worker memory or hold the request open indefinitely.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import httpx

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


class _BodyTooLarge(Exception):
    """The response declared, or streamed, more than the caller's cap."""


async def _get_capped(
    url: str, *, max_bytes: int, transport: httpx.AsyncBaseTransport | None
) -> tuple[int, bytes]:
    """GET ``url`` and return ``(status, body)``, streaming the body so it is
    never held past ``max_bytes``. An error status returns without reading the
    body. Raises :class:`_BodyTooLarge` on a ``Content-Length`` over the cap (up
    front) or once the decoded bytes cross it; transport failures propagate as
    ``httpx.HTTPError``. The caller owns the overall deadline."""
    async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=transport) as http:
        async with http.stream("GET", url) as resp:
            if resp.status_code >= 400:
                return resp.status_code, b""
            try:
                declared = int(resp.headers.get("content-length", ""))
            except ValueError:  # absent, or not a sane number: count instead
                declared = None
            if declared is not None and declared > max_bytes:
                raise _BodyTooLarge
            # Counted on decoded bytes, so a compressed body is held to the
            # cap by what it expands to, not by what it declared.
            size = 0
            chunks: list[bytes] = []
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise _BodyTooLarge
                chunks.append(chunk)
            return resp.status_code, b"".join(chunks)


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


def _parse(data: object) -> ResolvedArtifact:
    if not isinstance(data, dict):
        raise RegistryError("registry returned a non-object resolve response")
    try:
        resolved = data["resolved"]
        artifact = data["artifact"]
        return ResolvedArtifact(
            id=resolved["id"],
            name=resolved["name"],
            version=resolved["version"],
            kind=resolved["kind"],
            pack_type=resolved.get("pack_type"),
            trust_tier=resolved.get("trust_tier"),
            publisher=data.get("publisher") or {},
            artifact_url=artifact["url"],
            digest=artifact["digest"],
            signature=data.get("signature"),
            requires_flagpost=data.get("requires_flagpost") or {},
            capabilities=data.get("capabilities") or [],
            raw=data,
        )
    except (KeyError, TypeError) as exc:
        raise RegistryError(f"malformed resolve response: missing {exc}") from exc


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
    except _BodyTooLarge as exc:
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
    except _BodyTooLarge as exc:
        raise RegistryError("the artifact is too large") from exc
    except httpx.HTTPError as exc:
        raise RegistryError(f"could not fetch the artifact: {exc}") from exc
    if status_code >= 400:
        raise RegistryError(f"the artifact fetch returned {status_code}")
    return content
