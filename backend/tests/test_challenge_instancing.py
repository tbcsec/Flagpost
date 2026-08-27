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
