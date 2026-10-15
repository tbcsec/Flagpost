"""Code judge — site configuration (#447, ADR-0042): the settings singleton,
the language registry, the enable invariant, command validation, RBAC and the
audit trail. Nothing here executes code; the executor arrives in #448."""

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from tests.conftest import admin_token

import main  # noqa: F401, E402  (loads the judge module's routes)

BASE = "/api/admin/judge"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _participant(client, email: str = "player@example.com") -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["access_token"]


def _python(**over) -> dict:
    body = {
        "key": "python3",
        "name": "Python 3",
        "image_ref": "python:3.13-slim",
        "source_filename": "solution.py",
        "run_command": ["python3", "{source}"],
    }
    body.update(over)
    return body


async def _events(name: str) -> list[AuditLogEntry]:
    async with SessionLocal() as session:
        return list(
            (
                await session.execute(
                    select(AuditLogEntry).where(AuditLogEntry.event_name == name)
                )
            ).scalars().all()
        )


# --- RBAC --------------------------------------------------------------------


async def test_judge_config_requires_manage_judge_infra(client):
    token = await _participant(client)
    for method, path in (
        ("GET", "/settings"),
        ("PUT", "/settings"),
        ("GET", "/languages"),
        ("POST", "/languages"),
    ):
        resp = await client.request(method, BASE + path, json={}, headers=_auth(token))
        assert resp.status_code == 403, (method, path, resp.status_code)


# --- settings + the enable invariant ------------------------------------------


async def test_settings_ship_inert_with_lightweight_defaults(client):
    admin = await admin_token(client)
    resp = await client.get(f"{BASE}/settings", headers=_auth(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["executor"] == "docker"
    assert body["endpoint_url"] is None
    # One judging at a time by default (ADR-0042 §5).
    assert body["max_concurrent_judgings"] == 1


async def test_cannot_enable_without_an_endpoint_and_a_language(client):
    admin = await admin_token(client)

    no_endpoint = await client.put(
        f"{BASE}/settings", json={"enabled": True}, headers=_auth(admin)
    )
    assert no_endpoint.status_code == 400
    assert "endpoint" in no_endpoint.json()["detail"].lower()

    no_language = await client.put(
        f"{BASE}/settings",
        json={"enabled": True, "endpoint_url": "http://socket-proxy:2375"},
        headers=_auth(admin),
    )
    assert no_language.status_code == 400
    assert "language" in no_language.json()["detail"].lower()
    # The refused PUT changed nothing.
    after = (await client.get(f"{BASE}/settings", headers=_auth(admin))).json()
    assert after["enabled"] is False and after["endpoint_url"] is None

    await client.post(f"{BASE}/languages", json=_python(), headers=_auth(admin))
    ok = await client.put(
        f"{BASE}/settings",
        json={"enabled": True, "endpoint_url": "http://socket-proxy:2375"},
        headers=_auth(admin),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["enabled"] is True


async def test_settings_bounds_and_executor_are_validated(client):
    admin = await admin_token(client)
    for body in (
        {"executor": "kubernetes"},  # not an executor kind (yet)
        {"max_concurrent_judgings": 0},
        {"default_time_limit_ms": 10},
        {"default_memory_limit_mb": 1},
    ):
        resp = await client.put(f"{BASE}/settings", json=body, headers=_auth(admin))
        assert resp.status_code == 422, body


async def _enabled_judge(client, admin) -> str:
    created = await client.post(f"{BASE}/languages", json=_python(), headers=_auth(admin))
    assert created.status_code == 201, created.text
    await client.put(
        f"{BASE}/settings",
        json={"enabled": True, "endpoint_url": "http://socket-proxy:2375"},
        headers=_auth(admin),
    )
    return created.json()["id"]


async def test_last_enabled_language_cannot_be_disabled_or_deleted_while_enabled(client):
    """Otherwise the judge reaches the forbidden "enabled but unconfigured"
    state through the language registry rather than the settings form."""
    admin = await admin_token(client)
    lang_id = await _enabled_judge(client, admin)

    disable = await client.patch(
        f"{BASE}/languages/{lang_id}", json={"enabled": False}, headers=_auth(admin)
    )
    assert disable.status_code == 400
    delete = await client.delete(f"{BASE}/languages/{lang_id}", headers=_auth(admin))
    assert delete.status_code == 400

    # Both refusals rolled back: the language is still there and enabled.
    langs = (await client.get(f"{BASE}/languages", headers=_auth(admin))).json()
    assert [(lang["id"], lang["enabled"]) for lang in langs] == [(lang_id, True)]

    # Once the judge is disabled, the language can go.
    await client.put(f"{BASE}/settings", json={"enabled": False}, headers=_auth(admin))
    assert (
        await client.delete(f"{BASE}/languages/{lang_id}", headers=_auth(admin))
    ).status_code == 204


# --- language validation -----------------------------------------------------


async def test_language_commands_are_argv_lists_with_known_placeholders_only(client):
    admin = await admin_token(client)
    bad = [
        _python(key="Bad Key"),
        _python(key="py3", source_filename="../../etc/passwd"),
        _python(key="py4", source_filename=".hidden"),
        _python(key="py5", image_ref="python:3.13 slim"),
        # A shell string, not an argv list.
        _python(key="py6", run_command="python3 {source}"),
        _python(key="py7", run_command=[]),
        _python(key="py8", run_command=["python3", "{source}", "{secret_answers}"]),
        _python(key="py9", run_command=["python3", "{source}\x00"]),
        _python(key="py10", compile_command=["gcc", "{tests}"]),
    ]
    for body in bad:
        resp = await client.post(f"{BASE}/languages", json=body, headers=_auth(admin))
        assert resp.status_code == 422, (body, resp.status_code)

    good = await client.post(
        f"{BASE}/languages",
        json=_python(
            key="cpp17",
            name="C++17",
            image_ref="gcc:14",
            source_filename="main.cpp",
            compile_command=["g++", "-O2", "-std=c++17", "-o", "{work}/main", "{source}"],
            run_command=["{work}/main"],
            time_multiplier=1.0,
        ),
        headers=_auth(admin),
    )
    assert good.status_code == 201, good.text
    assert good.json()["compile_command"][-1] == "{source}"


async def test_language_key_is_unique_and_immutable(client):
    admin = await admin_token(client)
    first = await client.post(f"{BASE}/languages", json=_python(), headers=_auth(admin))
    assert first.status_code == 201
    dupe = await client.post(f"{BASE}/languages", json=_python(), headers=_auth(admin))
    assert dupe.status_code == 409

    # Problems refer to languages by key, so it can't be renamed in place.
    rename = await client.patch(
        f"{BASE}/languages/{first.json()['id']}", json={"key": "py"}, headers=_auth(admin)
    )
    assert rename.status_code == 422


async def test_compile_command_can_be_cleared_or_left_alone(client):
    admin = await admin_token(client)
    created = await client.post(
        f"{BASE}/languages",
        json=_python(compile_command=["python3", "-m", "py_compile", "{source}"]),
        headers=_auth(admin),
    )
    lang_id = created.json()["id"]

    untouched = await client.patch(
        f"{BASE}/languages/{lang_id}", json={"name": "Python"}, headers=_auth(admin)
    )
    assert untouched.json()["compile_command"] == ["python3", "-m", "py_compile", "{source}"]

    cleared = await client.patch(
        f"{BASE}/languages/{lang_id}", json={"compile_command": None}, headers=_auth(admin)
    )
    assert cleared.json()["compile_command"] is None


# --- audit trail -------------------------------------------------------------


async def test_config_changes_are_audited_without_the_commands(client):
    admin = await admin_token(client)
    lang_id = await _enabled_judge(client, admin)
    await client.patch(f"{BASE}/languages/{lang_id}", json={"name": "Py"}, headers=_auth(admin))

    assert await _events("judge.language_created")
    assert await _events("judge.language_updated")
    settings_events = await _events("judge.settings_updated")
    assert settings_events

    created = (await _events("judge.language_created"))[0]
    payload = created.payload or {}
    assert payload.get("key") == "python3"
    # Commands and images stay out of the event payload.
    assert "run_command" not in payload and "image_ref" not in payload


async def test_judge_is_an_optional_module(client):
    # The catalog lists *only* optional (per-competition toggleable) modules,
    # so appearing in it is the assertion — the judge is the eighth.
    admin = await admin_token(client)
    catalog = await client.get("/api/modules", headers=_auth(admin))
    assert catalog.status_code == 200, catalog.text
    assert "judge" in [m["id"] for m in catalog.json()]


# --- built-in presets + endpoint suggestion ----------------------------------


def test_every_preset_passes_the_same_validation_as_a_hand_entered_language():
    """A preset must not be a way around the argv/placeholder rules."""
    from schemas.judge import JudgeLanguageCreate
    from utils.judge_presets import LANGUAGE_PRESETS

    keys = [p["key"] for p in LANGUAGE_PRESETS]
    assert len(keys) == len(set(keys)), "preset keys must be unique"
    for preset in LANGUAGE_PRESETS:
        JudgeLanguageCreate(**preset, enabled=True)  # raises if invalid
        image = preset["image_ref"]
        # Pinned to a release line, and glibc-based: never a floating
        # :latest, never Alpine/musl (ADR-0042, utils/judge_presets).
        assert ":" in image and not image.endswith(":latest"), image
        assert "alpine" not in image, image


async def test_presets_are_listed_for_the_admin_and_can_be_added(client):
    admin = await admin_token(client)
    resp = await client.get(f"{BASE}/presets", headers=_auth(admin))
    assert resp.status_code == 200
    presets = {p["key"]: p for p in resp.json()}
    assert {"python3", "cpp", "java"} <= set(presets)

    # Adding one is an ordinary language create from the preset body.
    added = await client.post(
        f"{BASE}/languages", json={**presets["cpp"], "enabled": True}, headers=_auth(admin)
    )
    assert added.status_code == 201, added.text
    assert added.json()["image_ref"] == presets["cpp"]["image_ref"]


async def test_presets_require_manage_judge_infra(client):
    token = await _participant(client, "preset-peek@example.com")
    assert (await client.get(f"{BASE}/presets", headers=_auth(token))).status_code == 403


async def test_endpoint_suggestion_prefers_the_instancing_proxy(client):
    """A suggestion only — nothing is stored until the admin saves."""
    from models.challenge_instancing import INSTANCE_SETTINGS_ID, InstanceSettings

    admin = await admin_token(client)
    first = (await client.get(f"{BASE}/settings", headers=_auth(admin))).json()
    assert first["endpoint_url"] is None
    assert first["suggested_endpoint_url"] == "http://socket-proxy:2375"

    async with SessionLocal() as session:
        session.add(InstanceSettings(id=INSTANCE_SETTINGS_ID, endpoint_url="http://chal-proxy:2375"))
        await session.commit()

    second = (await client.get(f"{BASE}/settings", headers=_auth(admin))).json()
    assert second["endpoint_url"] is None
    assert second["suggested_endpoint_url"] == "http://chal-proxy:2375"


# --- deployment-managed endpoint ---------------------------------------------


async def test_a_deployment_endpoint_is_detected_and_not_editable(client, monkeypatch):
    """The docker-compose.judge.yml overlay sets JUDGE_ENDPOINT_URL; the setup
    flow then shows it as detected, and nothing can override it here."""
    from config import settings as app_settings

    monkeypatch.setattr(app_settings, "judge_endpoint_url", "http://judge-proxy:2375")
    admin = await admin_token(client)

    body = (await client.get(f"{BASE}/settings", headers=_auth(admin))).json()
    assert body["endpoint_managed"] is True
    assert body["endpoint_url"] == "http://judge-proxy:2375"

    refused = await client.put(
        f"{BASE}/settings", json={"endpoint_url": "http://elsewhere:2375"}, headers=_auth(admin)
    )
    assert refused.status_code == 400

    # The managed endpoint satisfies the enable invariant on its own.
    await client.post(f"{BASE}/languages", json=_python(), headers=_auth(admin))
    on = await client.put(f"{BASE}/settings", json={"enabled": True}, headers=_auth(admin))
    assert on.status_code == 200, on.text


# --- connection check ---------------------------------------------------------


def _docker_transport(*, restricted: bool):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_ping":
            return httpx.Response(200, text="OK", headers={"Api-Version": "1.47"})
        # A restricted proxy refuses the dangerous verbs; a raw socket doesn't.
        return httpx.Response(403 if restricted else 404, json={"message": "x"})

    return httpx.MockTransport(handler)


async def test_check_passes_a_restricted_proxy_and_fails_a_raw_socket():
    from utils.judge_connection import check_endpoint

    good = await check_endpoint(
        "http://judge-proxy:2375", transport=_docker_transport(restricted=True)
    )
    assert [(leg.name, leg.ok) for leg in good] == [
        ("endpoint_reachable", True),
        ("proxy_restricted", True),
    ]

    # The security-critical leg: an endpoint that answers exec/volumes/build is
    # effectively the host's Docker, and must not pass.
    raw = await check_endpoint(
        "http://docker:2375", transport=_docker_transport(restricted=False)
    )
    assert raw[1].name == "proxy_restricted" and raw[1].ok is False
    assert "NOT blocked" in raw[1].detail


async def test_check_reports_an_unreachable_endpoint():
    import httpx

    from utils.judge_connection import check_endpoint

    def boom(request):
        raise httpx.ConnectError("connection refused", request=request)

    legs = await check_endpoint("http://nowhere:2375", transport=httpx.MockTransport(boom))
    assert [(leg.name, leg.ok) for leg in legs] == [("endpoint_reachable", False)]


async def test_check_only_ever_probes_the_saved_endpoint(client, monkeypatch):
    """Never a URL from the request: otherwise the check would let the server
    be pointed at arbitrary addresses."""
    import routers.judge_admin as judge_admin

    probed: list[str] = []

    async def fake_check(settings):
        from utils.judge_connection import effective_endpoint

        probed.append(effective_endpoint(settings)[0])
        return []

    monkeypatch.setattr(judge_admin, "_run_check", fake_check)
    admin = await admin_token(client)

    nothing_saved = await client.post(f"{BASE}/check", headers=_auth(admin))
    assert nothing_saved.status_code == 400

    await client.put(
        f"{BASE}/settings", json={"endpoint_url": "http://judge-proxy:2375"}, headers=_auth(admin)
    )
    # A URL smuggled into the body is ignored.
    await client.post(
        f"{BASE}/check", json={"endpoint_url": "http://169.254.169.254/"}, headers=_auth(admin)
    )
    assert probed == ["http://judge-proxy:2375"]


# --- atomic setup -------------------------------------------------------------


async def test_setup_adds_ticked_languages_and_enables_the_judge(client):
    admin = await admin_token(client)
    await client.put(
        f"{BASE}/settings", json={"endpoint_url": "http://judge-proxy:2375"}, headers=_auth(admin)
    )
    resp = await client.post(
        f"{BASE}/setup", json={"preset_keys": ["python3", "cpp"]}, headers=_auth(admin)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["settings"]["enabled"] is True
    assert sorted((lang["key"], lang["enabled"]) for lang in body["languages"]) == [
        ("cpp", True),
        ("python3", True),
    ]
    assert await _events("judge.language_created")


async def test_rerunning_setup_disables_unticked_builtins_but_keeps_pins_and_custom(client):
    admin = await admin_token(client)
    await client.put(
        f"{BASE}/settings", json={"endpoint_url": "http://judge-proxy:2375"}, headers=_auth(admin)
    )
    first = await client.post(
        f"{BASE}/setup", json={"preset_keys": ["python3", "cpp"]}, headers=_auth(admin)
    )
    py_id = next(l["id"] for l in first.json()["languages"] if l["key"] == "python3")
    # The operator re-pins Python, and adds a custom language.
    await client.patch(
        f"{BASE}/languages/{py_id}", json={"image_ref": "python:3.13-slim"}, headers=_auth(admin)
    )
    await client.post(
        f"{BASE}/languages", json=_python(key="py-numpy", name="NumPy"), headers=_auth(admin)
    )

    second = await client.post(f"{BASE}/setup", json={"preset_keys": ["cpp"]}, headers=_auth(admin))
    assert second.status_code == 200, second.text
    langs = {l["key"]: l for l in second.json()["languages"]}
    assert langs["python3"]["enabled"] is False  # unticked built-in → off…
    assert langs["python3"]["image_ref"] == "python:3.13-slim"  # …but the pin is kept
    assert langs["cpp"]["enabled"] is True
    assert langs["py-numpy"]["enabled"] is True  # custom languages untouched


async def test_setup_is_atomic_when_it_cannot_complete(client):
    """No endpoint yet: setup refuses — and adds no languages on the way."""
    admin = await admin_token(client)
    resp = await client.post(
        f"{BASE}/setup", json={"preset_keys": ["python3"]}, headers=_auth(admin)
    )
    assert resp.status_code == 400
    assert (await client.get(f"{BASE}/languages", headers=_auth(admin))).json() == []
    assert (await client.get(f"{BASE}/settings", headers=_auth(admin))).json()["enabled"] is False


async def test_setup_rejects_unknown_or_empty_language_lists(client):
    admin = await admin_token(client)
    for body in ({"preset_keys": []}, {"preset_keys": ["cobol"]}):
        resp = await client.post(f"{BASE}/setup", json=body, headers=_auth(admin))
        assert resp.status_code == 422, body
