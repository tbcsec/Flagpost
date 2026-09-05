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
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_TIMEOUT_S = 15


class RegistryError(Exception):
    """The registry could not be reached, or returned an unusable response. The
    route maps it to a 400/404 with the message."""


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
    async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=transport) as http:
        try:
            resp = await http.get(url)
        except httpx.HTTPError as exc:
            raise RegistryError(f"could not reach the registry: {exc}") from exc
    if resp.status_code == 404:
        raise RegistryError("no artifact was found for that code")
    if resp.status_code >= 400:
        raise RegistryError(f"the registry returned {resp.status_code}")
    try:
        data = resp.json()
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
    Refuses a body over ``max_bytes``."""
    async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=transport) as http:
        try:
            resp = await http.get(url)
        except httpx.HTTPError as exc:
            raise RegistryError(f"could not fetch the artifact: {exc}") from exc
    if resp.status_code >= 400:
        raise RegistryError(f"the artifact fetch returned {resp.status_code}")
    content = resp.content
    if len(content) > max_bytes:
        raise RegistryError("the artifact is too large")
    return content
