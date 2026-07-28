"""Rules / code-of-conduct acceptance (issue #57).

The gate covers all four membership-granting paths: public self-serve join,
invite-code join, team join (including the approval-required request branch),
and team create. Acceptance is recorded per user per competition, emits
``competition.rules_accepted`` (audit-visible), and the effective document is
the per-competition override when set, else the site-wide text. Staff
(edit_competition holders) are exempt; display-only rules never block.
"""

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from models.rules_acceptance import RulesAcceptance
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _doc(text: str) -> dict:
    """A minimal ProseMirror doc containing ``text``."""
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


# A visually-empty TipTap doc: nodes but no text. Must not gate anything.
EMPTY_DOC = {"type": "doc", "content": [{"type": "paragraph"}]}


async def _register(client, email, name=None) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": name or email.split("@")[0],
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _make_competition(
    client, admin, *, visibility="public", mode="individual", **extra
) -> dict:
    resp = await client.post(
        "/api/competitions",
        json={
            "name": extra.pop("name", "CTF"),
            "participation_mode": mode,
            "visibility": visibility,
            **extra,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _set_global_rules(client, admin, text="Be excellent", **extra):
    resp = await client.put(
        "/api/site-settings/rules",
        json={"rules_text": _doc(text), "rules_display_only": False, **extra},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _acceptance_rows(competition_id: str) -> list:
    async with SessionLocal() as session:
        return list(
            (
                await session.execute(
                    select(RulesAcceptance).where(
                        RulesAcceptance.competition_id == competition_id
                    )
                )
            ).scalars()
        )


async def _audit_events(name: str) -> list:
    async with SessionLocal() as session:
        return list(
            (
                await session.execute(
                    select(AuditLogEntry).where(AuditLogEntry.event_name == name)
                )
            ).scalars()
        )


# --- the four join paths ------------------------------------------------------


async def test_public_join_blocked_until_accepted(client):
    admin = await admin_token(client)
    await _set_global_rules(client, admin)
    comp = await _make_competition(client, admin)
    token, user_id = await _register(client, "gated@example.com")

    resp = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["code"] == "rules_not_accepted"
    assert detail["competition_id"] == comp["id"]
    # The document travels with the rejection (the code-join flow renders it).
    assert detail["rules"]["type"] == "doc"

    accept = await client.post(
        f"/api/competitions/{comp['id']}/rules/accept", headers=_auth(token)
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["accepted"] is True

    resp = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text

    rows = await _acceptance_rows(comp["id"])
    assert len(rows) == 1 and rows[0].user_id == user_id


async def test_code_join_blocked_then_accept_with_join(client):
    admin = await admin_token(client)
    await _set_global_rules(client, admin)
    comp = await _make_competition(client, admin, visibility="private")
    token, user_id = await _register(client, "coded@example.com")

    resp = await client.post(
        "/api/competitions/join",
        json={"invite_code": comp["invite_code"]},
        headers=_auth(token),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "rules_not_accepted"

    # Retry with accept_rules — acceptance + join in one request.
    resp = await client.post(
        "/api/competitions/join",
        json={"invite_code": comp["invite_code"], "accept_rules": True},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    rows = await _acceptance_rows(comp["id"])
    assert len(rows) == 1 and rows[0].user_id == user_id


async def test_team_join_and_request_blocked(client):
    admin = await admin_token(client)
    await _set_global_rules(client, admin)
    comp = await _make_competition(client, admin, mode="team")

    # A team to join: created by a member who accepted first.
    captain, _ = await _register(client, "captain@example.com")
    await client.post(
        f"/api/competitions/{comp['id']}/rules/accept", headers=_auth(captain)
    )
    open_team = await client.post(
        f"/api/competitions/{comp['id']}/teams",
        json={"name": "Open"},
        headers=_auth(captain),
    )
    assert open_team.status_code == 201, open_team.text

    approval_captain, _ = await _register(client, "approver@example.com")
    await client.post(
        f"/api/competitions/{comp['id']}/rules/accept",
        headers=_auth(approval_captain),
    )
    gated_team = await client.post(
        f"/api/competitions/{comp['id']}/teams",
        json={"name": "Gated", "approval_required": True},
        headers=_auth(approval_captain),
    )
    assert gated_team.status_code == 201, gated_team.text

    joiner, _ = await _register(client, "joiner@example.com")
    # Plain team join blocked.
    resp = await client.post(
        f"/api/competitions/{comp['id']}/teams/join",
        json={"invite_code": open_team.json()["invite_code"]},
        headers=_auth(joiner),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "rules_not_accepted"
    # Filing a join *request* is equally blocked (the join moment is filing).
    resp = await client.post(
        f"/api/competitions/{comp['id']}/teams/join",
        json={"invite_code": gated_team.json()["invite_code"]},
        headers=_auth(joiner),
    )
    assert resp.status_code == 403

    await client.post(
        f"/api/competitions/{comp['id']}/rules/accept", headers=_auth(joiner)
    )
    resp = await client.post(
        f"/api/competitions/{comp['id']}/teams/join",
        json={"invite_code": gated_team.json()["invite_code"]},
        headers=_auth(joiner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["pending"] is True


async def test_create_team_blocked(client):
    """The fourth call site (owner-confirmed): creating a team grants the
    Participant role, so it must be gated like joining one."""
    admin = await admin_token(client)
    await _set_global_rules(client, admin)
    comp = await _make_competition(client, admin, mode="team")
    token, _ = await _register(client, "founder@example.com")

    resp = await client.post(
        f"/api/competitions/{comp['id']}/teams",
        json={"name": "Bypass FC"},
        headers=_auth(token),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "rules_not_accepted"

    await client.post(
        f"/api/competitions/{comp['id']}/rules/accept", headers=_auth(token)
    )
    resp = await client.post(
        f"/api/competitions/{comp['id']}/teams",
        json={"name": "Bypass FC"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text


# --- acceptance semantics -----------------------------------------------------


async def test_accept_is_idempotent_and_audited(client):
    admin = await admin_token(client)
    await _set_global_rules(client, admin)
    comp = await _make_competition(client, admin)
    token, user_id = await _register(client, "twice@example.com")

    for _ in range(2):
        resp = await client.post(
            f"/api/competitions/{comp['id']}/rules/accept", headers=_auth(token)
        )
        assert resp.status_code == 200, resp.text

    rows = await _acceptance_rows(comp["id"])
    assert len(rows) == 1
    events = await _audit_events("competition.rules_accepted")
    assert len(events) == 1
    assert events[0].payload["user_id"] == user_id
    assert events[0].payload["competition_id"] == comp["id"]


async def test_accept_without_rules_is_rejected(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    token, _ = await _register(client, "eager@example.com")
    resp = await client.post(
        f"/api/competitions/{comp['id']}/rules/accept", headers=_auth(token)
    )
    assert resp.status_code == 400


async def test_no_rules_configured_means_no_gate(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    token, _ = await _register(client, "free@example.com")

    rules = await client.get(
        f"/api/competitions/{comp['id']}/rules", headers=_auth(token)
    )
    assert rules.status_code == 200
    assert rules.json()["rules"] is None
    assert rules.json()["required"] is False

    resp = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text


async def test_visually_empty_doc_does_not_gate(client):
    admin = await admin_token(client)
    resp = await client.put(
        "/api/site-settings/rules",
        json={"rules_text": EMPTY_DOC, "rules_display_only": False},
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    comp = await _make_competition(client, admin)
    token, _ = await _register(client, "blank@example.com")
    resp = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text


# --- override vs global, display-only, staff exemption -------------------------


async def test_override_supersedes_global(client):
    admin = await admin_token(client)
    await _set_global_rules(client, admin, text="Global rules")
    comp = await _make_competition(client, admin)
    patch = await client.patch(
        f"/api/competitions/{comp['id']}",
        json={"rules_override": _doc("House rules")},
        headers=_auth(admin),
    )
    assert patch.status_code == 200, patch.text

    token, _ = await _register(client, "reader@example.com")
    rules = await client.get(
        f"/api/competitions/{comp['id']}/rules", headers=_auth(token)
    )
    text = rules.json()["rules"]["content"][0]["content"][0]["text"]
    assert text == "House rules"


async def test_display_only_never_blocks(client):
    admin = await admin_token(client)
    await _set_global_rules(client, admin, rules_display_only=True)
    comp = await _make_competition(client, admin)
    token, _ = await _register(client, "casual@example.com")

    rules = await client.get(
        f"/api/competitions/{comp['id']}/rules", headers=_auth(token)
    )
    assert rules.json()["display_only"] is True
    assert rules.json()["required"] is False

    resp = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert await _acceptance_rows(comp["id"]) == []


async def test_staff_exempt_from_gate(client):
    admin = await admin_token(client)
    await _set_global_rules(client, admin)
    comp = await _make_competition(client, admin)

    # The administrator holds edit_competition globally — exempt.
    rules = await client.get(
        f"/api/competitions/{comp['id']}/rules", headers=_auth(admin)
    )
    assert rules.json()["exempt"] is True
    assert rules.json()["required"] is False
    resp = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(admin)
    )
    assert resp.status_code == 200, resp.text
    assert await _acceptance_rows(comp["id"]) == []


# --- re-acceptance on override change ------------------------------------------


async def test_override_change_resets_acceptances(client):
    admin = await admin_token(client)
    await _set_global_rules(client, admin)
    comp = await _make_competition(client, admin)
    token, _ = await _register(client, "member@example.com")

    await client.post(
        f"/api/competitions/{comp['id']}/rules/accept", headers=_auth(token)
    )
    await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert len(await _acceptance_rows(comp["id"])) == 1

    # Adding an override supersedes what was agreed to — rows are reset and the
    # (now member) user must re-accept.
    patch = await client.patch(
        f"/api/competitions/{comp['id']}",
        json={"rules_override": _doc("New house rules")},
        headers=_auth(admin),
    )
    assert patch.status_code == 200, patch.text
    assert await _acceptance_rows(comp["id"]) == []

    rules = await client.get(
        f"/api/competitions/{comp['id']}/rules", headers=_auth(token)
    )
    assert rules.json()["accepted"] is False
    assert rules.json()["required"] is True  # member + mandatory + unaccepted

    # An unrelated PATCH (or re-saving the same override) does NOT reset.
    await client.post(
        f"/api/competitions/{comp['id']}/rules/accept", headers=_auth(token)
    )
    await client.patch(
        f"/api/competitions/{comp['id']}",
        json={"description": "tweak", "rules_override": _doc("New house rules")},
        headers=_auth(admin),
    )
    assert len(await _acceptance_rows(comp["id"])) == 1


async def test_clearing_override_does_not_reset(client):
    admin = await admin_token(client)
    await _set_global_rules(client, admin)
    comp = await _make_competition(client, admin)
    await client.patch(
        f"/api/competitions/{comp['id']}",
        json={"rules_override": _doc("House rules")},
        headers=_auth(admin),
    )
    token, _ = await _register(client, "settled@example.com")
    await client.post(
        f"/api/competitions/{comp['id']}/rules/accept", headers=_auth(token)
    )

    await client.patch(
        f"/api/competitions/{comp['id']}",
        json={"rules_override": None},
        headers=_auth(admin),
    )
    # Back to the global document; existing acceptances stand (owner decision:
    # only adding/changing an override forces re-acceptance).
    assert len(await _acceptance_rows(comp["id"])) == 1


# --- authoring + visibility -----------------------------------------------------


async def test_rules_settings_require_permission(client):
    token, _ = await _register(client, "pleb@example.com")
    resp = await client.put(
        "/api/site-settings/rules",
        json={"rules_text": _doc("mine now"), "rules_display_only": False},
        headers=_auth(token),
    )
    assert resp.status_code == 403
    resp = await client.get("/api/site-settings/rules", headers=_auth(token))
    assert resp.status_code == 403


async def test_rules_hidden_for_invisible_competition(client):
    admin = await admin_token(client)
    await _set_global_rules(client, admin)
    comp = await _make_competition(client, admin, visibility="private")
    token, _ = await _register(client, "outsider@example.com")

    # A private competition's rules (and existence) are undisclosed to
    # non-members — the accept route matches.
    resp = await client.get(
        f"/api/competitions/{comp['id']}/rules", headers=_auth(token)
    )
    assert resp.status_code == 404
    resp = await client.post(
        f"/api/competitions/{comp['id']}/rules/accept", headers=_auth(token)
    )
    assert resp.status_code == 404
