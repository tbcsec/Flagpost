"""Instance lifecycle internals (#266, ADR-0036 §2/§4): the TCP port allocator,
the global concurrency backstop, and the scheduler reaper (TTL expiry + stuck
provisioning). Runs on the zero-infra shared-static kind and direct DB rows, so
no Docker daemon is touched (the docker path is covered in
``test_provisioner_docker``)."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from db import SessionLocal, utcnow
from models.audit_log import AuditLogEntry
from models.challenge_instancing import (
    INSTANCE_SETTINGS_ID,
    ChallengeDeployment,
    ChallengeInstance,
    InstanceSettings,
)
from models.role import Role, RoleAssignment
from tests.conftest import admin_token
from utils import instance_service as svc
from utils.instance_reaper import reap_instances

pytestmark = pytest.mark.asyncio


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _scaffold(client):
    """A competition, a challenge, its shared-static deployment, and a
    registered participant — all via the API, returning the ids the direct-DB
    tests need."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual"},
            headers=_auth(admin),
        )
    ).json()["id"]
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "c", "points": 100, "flag": "flag{x}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    dep = (
        await client.put(
            f"/api/competitions/{comp}/challenges/{chal}/deployment",
            json={
                "backend": "shared-static",
                "exposure": "tcp",
                "ports": [1337],
                "manifest": {
                    "endpoints": [{"kind": "tcp", "host": "h", "port": 31337}]
                },
            },
            headers=_auth(admin),
        )
    ).json()["id"]
    reg = await client.post(
        "/api/auth/register",
        json={
            "email": "p@example.com",
            "password": "password123",
            "display_name": "p",
        },
    )
    uid = reg.json()["user"]["id"]
    async with SessionLocal() as db:
        role = await db.scalar(select(Role).where(Role.name == "Participant"))
        db.add(RoleAssignment(user_id=uid, competition_id=comp, role_id=role.id))
        await db.commit()
    return comp, chal, dep, uid


async def _insert(db, *, comp, chal, dep, uid, **over) -> ChallengeInstance:
    data = dict(
        competition_id=comp,
        challenge_id=chal,
        deployment_id=dep,
        user_id=uid,
        status="running",
        endpoints=[],
    )
    data.update(over)
    created_at = data.pop("created_at", None)
    inst = ChallengeInstance(**data)
    if created_at is not None:
        inst.created_at = created_at
    db.add(inst)
    await db.commit()
    await db.refresh(inst)
    return inst


async def _events(name: str):
    async with SessionLocal() as db:
        return (
            await db.execute(
                select(AuditLogEntry).where(AuditLogEntry.event_name == name)
            )
        ).scalars().all()


# --- port allocation ---------------------------------------------------------


async def test_allocator_picks_lowest_free_and_skips_used(client):
    comp, chal, dep, uid = await _scaffold(client)
    settings = InstanceSettings(
        id=INSTANCE_SETTINGS_ID, tcp_port_min=30000, tcp_port_max=30005
    )
    async with SessionLocal() as db:
        await _insert(
            db,
            comp=comp,
            chal=chal,
            dep=dep,
            uid=uid,
            endpoints=[{"kind": "tcp", "host": "h", "port": 30000}],
        )
        await _insert(
            db,
            comp=comp,
            chal=chal,
            dep=dep,
            uid=uid,
            endpoints=[{"kind": "tcp", "host": "h", "port": 30001}],
        )
        ports = await svc._allocate_host_ports(db, settings, 1)
    assert ports == [30002]


async def test_allocator_raises_when_range_is_exhausted(client):
    comp, chal, dep, uid = await _scaffold(client)
    settings = InstanceSettings(
        id=INSTANCE_SETTINGS_ID, tcp_port_min=30000, tcp_port_max=30000
    )
    async with SessionLocal() as db:
        await _insert(
            db,
            comp=comp,
            chal=chal,
            dep=dep,
            uid=uid,
            endpoints=[{"kind": "tcp", "host": "h", "port": 30000}],
        )
        with pytest.raises(svc.PortsExhausted):
            await svc._allocate_host_ports(db, settings, 1)


async def test_plan_endpoints_allocates_for_docker_tcp_only(client):
    comp, chal, dep, uid = await _scaffold(client)
    settings = InstanceSettings(
        id=INSTANCE_SETTINGS_ID,
        tcp_port_min=40000,
        tcp_port_max=40010,
        public_host="chal.example",
    )
    docker_dep = ChallengeDeployment(
        competition_id=comp,
        challenge_id=chal,
        backend="docker",
        image_ref="img:latest",
        exposure="tcp",
        ports=[1337, 8080],
    )
    static_dep = ChallengeDeployment(
        competition_id=comp,
        challenge_id=chal,
        backend="shared-static",
        exposure="tcp",
        ports=[1337],
    )
    async with SessionLocal() as db:
        docker_eps, docker_sub = await svc._plan_endpoints(db, settings, docker_dep)
        static_eps, static_sub = await svc._plan_endpoints(db, settings, static_dep)
    # One host port per declared container port, from the range, on the public host.
    assert [e["port"] for e in docker_eps] == [40000, 40001]
    assert all(e["host"] == "chal.example" for e in docker_eps)
    assert docker_sub is None  # TCP exposure has no subdomain
    # Shared-static gets its endpoints from its manifest at provision time, not here.
    assert static_eps == [] and static_sub is None


async def test_plan_endpoints_kubernetes_site_allocates_like_docker(client):
    """#320 D7: a docker-authored spec on a kubernetes-configured site draws
    NodePorts/subdomains from the same range and ledger — the allocation layer
    keys on the *effective* backend, not the authored one."""
    comp, chal, dep, uid = await _scaffold(client)
    settings = InstanceSettings(
        id=INSTANCE_SETTINGS_ID,
        backend="kubernetes",
        tcp_port_min=40000,
        tcp_port_max=40010,
        public_host="chal.example",
        chal_base_domain="chal.example.org",
    )
    tcp_dep = ChallengeDeployment(
        competition_id=comp,
        challenge_id=chal,
        backend="docker",
        image_ref="img:latest",
        exposure="tcp",
        ports=[1337],
    )
    http_dep = ChallengeDeployment(
        competition_id=comp,
        challenge_id=chal,
        backend="docker",
        image_ref="img:latest",
        exposure="http",
        ports=[8080],
    )
    async with SessionLocal() as db:
        tcp_eps, tcp_sub = await svc._plan_endpoints(db, settings, tcp_dep)
        http_eps, http_sub = await svc._plan_endpoints(db, settings, http_dep)
    assert [e["port"] for e in tcp_eps] == [40000] and tcp_sub is None
    assert http_sub is not None and len(http_sub) == 8
    assert http_eps == [{"kind": "http", "url": f"https://{http_sub}.chal.example.org"}]


async def test_plan_endpoints_http_allocates_a_subdomain_url(client):
    comp, chal, dep, uid = await _scaffold(client)
    settings = InstanceSettings(
        id=INSTANCE_SETTINGS_ID,
        public_host="chal.example",
        chal_base_domain="chal.example.org",
    )
    http_dep = ChallengeDeployment(
        competition_id=comp,
        challenge_id=chal,
        backend="docker",
        image_ref="img:latest",
        exposure="http",
        ports=[8080],
    )
    async with SessionLocal() as db:
        eps, subdomain = await svc._plan_endpoints(db, settings, http_dep)
    # A unique 8-char token drives a single https endpoint on the base domain.
    assert subdomain is not None and len(subdomain) == 8
    assert eps == [{"kind": "http", "url": f"https://{subdomain}.chal.example.org"}]


async def test_plan_endpoints_http_needs_a_base_domain(client):
    import pytest

    comp, chal, dep, uid = await _scaffold(client)
    settings = InstanceSettings(id=INSTANCE_SETTINGS_ID, chal_base_domain=None)
    http_dep = ChallengeDeployment(
        competition_id=comp,
        challenge_id=chal,
        backend="docker",
        image_ref="img:latest",
        exposure="http",
        ports=[8080],
    )
    async with SessionLocal() as db:
        with pytest.raises(svc.BackendNotReady):
            await svc._plan_endpoints(db, settings, http_dep)


async def test_spec_for_threads_the_subdomain_and_binds_no_ports():
    inst = ChallengeInstance(
        id="i1",
        challenge_id="c1",
        competition_id="comp1",
        deployment_id="d1",
        user_id="u1",
        subdomain="k7m2q9xz",
        endpoints=[{"kind": "http", "url": "https://k7m2q9xz.chal.example.org"}],
    )
    dep = ChallengeDeployment(
        id="d1",
        competition_id="comp1",
        challenge_id="c1",
        backend="docker",
        exposure="http",
        image_ref="img:latest",
        ports=[8080],
    )
    spec = svc._spec_for(inst, dep, lifetime=600)
    assert spec.subdomain == "k7m2q9xz"
    assert spec.exposure == "http"
    # HTTP has no host-port bindings — routing is label-driven (#319).
    assert spec.host_ports == {}


# --- transition guard --------------------------------------------------------


async def test_transition_refuses_illegal_steps():
    inst = ChallengeInstance(
        competition_id="c", challenge_id="ch", deployment_id="d", user_id="u",
        status="destroyed",
    )
    assert svc.transition(inst, "running") is False
    assert inst.status == "destroyed"
    inst.status = "requested"
    assert svc.transition(inst, "provisioning") is True
    assert inst.status == "provisioning"


# --- global concurrency backstop ---------------------------------------------


async def test_global_max_concurrent_refuses_launch(client):
    comp, chal, dep, uid = await _scaffold(client)
    async with SessionLocal() as db:
        db.add(InstanceSettings(id=INSTANCE_SETTINGS_ID, max_concurrent=1))
        # One instance already alive globally.
        await _insert(db, comp=comp, chal=chal, dep=dep, uid=uid)
        await db.commit()
    # A different competitor tries to launch → the global ceiling refuses it.
    token = (
        await client.post(
            "/api/auth/register",
            json={
                "email": "q@example.com",
                "password": "password123",
                "display_name": "q",
            },
        )
    ).json()["access_token"]
    async with SessionLocal() as db:
        role = await db.scalar(select(Role).where(Role.name == "Participant"))
        # resolve the new user's id
        from models.user import User

        qid = (
            await db.scalar(select(User.id).where(User.email == "q@example.com"))
        )
        db.add(RoleAssignment(user_id=qid, competition_id=comp, role_id=role.id))
        await db.commit()
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/instance", headers=_auth(token)
    )
    assert resp.status_code == 409
    assert "capacity" in resp.json()["detail"]


# --- reaper ------------------------------------------------------------------


async def test_reaper_expires_ttl_and_emits_event(client):
    comp, chal, dep, uid = await _scaffold(client)
    async with SessionLocal() as db:
        inst = await _insert(
            db,
            comp=comp,
            chal=chal,
            dep=dep,
            uid=uid,
            status="running",
            backend_handle=None,
            expires_at=utcnow() - timedelta(minutes=1),
        )
        instance_id = inst.id

    await reap_instances(SessionLocal)

    async with SessionLocal() as db:
        row = await db.get(ChallengeInstance, instance_id)
    assert row.status == "destroyed"
    assert row.destroyed_at is not None
    assert await _events("challenge.instance_expired")


async def test_reaper_fails_stuck_provisioning(client):
    comp, chal, dep, uid = await _scaffold(client)
    async with SessionLocal() as db:
        inst = await _insert(
            db,
            comp=comp,
            chal=chal,
            dep=dep,
            uid=uid,
            status="requested",
            created_at=utcnow() - timedelta(minutes=10),
        )
        instance_id = inst.id

    await reap_instances(SessionLocal)

    async with SessionLocal() as db:
        row = await db.get(ChallengeInstance, instance_id)
    assert row.status == "failed"
    assert "timed out" in (row.failure_reason or "")
    assert await _events("challenge.instance_provision_failed")


async def test_expiring_retry_emits_expired_for_a_ttl_row(client):
    # A TTL expiry whose first destroy failed is left 'expiring'; the retry must
    # still emit instance_expired (not the default instance_destroyed), so
    # automations keyed on expiry don't miss it.
    comp, chal, dep, uid = await _scaffold(client)
    async with SessionLocal() as db:
        inst = await _insert(
            db,
            comp=comp,
            chal=chal,
            dep=dep,
            uid=uid,
            status="expiring",
            backend_handle=None,
            expires_at=utcnow() - timedelta(minutes=1),
        )
        instance_id = inst.id

    await reap_instances(SessionLocal)

    async with SessionLocal() as db:
        row = await db.get(ChallengeInstance, instance_id)
    assert row.status == "destroyed"
    assert await _events("challenge.instance_expired")


async def test_expiring_retry_emits_destroyed_for_a_manual_row(client):
    # An 'expiring' row still within its TTL was a manual/staff destroy — the
    # retry emits instance_destroyed.
    comp, chal, dep, uid = await _scaffold(client)
    async with SessionLocal() as db:
        inst = await _insert(
            db,
            comp=comp,
            chal=chal,
            dep=dep,
            uid=uid,
            status="expiring",
            backend_handle=None,
            expires_at=utcnow() + timedelta(minutes=30),
        )
        instance_id = inst.id

    await reap_instances(SessionLocal)

    async with SessionLocal() as db:
        row = await db.get(ChallengeInstance, instance_id)
    assert row.status == "destroyed"
    assert await _events("challenge.instance_destroyed")
    assert not await _events("challenge.instance_expired")


async def test_reaper_leaves_fresh_pending_alone(client):
    comp, chal, dep, uid = await _scaffold(client)
    async with SessionLocal() as db:
        inst = await _insert(
            db, comp=comp, chal=chal, dep=dep, uid=uid, status="provisioning"
        )
        instance_id = inst.id

    await reap_instances(SessionLocal)

    async with SessionLocal() as db:
        row = await db.get(ChallengeInstance, instance_id)
    # Created just now — well under the stuck threshold, so untouched.
    assert row.status == "provisioning"


class _NetSweepProv:
    """A provisioner double for the orphan-network sweep: no orphan containers,
    one perpetually-orphaned per-instance network, recording removals."""

    def __init__(self) -> None:
        self.removed: list[str] = []

    async def list(self) -> list[str]:
        return []

    async def list_orphan_networks(self) -> set[str]:
        return {"flagpost-net-ghost"}

    async def remove_network(self, name: str) -> None:
        self.removed.append(name)


async def test_reaper_two_tick_orphan_network_sweep(client, monkeypatch):
    # GHSA-vgrr: a per-instance bridge whose container AutoRemoved after crashing
    # is swept — but only under the same two-tick guard as orphan containers, so
    # a network momentarily empty between its create and its container attaching
    # is never mistaken for an orphan and deleted out from under a live launch.
    import utils.instance_reaper as reaper

    async with SessionLocal() as db:
        db.add(
            InstanceSettings(
                id=INSTANCE_SETTINGS_ID, backend="docker", enabled=True,
                public_host="chal.example",
            )
        )
        await db.commit()

    fake = _NetSweepProv()
    monkeypatch.setattr(svc, "provisioner_from_settings", lambda settings, **kw: fake)
    # Deterministic start regardless of any prior test's orphan state.
    reaper._orphan_seen = set()
    reaper._orphan_networks_seen = set()

    # Tick 1 only *records* the orphan network (seen once) — nothing removed yet.
    await reap_instances(SessionLocal)
    assert fake.removed == []

    # Tick 2: still orphaned on the second consecutive pass ⇒ removed now.
    await reap_instances(SessionLocal)
    assert fake.removed == ["flagpost-net-ghost"]
