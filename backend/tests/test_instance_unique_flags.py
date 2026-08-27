"""Phase 2a of challenge instancing (#266, ADR-0036 §3): unique-per-instance
flags — provision-time render + hash, unique-mode grading, flag-sharing
detection, and authoring validation.

Grading is exercised at the API level by inserting ``running`` instance rows
directly (no Docker), and the provision-time render+hash is exercised through
``provision()`` with a fake provisioner that records the injected spec — proving
the plaintext injected into the container and the hash stored on the row agree.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from db import SessionLocal, utcnow
from models.audit_log import AuditLogEntry
from models.challenge_instancing import ChallengeInstance
from tests.conftest import admin_token
from tests.test_instance_lifecycle import (
    _assign_participant,
    _make_competition,
    _register,
    uid_counter,
)
from utils import instance_service
from utils.flags import hash_static_flag, make_salt
from utils.instance_service import render_flag_template

pytestmark = pytest.mark.asyncio


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _competitor(client, comp) -> tuple[str, str]:
    token, uid = await _register(client, f"uf{uid_counter()}@example.com")
    await _assign_participant(uid, comp)
    return token, uid


async def _make_flagless_challenge(client, comp, token) -> str:
    """A challenge with no static flag — its flag lives per-instance."""
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "instanced pwn", "points": 100},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _unique_body(**over) -> dict:
    body = {
        "backend": "docker",
        "image_ref": "example/chal:latest",
        "exposure": "tcp",
        "ports": [1337],
        "flag_mode": "unique_per_instance",
        "flag_template": "flag{pwned-<random>}",
        "per_subject_cap": 2,
    }
    body.update(over)
    return body


async def _put_deployment(client, comp, chal, token, **over):
    return await client.put(
        f"/api/competitions/{comp}/challenges/{chal}/deployment",
        json=_unique_body(**over),
        headers=_auth(token),
    )


async def _published_unique_challenge(client, comp, admin, **over) -> tuple[str, dict]:
    """Flagless challenge + a valid unique-mode deployment, published so a
    competitor can submit against it (publish now accepts flagless unique-mode
    challenges — the deployment supplies the flag)."""
    chal = await _make_flagless_challenge(client, comp, admin)
    dep = (await _put_deployment(client, comp, chal, admin, **over)).json()
    pub = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
    )
    assert pub.status_code == 200, pub.text
    return chal, dep


async def _running_instance(
    *, comp, chal, deployment_id, user_id, plaintext, team_id=None, status="running"
) -> str:
    """Insert an instance row holding the salted hash of ``plaintext`` (the same
    at-rest shape the provisioner writes). ``plaintext=None`` leaves the hash
    NULL — a not-yet-provisioned instance."""
    salt = hash = None
    if plaintext is not None:
        salt = make_salt()
        hash = hash_static_flag(plaintext, salt, case_insensitive=False)
    async with SessionLocal() as db:
        inst = ChallengeInstance(
            competition_id=comp,
            challenge_id=chal,
            deployment_id=deployment_id,
            user_id=user_id,
            team_id=team_id,
            status=status,
            flag_salt=salt,
            flag_hash=hash,
            started_at=utcnow(),
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(inst)
        await db.commit()
        await db.refresh(inst)
        return inst.id


async def _submit(client, comp, chal, token, flag) -> tuple[int, dict]:
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": flag},
        headers=_auth(token),
    )
    return resp.status_code, (resp.json() if resp.content else {})


async def _events(name: str):
    async with SessionLocal() as db:
        return (
            (await db.execute(select(AuditLogEntry).where(AuditLogEntry.event_name == name)))
            .scalars()
            .all()
        )


# --- template rendering ------------------------------------------------------


async def test_render_flag_template_substitutes_and_is_unique():
    a = render_flag_template("flag{pwned-<random>}")
    b = render_flag_template("flag{pwned-<random>}")
    assert a.startswith("flag{pwned-") and a.endswith("}")
    assert "<random>" not in a
    assert a != b  # a fresh token each render — every instance differs


async def test_render_flag_template_fills_every_placeholder():
    out = render_flag_template("<random>-<random>")
    left, right = out.split("-")
    # One token per render, substituted everywhere — both halves resolved.
    assert "<random>" not in out and left == right and left


# --- provision: render -> inject -> hash-store -------------------------------


class _FakeProvisioner:
    """Records the spec so the test can prove the injected plaintext hashes to
    what got stored on the row."""

    def __init__(self):
        self.spec = None

    async def create(self, spec):
        self.spec = spec
        return "fake-handle"

    async def endpoints(self, handle):
        return [{"kind": "tcp", "host": "127.0.0.1", "port": 40000}]


async def _requested_instance(comp, chal, deployment_id, user_id) -> str:
    async with SessionLocal() as db:
        inst = ChallengeInstance(
            competition_id=comp,
            challenge_id=chal,
            deployment_id=deployment_id,
            user_id=user_id,
            status="requested",
            endpoints=[],
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(inst)
        await db.commit()
        await db.refresh(inst)
        return inst.id


async def test_provision_stores_hash_of_the_injected_unique_flag(client, monkeypatch):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal, dep = await _published_unique_challenge(client, comp, admin)
    _, uid = await _competitor(client, comp)
    inst_id = await _requested_instance(comp, chal, dep["id"], uid)

    fake = _FakeProvisioner()
    monkeypatch.setattr(
        instance_service, "provisioner_for", lambda *a, **k: fake
    )
    await instance_service.provision(SessionLocal, inst_id)

    async with SessionLocal() as db:
        row = await db.get(ChallengeInstance, inst_id)
    assert row.status == "running"
    # The flag was injected into the container...
    assert fake.spec.flag_plaintext is not None
    assert fake.spec.flag_plaintext.startswith("flag{pwned-")
    # ...and only its hash was stored — and the two agree.
    assert row.flag_hash is not None and row.flag_salt is not None
    assert (
        hash_static_flag(fake.spec.flag_plaintext, row.flag_salt, case_insensitive=False)
        == row.flag_hash
    )


async def test_provision_static_mode_injects_and_stores_no_flag(client, monkeypatch):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_flagless_challenge(client, comp, admin)
    dep = (
        await _put_deployment(
            client, comp, chal, admin, flag_mode="static", flag_template=None
        )
    ).json()
    _, uid = await _competitor(client, comp)
    inst_id = await _requested_instance(comp, chal, dep["id"], uid)

    fake = _FakeProvisioner()
    monkeypatch.setattr(instance_service, "provisioner_for", lambda *a, **k: fake)
    await instance_service.provision(SessionLocal, inst_id)

    async with SessionLocal() as db:
        row = await db.get(ChallengeInstance, inst_id)
    assert row.status == "running"
    assert fake.spec.flag_plaintext is None
    assert row.flag_hash is None and row.flag_salt is None


# --- unique-mode grading -----------------------------------------------------


async def test_unique_flag_grades_correct_against_own_instance(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal, dep = await _published_unique_challenge(client, comp, admin)
    token, uid = await _competitor(client, comp)
    flag = "flag{pwned-abc123}"
    await _running_instance(comp=comp, chal=chal, deployment_id=dep["id"], user_id=uid, plaintext=flag)

    code, ok = await _submit(client, comp, chal, token, flag)
    assert code == 200 and ok["correct"] is True and ok["points_awarded"] == 100
    code, wrong = await _submit(client, comp, chal, token, "flag{pwned-nope}")
    assert code == 200 and wrong["correct"] is False


async def test_no_active_instance_is_wrong_not_a_400(client):
    # A unique-mode challenge carries no static flag, so the has_flag gate must be
    # bypassed — with no instance the submission grades wrong, it does not 400.
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal, _dep = await _published_unique_challenge(client, comp, admin)
    token, _ = await _competitor(client, comp)

    code, body = await _submit(client, comp, chal, token, "flag{pwned-guess}")
    assert code == 200 and body["correct"] is False


async def test_grades_correct_against_any_of_several_own_instances(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal, dep = await _published_unique_challenge(client, comp, admin)
    token, uid = await _competitor(client, comp)
    await _running_instance(comp=comp, chal=chal, deployment_id=dep["id"], user_id=uid, plaintext="flag{pwned-one}")
    await _running_instance(comp=comp, chal=chal, deployment_id=dep["id"], user_id=uid, plaintext="flag{pwned-two}")

    code, body = await _submit(client, comp, chal, token, "flag{pwned-two}")
    assert code == 200 and body["correct"] is True


async def test_provisioning_instance_without_hash_is_not_gradeable(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal, dep = await _published_unique_challenge(client, comp, admin)
    token, uid = await _competitor(client, comp)
    # An instance still provisioning: active, but no flag hash yet.
    await _running_instance(
        comp=comp, chal=chal, deployment_id=dep["id"], user_id=uid,
        plaintext=None, status="provisioning",
    )
    # A separate running instance with a real flag proves the NULL-hash row is
    # skipped rather than crashing the compare.
    await _running_instance(comp=comp, chal=chal, deployment_id=dep["id"], user_id=uid, plaintext="flag{pwned-live}")

    code, body = await _submit(client, comp, chal, token, "flag{pwned-live}")
    assert code == 200 and body["correct"] is True


# --- flag-sharing detection --------------------------------------------------


async def test_submitting_another_subjects_flag_is_detected(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal, dep = await _published_unique_challenge(client, comp, admin)
    a_token, a_uid = await _competitor(client, comp)
    b_token, b_uid = await _competitor(client, comp)
    await _running_instance(comp=comp, chal=chal, deployment_id=dep["id"], user_id=a_uid, plaintext="flag{pwned-aaa}")
    await _running_instance(comp=comp, chal=chal, deployment_id=dep["id"], user_id=b_uid, plaintext="flag{pwned-bbb}")

    # B submits A's flag: wrong for B, and provable sharing.
    code, body = await _submit(client, comp, chal, b_token, "flag{pwned-aaa}")
    assert code == 200 and body["correct"] is False
    events = await _events("challenge.flag_shared_detected")
    assert len(events) == 1
    payload = events[0].payload
    assert payload["user_id"] == b_uid
    assert payload["matched_user_id"] == a_uid


async def test_ordinary_wrong_guess_is_not_flagged_as_sharing(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal, dep = await _published_unique_challenge(client, comp, admin)
    a_token, a_uid = await _competitor(client, comp)
    b_token, b_uid = await _competitor(client, comp)
    await _running_instance(comp=comp, chal=chal, deployment_id=dep["id"], user_id=a_uid, plaintext="flag{pwned-aaa}")
    await _running_instance(comp=comp, chal=chal, deployment_id=dep["id"], user_id=b_uid, plaintext="flag{pwned-bbb}")

    code, body = await _submit(client, comp, chal, b_token, "flag{totally-made-up}")
    assert code == 200 and body["correct"] is False
    assert await _events("challenge.flag_shared_detected") == []


# --- authoring validation ----------------------------------------------------


async def test_unique_template_must_contain_the_random_placeholder(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_flagless_challenge(client, comp, admin)
    resp = await _put_deployment(
        client, comp, chal, admin, flag_template="flag{fixed}"
    )
    assert resp.status_code == 400
    assert "<random>" in resp.json()["detail"]


async def test_unique_flags_rejected_on_shared_static_backend(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_flagless_challenge(client, comp, admin)
    resp = await _put_deployment(
        client,
        comp,
        chal,
        admin,
        backend="shared-static",
        image_ref=None,
        manifest={"endpoints": [{"kind": "tcp", "host": "h", "port": 1}]},
    )
    assert resp.status_code == 400
    assert "shared-static" in resp.json()["detail"]


async def test_valid_unique_deployment_is_accepted(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal = await _make_flagless_challenge(client, comp, admin)
    resp = await _put_deployment(client, comp, chal, admin)
    assert resp.status_code == 200, resp.text
    assert resp.json()["flag_mode"] == "unique_per_instance"


async def test_unique_deployment_rejected_when_challenge_has_its_own_flag(client):
    # A challenge can't hold both a static flag and a unique-per-instance flag —
    # grading would silently ignore the authored one. Refuse the combination.
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "has its own flag", "points": 100, "flag": "flag{static}"},
        headers=_auth(admin),
    )
    chal = resp.json()["id"]
    r = await _put_deployment(client, comp, chal, admin)  # unique mode
    assert r.status_code == 400
    assert "own flag" in r.json()["detail"]


# --- flag-sharing false-positive guard (team switch) -------------------------


async def _team(comp, name) -> str:
    from models.team import Team

    async with SessionLocal() as db:
        team = Team(competition_id=comp, name=name, invite_code=f"c-{name}-{uid_counter()}")
        db.add(team)
        await db.commit()
        await db.refresh(team)
        return team.id


async def test_sharing_scan_excludes_the_submitters_own_instance(client):
    # A competitor who switched teams still owns a live instance credited to the
    # OLD team (subject-key mismatch). Submitting its flag must not accuse them of
    # sharing with themselves — the scan excludes their own instances by user_id.
    from utils.instance_grading import grade_unique
    from utils.scoring import Subject

    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    chal, dep = await _published_unique_challenge(client, comp, admin)
    _, u = await _competitor(client, comp)
    team_a = await _team(comp, "alpha")
    await _running_instance(
        comp=comp, chal=chal, deployment_id=dep["id"], user_id=u,
        team_id=team_a, plaintext="flag{mine}",
    )

    async with SessionLocal() as db:
        # U now grades as a different subject ("beta") but is the same human.
        own = await grade_unique(
            db, comp, chal, Subject(kind="team", id="beta", team_id="beta"),
            "flag{mine}", user_id=u,
        )
        assert own.correct is False and own.shared_with is None
        # Control: a *different* human submitting that flag is real sharing.
        other = await grade_unique(
            db, comp, chal, Subject(kind="team", id="beta", team_id="beta"),
            "flag{mine}", user_id="another-human",
        )
        assert other.correct is False and other.shared_with is not None
        assert other.shared_with.user_id == u
