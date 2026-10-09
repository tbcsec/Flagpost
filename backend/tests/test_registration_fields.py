"""Per-competition custom registration fields (#350).

The invariants: an organiser defines fields; competitors/teams fill them at
entry with required ones enforced; values are stored per subject and editable by
the subject; they reach the operator via the CSV export and never a public view;
and only an organiser can author the field set.
"""

import pytest

from tests.conftest import admin_token
from utils.registration_fields import validate_values


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _competition(client, mode: str = "individual") -> str:
    admin = await admin_token(client)
    body = {"name": "CTF", "participation_mode": mode, "visibility": "public"}
    resp = await client.post("/api/competitions", json=body, headers=_auth(admin))
    return resp.json()["id"]


async def _register(client, name: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register", json={"display_name": name, "password": "password123"}
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _define(client, comp: str, fields: list[dict], token: str):
    return await client.put(
        f"/api/competitions/{comp}/registration-fields",
        json={"fields": fields},
        headers=_auth(token),
    )


_TSHIRT = {
    "key": "tshirt",
    "label": "T-shirt size",
    "field_type": "select",
    "options": ["S", "M", "L"],
    "required": True,
    "position": 0,
}
_DIET = {"key": "diet", "label": "Dietary needs", "field_type": "text", "position": 1}


# --- definitions --------------------------------------------------------------


async def test_organiser_defines_fields_and_anyone_authed_reads_them(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    resp = await _define(client, comp, [_DIET, _TSHIRT], admin)
    assert resp.status_code == 200, resp.text

    # Any authenticated (non-member) user can read the definitions to render the
    # join form; they come back in form order (position).
    outsider, _ = await _register(client, "outsider")
    listing = (
        await client.get(
            f"/api/competitions/{comp}/registration-fields", headers=_auth(outsider)
        )
    ).json()
    assert [f["key"] for f in listing] == ["tshirt", "diet"]
    assert listing[0]["options"] == ["S", "M", "L"]


async def test_private_competition_fields_hidden_from_non_members(client):
    # A private competition's field labels (and its existence) must not leak to
    # someone who can't see it — get_visible_competition, not just "it exists".
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "Secret", "participation_mode": "individual", "visibility": "private"},
            headers=_auth(admin),
        )
    ).json()
    await _define(client, comp["id"], [_TSHIRT], admin)

    outsider, _ = await _register(client, "outsider")
    resp = await client.get(
        f"/api/competitions/{comp['id']}/registration-fields", headers=_auth(outsider)
    )
    assert resp.status_code == 404  # not disclosed
    # The organiser still reads them (they can see the competition).
    assert (
        await client.get(
            f"/api/competitions/{comp['id']}/registration-fields", headers=_auth(admin)
        )
    ).status_code == 200


async def test_code_join_defers_required_fields_it_cannot_pre_collect(client):
    # A private competition is undisclosed until the invite code resolves, so its
    # fields can't render a pre-join form — the code join must not hard-block on a
    # required field; the competitor fills it afterwards via /me.
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "Priv", "participation_mode": "individual", "visibility": "private"},
            headers=_auth(admin),
        )
    ).json()
    await _define(client, comp["id"], [_TSHIRT], admin)

    token, _ = await _register(client, "coder")
    joined = await client.post(
        "/api/competitions/join",
        json={"invite_code": comp["invite_code"], "field_values": {}},
        headers=_auth(token),
    )
    assert joined.status_code == 200  # deferred, not a 422 wall
    # And they can now fill it (required enforced on their own save).
    saved = await client.put(
        f"/api/competitions/{comp['id']}/registration-fields/me",
        json={"values": {"tshirt": "M"}},
        headers=_auth(token),
    )
    assert saved.status_code == 200


async def test_only_an_organiser_can_author_fields(client):
    comp = await _competition(client)
    player, _ = await _register(client, "player")
    resp = await _define(client, comp, [_DIET], player)
    assert resp.status_code == 403


async def test_a_select_field_needs_options(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    bad = {"key": "x", "label": "X", "field_type": "select", "options": []}
    resp = await _define(client, comp, [bad], admin)
    assert resp.status_code == 422


# --- collection at individual join -------------------------------------------


async def test_individual_join_enforces_required_then_stores_and_edits(client):
    comp = await _competition(client, "individual")
    admin = await admin_token(client)
    await _define(client, comp, [_TSHIRT, _DIET], admin)
    token, uid = await _register(client, "ada")

    # A required field missing → 422, and the user is NOT joined.
    missing = await client.post(
        f"/api/competitions/{comp}/join", json={"field_values": {}}, headers=_auth(token)
    )
    assert missing.status_code == 422
    fields = await client.get(
        f"/api/competitions/{comp}/registration-fields/me", headers=_auth(token)
    )
    assert fields.status_code == 403  # not a member yet (no challenge_view)

    # With the required field it joins; a bad select choice is rejected.
    bad = await client.post(
        f"/api/competitions/{comp}/join",
        json={"field_values": {"tshirt": "XXL"}},
        headers=_auth(token),
    )
    assert bad.status_code == 422

    ok = await client.post(
        f"/api/competitions/{comp}/join",
        json={"field_values": {"tshirt": "M", "diet": "none"}},
        headers=_auth(token),
    )
    assert ok.status_code == 200

    mine = (
        await client.get(
            f"/api/competitions/{comp}/registration-fields/me", headers=_auth(token)
        )
    ).json()
    assert mine["values"] == {"tshirt": "M", "diet": "none"}

    # The subject edits their own answers later.
    edited = await client.put(
        f"/api/competitions/{comp}/registration-fields/me",
        json={"values": {"tshirt": "L", "diet": "vegan"}},
        headers=_auth(token),
    )
    assert edited.status_code == 200 and edited.json()["values"]["tshirt"] == "L"


async def test_re_join_does_not_re_demand_fields(client):
    comp = await _competition(client, "individual")
    admin = await admin_token(client)
    token, _ = await _register(client, "bo")
    # Join before any fields exist.
    assert (await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))).status_code == 200
    # Organiser adds a required field afterwards.
    await _define(client, comp, [_TSHIRT], admin)
    # An idempotent re-join must not now 422 on the un-answered required field.
    again = await client.post(
        f"/api/competitions/{comp}/join", json={"field_values": {}}, headers=_auth(token)
    )
    assert again.status_code == 200


# --- collection at team creation ---------------------------------------------


async def test_team_create_stores_team_values_and_captain_edits(client):
    comp = await _competition(client, "team")
    admin = await admin_token(client)
    await _define(client, comp, [_TSHIRT], admin)
    cap, _ = await _register(client, "captain")

    missing = await client.post(
        f"/api/competitions/{comp}/teams",
        json={"name": "Alpha", "field_values": {}},
        headers=_auth(cap),
    )
    assert missing.status_code == 422  # required enforced, no orphan team

    created = await client.post(
        f"/api/competitions/{comp}/teams",
        json={"name": "Alpha", "field_values": {"tshirt": "S"}},
        headers=_auth(cap),
    )
    assert created.status_code == 201

    # Individual /me is meaningless in team mode.
    assert (
        await client.get(
            f"/api/competitions/{comp}/registration-fields/me", headers=_auth(cap)
        )
    ).status_code == 400

    # Captain edits the team's answers via the team.
    edited = await client.patch(
        f"/api/competitions/{comp}/teams/me",
        json={"field_values": {"tshirt": "L"}},
        headers=_auth(cap),
    )
    assert edited.status_code == 200


# --- export -------------------------------------------------------------------


async def test_export_csv_is_organiser_only_and_carries_values(client):
    comp = await _competition(client, "individual")
    admin = await admin_token(client)
    await _define(client, comp, [_TSHIRT, _DIET], admin)
    token, _ = await _register(client, "ada")
    await client.post(
        f"/api/competitions/{comp}/join",
        json={"field_values": {"tshirt": "M", "diet": "none"}},
        headers=_auth(token),
    )

    forbidden = await client.get(
        f"/api/competitions/{comp}/registration-fields/export", headers=_auth(token)
    )
    assert forbidden.status_code == 403  # a competitor can't pull the roster

    export = await client.get(
        f"/api/competitions/{comp}/registration-fields/export", headers=_auth(admin)
    )
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    body = export.text
    assert "T-shirt size" in body and "Dietary needs" in body
    assert "ada" in body and "M" in body


async def test_export_neutralises_csv_formula_injection(client):
    """GHSA-352q: a competitor-controlled free-text answer that a spreadsheet
    would evaluate as a formula is prefixed with an apostrophe in the export, so
    opening the roster in Excel/LibreOffice can't execute it."""
    import csv as _csv

    comp = await _competition(client, "individual")
    admin = await admin_token(client)
    await _define(client, comp, [_DIET], admin)
    token, _ = await _register(client, "mallory")
    await client.post(
        f"/api/competitions/{comp}/join",
        json={"field_values": {"diet": "=1+1"}},
        headers=_auth(token),
    )

    export = await client.get(
        f"/api/competitions/{comp}/registration-fields/export", headers=_auth(admin)
    )
    assert export.status_code == 200
    body = export.text
    assert "'=1+1" in body  # neutralised
    # No cell in the file begins with a bare formula lead.
    rows = list(_csv.reader(body.splitlines()))
    assert not any(
        cell[:1] in "=+-@" for row in rows for cell in row if cell
    )


# --- validator unit -----------------------------------------------------------


class _F:
    def __init__(self, key, field_type="text", required=False, options=None):
        self.key = key
        self.label = key
        self.field_type = field_type
        self.required = required
        self.options = options


def test_validate_values_coerces_and_bounds():
    fields = [
        _F("consent", "checkbox", required=True),
        _F("size", "select", options=["S", "M"]),
        _F("note", "text"),
    ]
    cleaned = validate_values(
        fields,
        {"consent": True, "size": "M", "note": "  hi  ", "junk": "x"},
    )
    assert cleaned == {"consent": True, "size": "M", "note": "hi"}  # junk dropped, trimmed


def test_validate_values_enforces_required_and_choices():
    from fastapi import HTTPException

    fields = [_F("consent", "checkbox", required=True), _F("size", "select", options=["S"])]
    with pytest.raises(HTTPException):
        validate_values(fields, {"size": "S"})  # consent required, missing
    with pytest.raises(HTTPException):
        validate_values(fields, {"consent": True, "size": "XL"})  # bad choice
    # Required can be relaxed for non-entry contexts.
    assert validate_values(fields, {"size": "S"}, require_required=False) == {"size": "S"}


def test_validate_values_checkbox_string_false_is_false():
    # A hostile client sending the *string* "false" must not become True.
    fields = [_F("consent", "checkbox")]
    assert validate_values(fields, {"consent": "false"}) == {"consent": False}
    assert validate_values(fields, {"consent": "true"}) == {"consent": True}
    assert validate_values(fields, {"consent": True}) == {"consent": True}


def test_validate_values_rejects_an_overlong_answer():
    from fastapi import HTTPException

    fields = [_F("bio", "textarea")]
    with pytest.raises(HTTPException):
        validate_values(fields, {"bio": "x" * 5000})
