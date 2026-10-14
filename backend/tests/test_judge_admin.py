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
