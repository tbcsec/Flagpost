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
        docker_eps = await svc._plan_endpoints(db, settings, docker_dep)
        static_eps = await svc._plan_endpoints(db, settings, static_dep)
    # One host port per declared container port, from the range, on the public host.
    assert [e["port"] for e in docker_eps] == [40000, 40001]
    assert all(e["host"] == "chal.example" for e in docker_eps)
    # Shared-static gets its endpoints from its manifest at provision time, not here.
    assert static_eps == []


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
