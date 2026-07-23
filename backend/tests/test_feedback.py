"""Feedback / surveys (Tier 3 Phase 4, ROADMAP #22): survey + question CRUD
RBAC, question types, the one-response-per-user invariant, module gating, the
survey.submitted event (and that it triggers an automation rule), results
aggregation, and CSV export."""

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from tests.conftest import admin_token

import main  # noqa: E402


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def _competition(client) -> str:
    admin = await admin_token(client)
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _participant(client, comp, email) -> str:
    token = await _register(client, email)
    resp = await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return token


async def _survey(client, comp, admin, *, title="Post-event") -> str:
    resp = await client.post(
        f"/api/competitions/{comp}/surveys",
        json={"title": title, "description": "How did we do?"},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_question(client, comp, admin, survey, **body) -> str:
    resp = await client.post(
        f"/api/competitions/{comp}/surveys/{survey}/questions",
        json=body,
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _open(client, comp, admin, survey) -> None:
    current = (
        await client.get(f"/api/competitions/{comp}/surveys/{survey}", headers=_auth(admin))
    ).json()
    resp = await client.put(
        f"/api/competitions/{comp}/surveys/{survey}",
        json={"title": current["title"], "description": current["description"], "is_open": True},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text


async def _audit_names(event_prefix: str) -> list[str]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(AuditLogEntry.event_name).where(
                        AuditLogEntry.event_name.like(f"{event_prefix}%")
                    )
                )
            ).all()
        )


# --- RBAC + question types ----------------------------------------------------


async def test_opening_a_survey_emits_survey_opened_once(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    survey = await _survey(client, comp, admin)

    await _open(client, comp, admin, survey)
    assert (await _audit_names("survey.opened")) == ["survey.opened"]

    # A no-op re-save of an already-open survey must NOT re-emit (closed→open
    # edge only).
    await _open(client, comp, admin, survey)
    assert (await _audit_names("survey.opened")) == ["survey.opened"]


async def test_only_staff_can_build_surveys(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    resp = await client.post(
        f"/api/competitions/{comp}/surveys",
        json={"title": "x"},
        headers=_auth(ada),
    )
    assert resp.status_code == 403


async def test_all_question_types_and_validation(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    survey = await _survey(client, comp, admin)
    for qtype in ("rating_1_10", "rating_1_5", "short_text", "long_text"):
        await _add_question(client, comp, admin, survey, prompt=f"q {qtype}", type=qtype)
    mc = await _add_question(
        client, comp, admin, survey,
        prompt="Favourite category?", type="multiple_choice",
        options=["web", "pwn", "crypto"],
    )
    assert mc

    # multiple_choice needs >= 2 options.
    bad = await client.post(
        f"/api/competitions/{comp}/surveys/{survey}/questions",
        json={"prompt": "bad", "type": "multiple_choice", "options": ["only one"]},
        headers=_auth(admin),
    )
    assert bad.status_code == 422

    detail = (
        await client.get(f"/api/competitions/{comp}/surveys/{survey}", headers=_auth(admin))
    ).json()
    assert detail["question_count"] == 5
    assert [q["position"] for q in detail["questions"]] == [0, 1, 2, 3, 4]


async def test_question_reorder(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    survey = await _survey(client, comp, admin)
    q1 = await _add_question(client, comp, admin, survey, prompt="one", type="short_text")
    q2 = await _add_question(client, comp, admin, survey, prompt="two", type="short_text")
    q3 = await _add_question(client, comp, admin, survey, prompt="three", type="short_text")

    resp = await client.put(
        f"/api/competitions/{comp}/surveys/{survey}/questions/order",
        json={"question_ids": [q3, q1, q2]},
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    assert [q["id"] for q in resp.json()] == [q3, q1, q2]

    # A reorder that doesn't cover exactly the survey's questions is rejected.
    bad = await client.put(
        f"/api/competitions/{comp}/surveys/{survey}/questions/order",
        json={"question_ids": [q1, q2]},
        headers=_auth(admin),
    )
    assert bad.status_code == 400


# --- competitor visibility + submission --------------------------------------


async def test_competitor_sees_only_open_surveys(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    closed = await _survey(client, comp, admin, title="Closed")
    opened = await _survey(client, comp, admin, title="Open")
    await _open(client, comp, admin, opened)

    seen = (await client.get(f"/api/competitions/{comp}/surveys", headers=_auth(ada))).json()
    assert [s["title"] for s in seen] == ["Open"]
    # The closed one 404s for a competitor even by id.
    assert (
        await client.get(f"/api/competitions/{comp}/surveys/{closed}", headers=_auth(ada))
    ).status_code == 404
    # Staff see both.
    staff = (await client.get(f"/api/competitions/{comp}/surveys", headers=_auth(admin))).json()
    assert len(staff) == 2


async def test_submit_validates_required_range_and_options(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    survey = await _survey(client, comp, admin)
    rating = await _add_question(client, comp, admin, survey, prompt="Rate 1-5", type="rating_1_5")
    choice = await _add_question(
        client, comp, admin, survey, prompt="Best cat?", type="multiple_choice",
        options=["web", "pwn"], required=False,
    )
    text = await _add_question(
        client, comp, admin, survey, prompt="Comments", type="long_text", required=False,
    )
    await _open(client, comp, admin, survey)

    base = f"/api/competitions/{comp}/surveys/{survey}/responses"
    # Missing the required rating.
    assert (await client.post(base, json={"answers": []}, headers=_auth(ada))).status_code == 400
    # Rating out of range.
    assert (
        await client.post(base, json={"answers": [{"question_id": rating, "value": "9"}]}, headers=_auth(ada))
    ).status_code == 400
    # Choice not among options.
    assert (
        await client.post(
            base,
            json={"answers": [{"question_id": rating, "value": "4"}, {"question_id": choice, "value": "forensics"}]},
            headers=_auth(ada),
        )
    ).status_code == 400

    # A valid submission.
    ok = await client.post(
        base,
        json={"answers": [
            {"question_id": rating, "value": "4"},
            {"question_id": choice, "value": "web"},
            {"question_id": text, "value": "great event"},
        ]},
        headers=_auth(ada),
    )
    assert ok.status_code == 201, ok.text
    # Second submission by the same user is refused (one per user).
    dup = await client.post(base, json={"answers": [{"question_id": rating, "value": "3"}]}, headers=_auth(ada))
    assert dup.status_code == 409
    # And the competitor now sees it as responded.
    detail = (await client.get(f"/api/competitions/{comp}/surveys/{survey}", headers=_auth(ada))).json()
    assert detail["responded"] is True


async def test_cannot_submit_to_closed_survey(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    survey = await _survey(client, comp, admin)
    await _add_question(client, comp, admin, survey, prompt="q", type="short_text", required=False)
    # Never opened → competitor can't even see it, and submit 404s (guarded first).
    resp = await client.post(
        f"/api/competitions/{comp}/surveys/{survey}/responses",
        json={"answers": []},
        headers=_auth(ada),
    )
    assert resp.status_code in (404, 409)


# --- event + automation trigger ----------------------------------------------


async def test_submit_emits_survey_submitted_and_triggers_a_rule(client):
    from utils.event_bus import event_bus

    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    survey = await _survey(client, comp, admin)
    q = await _add_question(client, comp, admin, survey, prompt="Rate", type="rating_1_5")
    await _open(client, comp, admin, survey)

    # A rule that notifies the submitter when they complete a survey.
    await client.post(
        f"/api/automations?competition_id={comp}",
        json={
            "name": "Thanks for the feedback",
            "trigger_type": "survey.submitted",
            "conditions": [],
            "actions": [{"type": "notify", "target": "event_user", "title": "Thanks for your feedback!"}],
        },
        headers=_auth(admin),
    )

    resp = await client.post(
        f"/api/competitions/{comp}/surveys/{survey}/responses",
        json={"answers": [{"question_id": q, "value": "5"}]},
        headers=_auth(ada),
    )
    assert resp.status_code == 201
    await event_bus.wait_for_background()

    async with SessionLocal() as session:
        events = (await session.scalars(select(AuditLogEntry.event_name))).all()
    assert "survey.submitted" in events

    notifs = (await client.get("/api/notifications", headers=_auth(ada))).json()
    assert [n["type"] for n in notifs] == ["survey.submitted"]
    assert notifs[0]["title"] == "Thanks for your feedback!"


# --- results + CSV (feedback_view_responses) ---------------------------------


async def test_results_aggregate_by_type(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    survey = await _survey(client, comp, admin)
    rating = await _add_question(client, comp, admin, survey, prompt="Rate 1-5", type="rating_1_5")
    choice = await _add_question(
        client, comp, admin, survey, prompt="Best cat?", type="multiple_choice",
        options=["web", "pwn"], required=False,
    )
    text = await _add_question(
        client, comp, admin, survey, prompt="Comments", type="short_text", required=False,
    )
    await _open(client, comp, admin, survey)

    async def submit(email, rate, cat, comment):
        token = await _participant(client, comp, email)
        r = await client.post(
            f"/api/competitions/{comp}/surveys/{survey}/responses",
            json={"answers": [
                {"question_id": rating, "value": rate},
                {"question_id": choice, "value": cat},
                {"question_id": text, "value": comment},
            ]},
            headers=_auth(token),
        )
        assert r.status_code == 201, r.text

    await submit("a@example.com", "5", "web", "loved it")
    await submit("b@example.com", "3", "web", "")
    await submit("c@example.com", "4", "pwn", "good")

    results = (
        await client.get(f"/api/competitions/{comp}/surveys/{survey}/results", headers=_auth(admin))
    ).json()
    assert results["response_count"] == 3
    by_q = {q["question_id"]: q for q in results["questions"]}
    assert by_q[rating]["average"] == 4.0
    assert by_q[rating]["counts"] == {"5": 1, "3": 1, "4": 1}
    assert by_q[choice]["counts"] == {"web": 2, "pwn": 1}
    assert sorted(by_q[text]["texts"]) == ["good", "loved it"]  # empty comment excluded

    # A competitor can't read results.
    ada = await _participant(client, comp, "nosy@example.com")
    assert (
        await client.get(f"/api/competitions/{comp}/surveys/{survey}/results", headers=_auth(ada))
    ).status_code == 403


async def test_csv_export(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    survey = await _survey(client, comp, admin)
    q = await _add_question(client, comp, admin, survey, prompt="Rate", type="rating_1_5")
    await _open(client, comp, admin, survey)
    await client.post(
        f"/api/competitions/{comp}/surveys/{survey}/responses",
        json={"answers": [{"question_id": q, "value": "5"}]},
        headers=_auth(ada),
    )

    resp = await client.get(
        f"/api/competitions/{comp}/surveys/{survey}/responses.csv", headers=_auth(admin)
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0] == "respondent,email,submitted_at,Rate"
    assert lines[1].startswith("ada,ada@example.com,")
    assert lines[1].endswith(",5")


# --- module gating (§11.3) ----------------------------------------------------


async def test_disabled_module_404s_every_route(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    survey = await _survey(client, comp, admin)

    await client.put(
        f"/api/competitions/{comp}/modules/feedback",
        json={"enabled": False},
        headers=_auth(admin),
    )
    assert (await client.get(f"/api/competitions/{comp}/surveys", headers=_auth(admin))).status_code == 404
    assert (
        await client.post(f"/api/competitions/{comp}/surveys", json={"title": "x"}, headers=_auth(admin))
    ).status_code == 404
    assert (
        await client.get(f"/api/competitions/{comp}/surveys/{survey}", headers=_auth(admin))
    ).status_code == 404

    # Re-enable → works again.
    await client.put(
        f"/api/competitions/{comp}/modules/feedback",
        json={"enabled": True},
        headers=_auth(admin),
    )
    assert (await client.get(f"/api/competitions/{comp}/surveys", headers=_auth(admin))).status_code == 200


async def test_feedback_is_a_toggleable_optional_module(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    modules = (await client.get(f"/api/competitions/{comp}/modules", headers=_auth(admin))).json()
    assert {"feedback", "automations"} <= {m["id"] for m in modules}
    assert all(m["enabled"] for m in modules)
