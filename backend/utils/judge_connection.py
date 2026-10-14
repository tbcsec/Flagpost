"""Code judge — the endpoint, and checking it (#447, ADR-0042).

Two jobs:

* ``effective_endpoint`` resolves where the judge talks to Docker: the
  deployment's ``JUDGE_ENDPOINT_URL`` (set by the ``docker-compose.judge.yml``
  overlay) when present — then the endpoint is *managed* and the admin UI shows
  it as detected — otherwise the admin-saved value.

* ``check_endpoint`` is the setup flow's "Check connection": the two legs that
  don't need the executor — the proxy is reachable, and it refuses the
  dangerous verbs. The second is the security-critical one: a raw Docker socket
  (or a proxy with its allowlist off) answers them, which would hand the judge —
  and so anyone who controls a submission's runtime — the host's Docker. The
  executor (#448) extends this with a leg that actually runs a hardened probe
  container.

Only ever pointed at the **saved/effective** endpoint, never a URL supplied in
the request — the instancing "test the saved config" posture — so the check
can't be used to make the server probe arbitrary addresses.
"""

from __future__ import annotations

import httpx

from config import settings as app_settings
from models.judge import JudgeSettings
from utils.provisioners import CheckResult

_TIMEOUT = 10.0

# Verbs the proxy must refuse with 403 (the instancing posture probes, kept in
# step with utils/provisioner_docker.validate). The exec probe targets
# /exec/<id>/start rather than /containers/<id>/exec, which the proxy gates
# under CONTAINERS and so forwards regardless.
_MUST_BE_DENIED = (
    ("exec", "POST", "/exec/flagpost-judge-probe/start"),
    ("volumes", "GET", "/volumes"),
    ("build", "POST", "/build"),
)


def effective_endpoint(settings: JudgeSettings) -> tuple[str | None, bool]:
    """``(endpoint, managed)``. Managed means it comes from the deployment's
    ``JUDGE_ENDPOINT_URL`` and the admin can't change it."""
    managed = (app_settings.judge_endpoint_url or "").strip()
    if managed:
        return managed, True
    return settings.endpoint_url, False


async def check_endpoint(
    url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> list[CheckResult]:
    legs: list[CheckResult] = []
    async with httpx.AsyncClient(
        base_url=url.rstrip("/"), timeout=_TIMEOUT, transport=transport
    ) as http:
        try:
            ping = await http.get("/_ping")
        except httpx.HTTPError as exc:
            legs.append(
                CheckResult("endpoint_reachable", False, f"couldn't reach {url}: {exc}")
            )
            return legs
        if ping.status_code != 200:
            legs.append(
                CheckResult(
                    "endpoint_reachable",
                    False,
                    f"GET /_ping returned {ping.status_code}",
                )
            )
            return legs
        legs.append(
            CheckResult(
                "endpoint_reachable",
                True,
                f"reachable, Docker API {ping.headers.get('Api-Version', 'unknown')}",
            )
        )

        ok = True
        notes: list[str] = []
        for label, method, path in _MUST_BE_DENIED:
            try:
                resp = await http.request(method, path)
            except httpx.HTTPError as exc:
                ok = False
                notes.append(f"{label}: probe failed ({exc})")
                continue
            if resp.status_code == 403:
                notes.append(f"{label}: blocked")
            else:
                ok = False
                notes.append(
                    f"{label}: NOT blocked ({method} {path} returned "
                    f"{resp.status_code}) — this isn't a restricted socket proxy"
                )
        legs.append(CheckResult("proxy_restricted", ok, "; ".join(notes)))
    return legs
