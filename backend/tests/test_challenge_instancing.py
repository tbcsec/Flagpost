"""Phase 0 of challenge instancing (#266, ADR-0036): the provisioner
contract, the kind registry, the shared-static kind, and the data model —
including the lifecycle state machine and the active-subject query the
grading path and cap checks will sit on.

No routes, module or events exist yet, so everything here is exercised at
the contract/model level; the API surface arrives with Phase 1.
"""

import pytest
from sqlalchemy import func, select

from db import SessionLocal
from models.challenge_instancing import (
    INSTANCE_ACTIVE_STATUSES,
    INSTANCE_STATUSES,
    INSTANCE_TRANSITIONS,
    ChallengeDeployment,
    ChallengeInstance,
    instance_can_transition,
)
from tests.conftest import admin_token
from utils.provisioners import (
    CheckResult,
    ProvisionSpec,
    ProvisionerError,
    SharedStaticProvisioner,
    UnknownProvisionerKind,
    provisioner_kind,
    provisioner_kinds,
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_competition(client) -> str:
    token = await admin_token(client)
    resp = await client.post(
        "/api/competitions", json={"name": "Instanced CTF"}, headers=_auth(token)
    )
    return resp.json()["id"]


async def _make_challenge(client, comp: str) -> str:
    token = await admin_token(client)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "pwn me", "points": 100, "flag": "flag{static}"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _spec(**over) -> ProvisionSpec:
    base = dict(
        instance_id="i1",
        deployment_id="d1",
        challenge_id="c1",
        competition_id="comp1",
        image_ref=None,
        manifest={"endpoints": [{"kind": "tcp", "host": "chal.example", "port": 31337}]},
        exposure="tcp",
        ports=[],
        env={},
        resource_limits=None,
        lifetime_s=3600,
        subject_key="team-1",
    )
    base.update(over)
    return ProvisionSpec(**base)


# --- state machine -----------------------------------------------------------


def test_transition_table_is_closed_and_terminal_states_are_terminal():
    # Every status the table names is a known status, and vice versa.
    assert set(INSTANCE_TRANSITIONS) == set(INSTANCE_STATUSES)
    for targets in INSTANCE_TRANSITIONS.values():
        assert set(targets) <= set(INSTANCE_STATUSES)

    # The happy path walks end to end.
    for a, b in [
        ("requested", "provisioning"),
        ("provisioning", "running"),
        ("running", "expiring"),
        ("expiring", "destroyed"),
    ]:
        assert instance_can_transition(a, b), f"{a} → {b}"

    # Idempotent re-entry is always legal (retried background work).
    for s in INSTANCE_STATUSES:
        assert instance_can_transition(s, s)

    # Terminal states go nowhere else.
    for terminal in ("destroyed", "failed"):
        for target in INSTANCE_STATUSES:
            if target != terminal:
                assert not instance_can_transition(terminal, target)

    # Active-status tuple matches the machine: exactly the non-terminal set.
    assert set(INSTANCE_ACTIVE_STATUSES) == set(INSTANCE_STATUSES) - {
        "destroyed",
        "failed",
    }


# --- registry ----------------------------------------------------------------


def test_registry_resolves_known_kind_and_rejects_unknown():
    assert "shared-static" in provisioner_kinds()
    assert provisioner_kind("shared-static") is SharedStaticProvisioner
    with pytest.raises(UnknownProvisionerKind):
        provisioner_kind("openstack")


# --- shared-static kind ------------------------------------------------------


async def test_shared_static_lifecycle_with_valid_manifest():
    manifest = {
        "endpoints": [
            {"kind": "tcp", "host": "chal.example.org", "port": 31337},
            {"kind": "http", "url": "https://web.chal.example.org"},
        ]
    }
    prov = SharedStaticProvisioner(manifest)

    legs = await prov.validate()
    assert all(leg.ok for leg in legs), legs
    assert legs[0].name == "endpoints_configured"
    assert isinstance(legs[0], CheckResult)

    handle = await prov.create(_spec(manifest=manifest))
    assert await prov.status(handle) == "running"
    assert await prov.endpoints(handle) == manifest["endpoints"]
    # Idempotent destroy, nothing to orphan-reap.
    await prov.destroy(handle)
    await prov.destroy(handle)
    assert await prov.list() == []


async def test_shared_static_refuses_unconnectable_config():
    empty = SharedStaticProvisioner(None)
    legs = await empty.validate()
    assert legs[0].name == "endpoints_configured" and not legs[0].ok
    with pytest.raises(ProvisionerError):
        await empty.create(_spec(manifest=None))

    # A malformed endpoint fails its own named leg with actionable detail.
    bad = SharedStaticProvisioner({"endpoints": [{"kind": "tcp", "host": "x"}]})
    legs = await bad.validate()
    by_name = {leg.name: leg for leg in legs}
    assert by_name["endpoints_configured"].ok
    assert not by_name["endpoint_0_shape"].ok
    assert "host+port" in by_name["endpoint_0_shape"].detail


# --- data model --------------------------------------------------------------


async def test_model_roundtrip_and_active_subject_query(client):
    comp = await _make_competition(client)
    chal = await _make_challenge(client, comp)
    admin = await admin_token(client)
    admin_id = (
        await client.get("/api/auth/me", headers=_auth(admin))
    ).json()["id"]

    subject = func.coalesce(ChallengeInstance.team_id, ChallengeInstance.user_id)

    async with SessionLocal() as session:
        deployment = ChallengeDeployment(
            competition_id=comp,
            challenge_id=chal,
            backend="shared-static",
            manifest={"endpoints": [{"kind": "tcp", "host": "h", "port": 1}]},
            exposure="tcp",
            ports=[],
            env={},
        )
        session.add(deployment)
        await session.flush()
        instance = ChallengeInstance(
            competition_id=comp,
            challenge_id=chal,
            deployment_id=deployment.id,
            user_id=admin_id,
            team_id=None,  # individual-mode shape: subject falls back to user
            endpoints=[],
        )
        session.add(instance)
        await session.commit()
        instance_id = instance.id

    # The active-subject lookup (grading + cap check): the fresh "requested"
    # row is active and credited to the user in the absence of a team.
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(ChallengeInstance).where(
                    ChallengeInstance.competition_id == comp,
                    ChallengeInstance.challenge_id == chal,
                    subject == admin_id,
                    ChallengeInstance.status.in_(INSTANCE_ACTIVE_STATUSES),
                )
            )
        ).scalar_one()
        assert row.id == instance_id
        assert row.status == "requested"
        assert row.extend_count == 0

        # Walk it to a terminal state and it drops out of the active query.
        row.status = "destroyed"
        await session.commit()

    async with SessionLocal() as session:
        gone = (
            await session.execute(
                select(ChallengeInstance).where(
                    ChallengeInstance.challenge_id == chal,
                    subject == admin_id,
                    ChallengeInstance.status.in_(INSTANCE_ACTIVE_STATUSES),
                )
            )
        ).scalar_one_or_none()
        assert gone is None


async def test_one_deployment_per_challenge(client):
    comp = await _make_competition(client)
    chal = await _make_challenge(client, comp)

    async with SessionLocal() as session:
        session.add(
            ChallengeDeployment(
                competition_id=comp,
                challenge_id=chal,
                backend="docker",
                image_ref="ghcr.io/example/pwn:1",
                ports=[1337],
                env={},
            )
        )
        await session.commit()

    from sqlalchemy.exc import IntegrityError

    async with SessionLocal() as session:
        session.add(
            ChallengeDeployment(
                competition_id=comp,
                challenge_id=chal,
                backend="docker",
                image_ref="ghcr.io/example/pwn:2",
                ports=[1338],
                env={},
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


# --- P1a: settings, permissions, per-competition policy ----------------------


def test_new_permissions_are_catalogued_and_role_granted():
    from auth.permissions import (
        ALL_PERMISSION_KEYS,
        ADMINISTRATOR_PERMISSIONS,
        JUDGE_PERMISSIONS,
        PARTICIPANT_PERMISSIONS,
    )

    keys = (
        "manage_instance_infra",
        "instance_launch",
        "instance_view",
        "instance_manage",
    )
    for k in keys:
        assert k in ALL_PERMISSION_KEYS
        assert k in ADMINISTRATOR_PERMISSIONS  # Administrator holds everything

    # Competitor-facing launch reaches Participants; staff view/manage do not.
    assert "instance_launch" in PARTICIPANT_PERMISSIONS
    assert "instance_view" not in PARTICIPANT_PERMISSIONS
    assert "instance_manage" not in PARTICIPANT_PERMISSIONS

    # A Judge runs their competition: launch + view + manage, but site
    # provisioner config stays Administrator-only.
    for k in ("instance_launch", "instance_view", "instance_manage"):
        assert k in JUDGE_PERMISSIONS
    assert "manage_instance_infra" not in JUDGE_PERMISSIONS


async def test_seeded_roles_carry_the_new_grants(client):
    # The startup role re-sync (seed_system_roles) runs in the test bootstrap,
    # so an existing install's built-in roles gain the keys with no migration.
    from sqlalchemy import select

    from models.role import Role

    async with SessionLocal() as session:
        admin = await session.scalar(
            select(Role).where(Role.name == "Administrator", Role.is_system.is_(True))
        )
        judge = await session.scalar(
            select(Role).where(Role.name == "Judge", Role.is_system.is_(True))
        )
        participant = await session.scalar(
            select(Role).where(Role.name == "Participant", Role.is_system.is_(True))
        )
    assert "manage_instance_infra" in admin.permissions
    assert "instance_manage" in judge.permissions
    assert "manage_instance_infra" not in judge.permissions
    assert "instance_launch" in participant.permissions
    assert "instance_view" not in participant.permissions


async def test_instance_settings_singleton_defaults():
    from models.challenge_instancing import (
        DEFAULT_MAX_CONCURRENT,
        DEFAULT_TCP_PORT_MAX,
        DEFAULT_TCP_PORT_MIN,
        INSTANCE_SETTINGS_ID,
        InstanceSettings,
    )

    async with SessionLocal() as session:
        row = InstanceSettings()
        session.add(row)
        await session.commit()
        await session.refresh(row)

    assert row.id == INSTANCE_SETTINGS_ID
    # Ships inert: disabled, no endpoint, deny-egress by default.
    assert row.enabled is False
    assert row.backend == "docker"
    assert row.endpoint_url is None
    assert row.egress_policy == "deny"
    assert row.tcp_port_min == DEFAULT_TCP_PORT_MIN
    assert row.tcp_port_max == DEFAULT_TCP_PORT_MAX
    assert row.max_concurrent == DEFAULT_MAX_CONCURRENT
    assert row.default_cpu == 1.0
    # Phase 2 HTTP fields (#319) ship inert: no base domain, throttle off.
    assert row.chal_base_domain is None
    assert row.spawn_rate_limit == 0
    assert row.spawn_rate_window_seconds == 60
    # Phase 3 kubernetes fields (#320) ship inert: default namespace, nothing
    # else set — a docker site never reads them.
    assert row.k8s_namespace == "flagpost-instances"
    assert row.k8s_ca_cert is None
    assert row.k8s_ingress_class is None
    assert row.k8s_image_pull_secret is None
    assert row.k8s_cluster_cidr is None


async def test_settings_roundtrip_http_and_rate_limit_fields(client):
    admin = await admin_token(client)
    body = {
        "endpoint_url": "http://socket-proxy:2375",
        "public_host": "ctf.example.org",
        "chal_base_domain": "  CHAL.Example.ORG  ",  # normalised: strip + lower
        "spawn_rate_limit": 5,
        "spawn_rate_window_seconds": 120,
    }
    r = await client.put("/api/admin/instances/settings", json=body, headers=_auth(admin))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["chal_base_domain"] == "chal.example.org"
    assert out["spawn_rate_limit"] == 5
    assert out["spawn_rate_window_seconds"] == 120
    # "" clears the base domain.
    cleared = await client.put(
        "/api/admin/instances/settings",
        json={"chal_base_domain": ""},
        headers=_auth(admin),
    )
    assert cleared.json()["chal_base_domain"] is None


async def test_settings_rejects_malformed_base_domain(client):
    admin = await admin_token(client)
    for bad in (
        "https://chal.example.org",  # scheme
        "chal.example.org/x",         # path
        "chal.example.org:8443",      # port
        "chal .example.org",          # whitespace
        ".chal.example.org",          # leading dot
    ):
        r = await client.put(
            "/api/admin/instances/settings",
            json={"chal_base_domain": bad},
            headers=_auth(admin),
        )
        assert r.status_code == 422, f"{bad!r} accepted ({r.status_code})"


async def test_settings_roundtrip_k8s_fields(client):
    admin = await admin_token(client)
    body = {
        "backend": "kubernetes",
        "endpoint_url": "https://k8s.internal:6443",
        "public_host": "chal.example.org",
        "k8s_namespace": "  flagpost-instances  ",  # normalised: stripped
        "k8s_bearer_token": "eyJhbGciOiJSUzI1NiJ9.token",
        "k8s_ca_cert": "-----BEGIN CERTIFICATE-----\nMIIB…\n-----END CERTIFICATE-----",
        "k8s_ingress_class": "traefik",
        "k8s_image_pull_secret": "flagpost-pull",
        # Host bits normalised to the network address; two ranges kept in order.
        "k8s_cluster_cidr": "10.42.0.1/16, 10.43.0.0/16",
    }
    r = await client.put("/api/admin/instances/settings", json=body, headers=_auth(admin))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["k8s_namespace"] == "flagpost-instances"
    assert out["k8s_ingress_class"] == "traefik"
    assert out["k8s_image_pull_secret"] == "flagpost-pull"
    assert out["k8s_cluster_cidr"] == "10.42.0.0/16,10.43.0.0/16"
    # The token is write-only: reported as stored, never echoed anywhere in
    # the response body.
    assert out["k8s_bearer_token_set"] is True
    assert "k8s_bearer_token" not in out
    assert "eyJhbGciOiJSUzI1NiJ9.token" not in r.text

    # GET agrees with PUT's view of the stored token.
    got = await client.get("/api/admin/instances/settings", headers=_auth(admin))
    assert got.json()["k8s_bearer_token_set"] is True

    # "" clears the token (and the other clearable fields).
    cleared = await client.put(
        "/api/admin/instances/settings",
        json={"k8s_bearer_token": "", "k8s_cluster_cidr": "", "k8s_ingress_class": ""},
        headers=_auth(admin),
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["k8s_bearer_token_set"] is False
    assert cleared.json()["k8s_cluster_cidr"] is None
    assert cleared.json()["k8s_ingress_class"] is None


async def test_settings_rejects_malformed_k8s_fields(client):
    admin = await admin_token(client)
    for field, bad in (
        ("k8s_namespace", ""),  # not clearable — the column is non-null
        ("k8s_namespace", "Has.Dots"),
        ("k8s_namespace", "-leading-hyphen"),
        ("k8s_namespace", "x" * 64),
        ("k8s_ca_cert", "not a pem"),
        ("k8s_ca_cert", "eyJhbGciOiJSUzI1NiJ9"),  # a pasted token, the likely slip
        ("k8s_ingress_class", "Bad_Class!"),
        ("k8s_ingress_class", "a" * 64 + ".cls"),  # per-label 63-char cap
        ("k8s_image_pull_secret", "UPPER"),
        ("k8s_cluster_cidr", "banana"),
        ("k8s_cluster_cidr", "10.42.0.0/99"),
        ("k8s_cluster_cidr", "10.42.0.0/16,nope"),
    ):
        r = await client.put(
            "/api/admin/instances/settings",
            json={field: bad},
            headers=_auth(admin),
        )
        assert r.status_code == 422, f"{field}={bad!r} accepted ({r.status_code})"


async def test_enable_kubernetes_requires_a_bearer_token(client):
    admin = await admin_token(client)
    base = {
        "backend": "kubernetes",
        "endpoint_url": "https://k8s.internal:6443",
        "public_host": "chal.example.org",
    }
    # Endpoint + public host alone aren't enough for the kubernetes kind.
    refused = await client.put(
        "/api/admin/instances/settings",
        json={**base, "enabled": True},
        headers=_auth(admin),
    )
    assert refused.status_code == 400
    assert "token" in refused.json()["detail"].lower()

    # A whitespace-only token is stripped to "" → still not configured, so
    # enabling is refused (the strip validator closes the "enabled but
    # unconfigured" bypass).
    ws = await client.put(
        "/api/admin/instances/settings",
        json={**base, "k8s_bearer_token": "   ", "enabled": True},
        headers=_auth(admin),
    )
    assert ws.status_code == 400

    # With a stored token, enabling succeeds…
    ok = await client.put(
        "/api/admin/instances/settings",
        json={**base, "k8s_bearer_token": "sa-token", "enabled": True},
        headers=_auth(admin),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["enabled"] is True

    # …and clearing the token while enabled is refused (the invariant reads the
    # in-flight clear, not the stale stored ciphertext).
    cleared = await client.put(
        "/api/admin/instances/settings",
        json={"k8s_bearer_token": ""},
        headers=_auth(admin),
    )
    assert cleared.status_code == 400

    # Cleanly disable + clear for any later settings tests.
    reset = await client.put(
        "/api/admin/instances/settings",
        json={"enabled": False, "k8s_bearer_token": "", "backend": "docker"},
        headers=_auth(admin),
    )
    assert reset.status_code == 200, reset.text


async def test_backend_change_refused_while_instances_are_active(client):
    """#320: flipping the site backend re-homes every orchestrated instance's
    teardown path, so the PUT refuses the change while any are live (else they
    strand un-destroyable). shared-static instances don't count — they resolve
    to their own kind regardless of the site backend."""
    from models.user import User

    admin = await admin_token(client)
    comp = await _make_competition(client)
    chal = await _make_challenge(client, comp)
    async with SessionLocal() as session:
        uid = await session.scalar(select(User.id).limit(1))
        dep = ChallengeDeployment(
            competition_id=comp,
            challenge_id=chal,
            backend="docker",
            image_ref="img:latest",
            exposure="tcp",
            ports=[1337],
        )
        session.add(dep)
        await session.flush()
        inst = ChallengeInstance(
            competition_id=comp,
            challenge_id=chal,
            deployment_id=dep.id,
            user_id=uid,
            status="running",
            backend_handle="container-123",
        )
        session.add(inst)
        await session.commit()
        inst_id = inst.id

    # A live docker instance blocks the flip to kubernetes.
    blocked = await client.put(
        "/api/admin/instances/settings",
        json={"backend": "kubernetes"},
        headers=_auth(admin),
    )
    assert blocked.status_code == 400, blocked.text
    assert "running instance" in blocked.json()["detail"]

    # Re-saving the SAME backend is never blocked (no re-homing).
    same = await client.put(
        "/api/admin/instances/settings",
        json={"backend": "docker", "max_concurrent": 50},
        headers=_auth(admin),
    )
    assert same.status_code == 200, same.text

    # Once the instance is terminal, the flip is allowed.
    async with SessionLocal() as session:
        row = await session.get(ChallengeInstance, inst_id)
        row.status = "destroyed"
        await session.commit()
    ok = await client.put(
        "/api/admin/instances/settings",
        json={"backend": "kubernetes"},
        headers=_auth(admin),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["backend"] == "kubernetes"


def test_effective_backend_resolves_through_site_settings():
    """#320 D7: the site backend decides how orchestrated deployments run;
    shared-static stays per-deployment; unconfigured falls back to authored."""
    from models.challenge_instancing import InstanceSettings
    from utils.instance_service import effective_backend

    docker_dep = ChallengeDeployment(backend="docker")
    static_dep = ChallengeDeployment(backend="shared-static")
    k8s_site = InstanceSettings(backend="kubernetes")
    docker_site = InstanceSettings(backend="docker")

    assert effective_backend(k8s_site, docker_dep) == "kubernetes"
    assert effective_backend(docker_site, docker_dep) == "docker"
    # A kubernetes-authored spec on a docker site runs on docker — symmetric.
    assert effective_backend(docker_site, ChallengeDeployment(backend="kubernetes")) == "docker"
    # shared-static ignores the site backend entirely.
    assert effective_backend(k8s_site, static_dep) == "shared-static"
    # Never configured: fall back to the authored kind (launch refuses anyway).
    assert effective_backend(None, docker_dep) == "docker"


async def test_competition_instancing_policy_roundtrips(client):
    token = await admin_token(client)

    created = await client.post(
        "/api/competitions",
        json={"name": "Instanced", "instance_max_alive": 3, "instance_lifetime_s": 1800},
        headers=_auth(token),
    )
    assert created.status_code == 201, created.text
    comp_id = created.json()["id"]
    assert created.json()["instance_max_alive"] == 3
    assert created.json()["instance_lifetime_s"] == 1800

    # PATCH overrides via the ordinary competition update (setattr path).
    patched = await client.patch(
        f"/api/competitions/{comp_id}",
        json={"instance_max_alive": 1},
        headers=_auth(token),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["instance_max_alive"] == 1
    assert patched.json()["instance_lifetime_s"] == 1800  # untouched

    # Null policy is legal (means "use site defaults") and is what a
    # competition created without the fields carries.
    plain = await client.post(
        "/api/competitions", json={"name": "Plain"}, headers=_auth(token)
    )
    assert plain.json()["instance_max_alive"] is None
    assert plain.json()["instance_lifetime_s"] is None

    # Out-of-range values are rejected by the schema, not silently clamped.
    bad = await client.patch(
        f"/api/competitions/{comp_id}",
        json={"instance_lifetime_s": 5},  # below the 60s floor
        headers=_auth(token),
    )
    assert bad.status_code == 422
