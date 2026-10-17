"""Programming challenges — problem authoring (#447, ADR-0042): the challenge
type, test cases (pasted and uploaded) stored as one ICPC-layout zip, the
limits / comparison / language overrides, the publish gate, and test data
riding backup, clone, challenge delete and the competition purge. Nothing here
runs code; judging arrives in #448."""

import io
import zipfile

import pytest
from sqlalchemy import select

from db import SessionLocal
from models.competition import Competition
from models.judge import JUDGE_SETTINGS_ID, JudgeLanguage, JudgeSettings
from models.judge_problem import JudgeProblem
from storage.memory import InMemoryStorage
from tests.conftest import admin_token
from utils import backup
from utils import judge_testdata as td

import main  # noqa: F401, E402  (loads the judge module's routes)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _competition(client, admin: str) -> str:
    resp = await client.post(
        "/api/competitions",
        json={"name": "Code Cup", "participation_mode": "individual", "visibility": "public"},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _programming(client, admin: str, comp: str, **over) -> str:
    body = {"title": "A + B", "points": 100, "flag_type": "programming", **over}
    resp = await client.post(
        f"/api/competitions/{comp}/challenges", json=body, headers=_auth(admin)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _setup(client) -> tuple[str, str, str]:
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    chal = await _programming(client, admin, comp)
    return admin, comp, chal


def _base(comp: str, chal: str) -> str:
    return f"/api/competitions/{comp}/challenges/{chal}/judge"


async def _add(client, admin, comp, chal, inp="1 2", ans="3", sample=False) -> dict:
    resp = await client.post(
        f"{_base(comp, chal)}/testcases",
        json={"input": inp, "answer": ans, "sample": sample},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _problem_row(chal: str) -> JudgeProblem | None:
    async with SessionLocal() as db:
        return await db.scalar(select(JudgeProblem).where(JudgeProblem.challenge_id == chal))


async def _set_module(client, admin, comp, enabled: bool) -> None:
    resp = await client.put(
        f"/api/competitions/{comp}/modules/judge",
        json={"enabled": enabled},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text


async def _participant(client, comp: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": "coder@example.com", "password": "password123", "display_name": "coder"},
    )
    token = resp.json()["access_token"]
    join = await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    assert join.status_code in (200, 201, 204), join.text
    return token


# --- the challenge type -------------------------------------------------------


async def test_programming_challenge_has_no_flag_and_rejects_one(client):
    admin, comp, chal = await _setup(client)
    got = (
        await client.get(f"/api/competitions/{comp}/challenges/{chal}", headers=_auth(admin))
    ).json()
    assert got["flag_type"] == "programming" and got["has_flag"] is False

    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "x", "flag_type": "programming", "flag": "flag{no}"},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    resp = await client.patch(
        f"/api/competitions/{comp}/challenges/{chal}",
        json={"flag": "flag{no}"},
        headers=_auth(admin),
    )
    assert resp.status_code == 400


async def test_type_cannot_switch_to_or_from_programming(client):
    admin, comp, chal = await _setup(client)
    resp = await client.patch(
        f"/api/competitions/{comp}/challenges/{chal}",
        json={"flag_type": "static", "flag": "flag{x}"},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    static = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "s", "flag": "flag{s}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    resp = await client.patch(
        f"/api/competitions/{comp}/challenges/{static}",
        json={"flag_type": "programming"},
        headers=_auth(admin),
    )
    assert resp.status_code == 400


async def test_programming_needs_the_module(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _set_module(client, admin, comp, False)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "x", "flag_type": "programming"},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    assert "code judge" in resp.json()["detail"]


async def test_authoring_routes_404_when_module_disabled(client):
    admin, comp, chal = await _setup(client)
    await _set_module(client, admin, comp, False)
    resp = await client.get(_base(comp, chal), headers=_auth(admin))
    assert resp.status_code == 404


async def test_authoring_routes_refuse_a_flag_challenge(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    static = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "s", "flag": "flag{s}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    resp = await client.get(_base(comp, static), headers=_auth(admin))
    assert resp.status_code == 400


async def test_flag_submission_is_refused(client):
    admin, comp, chal = await _setup(client)
    await _add(client, admin, comp, chal)
    pub = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
    )
    assert pub.status_code == 200, pub.text
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "anything"},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    assert "submitting code" in resp.json()["detail"]


# --- publishing ----------------------------------------------------------------


async def test_publish_requires_a_test_case(client):
    admin, comp, chal = await _setup(client)
    url = f"/api/competitions/{comp}/challenges/{chal}/publish"
    resp = await client.post(url, headers=_auth(admin))
    assert resp.status_code == 400
    assert "test case" in resp.json()["detail"]
    # A problem whose test cases were all removed is still unpublishable.
    case = (await _add(client, admin, comp, chal))["testcases"][0]
    await client.delete(f"{_base(comp, chal)}/testcases/{case['id']}", headers=_auth(admin))
    assert (await _problem_row(chal)) is not None
    resp = await client.post(url, headers=_auth(admin))
    assert resp.status_code == 400
    await _add(client, admin, comp, chal)
    resp = await client.post(url, headers=_auth(admin))
    assert resp.status_code == 200
    assert resp.json()["state"] == "published"


# --- problem settings -----------------------------------------------------------


async def test_new_problem_reports_defaults(client):
    admin, comp, chal = await _setup(client)
    body = (await client.get(_base(comp, chal), headers=_auth(admin))).json()
    assert body["time_limit_ms"] is None
    assert body["compare_mode"] == "token"
    assert body["allowed_languages"] is None
    assert body["testcases"] == []
    assert body["default_time_limit_ms"] == 2000
    assert body["default_memory_limit_mb"] == 256
    # A read creates nothing.
    assert await _problem_row(chal) is None


async def test_update_and_reset_limits(client):
    admin, comp, chal = await _setup(client)
    async with SessionLocal() as db:
        db.add(JudgeLanguage(key="python3", name="Python 3", image_ref="python:3.14-slim",
                             source_filename="main.py", run_command=["python3", "{source}"]))
        await db.commit()
    resp = await client.put(
        _base(comp, chal),
        json={"time_limit_ms": 5000, "compare_mode": "float", "allowed_languages": ["python3"]},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["time_limit_ms"] == 5000
    # Choosing float comparison fills in a tolerance rather than leaving it blank.
    assert body["compare_mode"] == "float" and body["float_tolerance"] == pytest.approx(1e-6)
    assert body["allowed_languages"] == ["python3"]

    # An omitted field is left alone; an explicit null resets to the default.
    body = (
        await client.put(_base(comp, chal), json={"time_limit_ms": None}, headers=_auth(admin))
    ).json()
    assert body["time_limit_ms"] is None and body["allowed_languages"] == ["python3"]
    # An empty language list means "all", not "none".
    body = (
        await client.put(_base(comp, chal), json={"allowed_languages": []}, headers=_auth(admin))
    ).json()
    assert body["allowed_languages"] is None


async def test_update_validates(client):
    admin, comp, chal = await _setup(client)
    for bad in (
        {"compare_mode": "regex"},
        {"time_limit_ms": 10},
        {"memory_limit_mb": 100_000},
        {"allowed_languages": ["cobol"]},
    ):
        resp = await client.put(_base(comp, chal), json=bad, headers=_auth(admin))
        assert resp.status_code == 422, (bad, resp.text)


# --- test cases -----------------------------------------------------------------


async def test_add_list_edit_delete_testcases(client, object_storage):
    admin, comp, chal = await _setup(client)
    await _add(client, admin, comp, chal, "1 2", "3")
    body = await _add(client, admin, comp, chal, "5 5", "10", sample=True)
    cases = body["testcases"]
    # Samples are listed (and judged) first.
    assert [c["sample"] for c in cases] == [True, False]
    assert cases[0]["input_preview"] == "5 5\n" and cases[1]["answer_preview"] == "3\n"
    sample_id, secret_id = cases[0]["id"], cases[1]["id"]

    got = (
        await client.get(f"{_base(comp, chal)}/testcases/{secret_id}", headers=_auth(admin))
    ).json()
    assert got == {"id": secret_id, "sample": False, "editable": True,
                   "input": "1 2\n", "answer": "3\n"}

    resp = await client.patch(
        f"{_base(comp, chal)}/testcases/{secret_id}",
        json={"answer": "three\r\n", "sample": True},
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    assert [c["id"] for c in resp.json()["testcases"]] == [sample_id, secret_id]

    resp = await client.delete(
        f"{_base(comp, chal)}/testcases/{sample_id}", headers=_auth(admin)
    )
    assert resp.status_code == 204
    row = await _problem_row(chal)
    assert [c["id"] for c in row.testcases] == [secret_id]
    # Only the current zip remains: every rewrite deletes its predecessor.
    keys = [k for k in object_storage._objects if f"/judge/{chal}/" in k]
    assert keys == [row.object_key]
    with zipfile.ZipFile(io.BytesIO(object_storage.get(row.object_key))) as zf:
        assert sorted(zf.namelist()) == ["data/sample/001.ans", "data/sample/001.in"]
        assert zf.read("data/sample/001.ans") == b"three\n"

    # Deleting the last case clears the object entirely.
    await client.delete(f"{_base(comp, chal)}/testcases/{secret_id}", headers=_auth(admin))
    row = await _problem_row(chal)
    assert row.object_key is None and row.testcases == []
    assert not [k for k in object_storage._objects if f"/judge/{chal}/" in k]


async def test_zip_uses_icpc_layout(client, object_storage):
    admin, comp, chal = await _setup(client)
    await _add(client, admin, comp, chal, "a", "A")
    await _add(client, admin, comp, chal, "b", "B", sample=True)
    await _add(client, admin, comp, chal, "c", "C")
    row = await _problem_row(chal)
    with zipfile.ZipFile(io.BytesIO(object_storage.get(row.object_key))) as zf:
        assert zf.read("data/sample/001.in") == b"b\n"
        assert zf.read("data/secret/001.in") == b"a\n"
        assert zf.read("data/secret/002.ans") == b"C\n"
    assert row.object_key.startswith(f"{comp}/judge/{chal}/")


async def test_upload_stores_bytes_verbatim(client, object_storage):
    admin, comp, chal = await _setup(client)
    resp = await client.post(
        f"{_base(comp, chal)}/testcases/upload",
        files={
            "input_file": ("1.in", b"\x00\xff binary", "application/octet-stream"),
            "answer_file": ("1.ans", b"no newline", "text/plain"),
        },
        data={"sample": "true"},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    case = resp.json()["testcases"][0]
    assert case["sample"] is True and case["input_bytes"] == 9
    got = (
        await client.get(f"{_base(comp, chal)}/testcases/{case['id']}", headers=_auth(admin))
    ).json()
    # Not text, so the editor offers replacement rather than in-place editing.
    assert got["editable"] is False and got["input"] is None
    cases = td.load(object_storage, (await _problem_row(chal)).object_key,
                    (await _problem_row(chal)).testcases)
    assert cases[0].input == b"\x00\xff binary" and cases[0].answer == b"no newline"


async def test_problem_size_cap(client, monkeypatch):
    admin, comp, chal = await _setup(client)
    monkeypatch.setattr(td, "MAX_TOTAL_BYTES", 10)
    await _add(client, admin, comp, chal, "1", "2")
    resp = await client.post(
        f"{_base(comp, chal)}/testcases",
        json={"input": "123456", "answer": "7"},
        headers=_auth(admin),
    )
    assert resp.status_code == 413
    assert "MB" in resp.json()["detail"]
    # The rejected edit left the problem as it was.
    assert len((await _problem_row(chal)).testcases) == 1


async def test_unknown_testcase_404(client):
    admin, comp, chal = await _setup(client)
    await _add(client, admin, comp, chal)
    for method in ("GET", "PATCH", "DELETE"):
        resp = await client.request(
            method, f"{_base(comp, chal)}/testcases/nope", json={}, headers=_auth(admin)
        )
        assert resp.status_code == 404, method


async def test_testcase_edits_emit_challenge_updated(client):
    from models.audit_log import AuditLogEntry

    admin, comp, chal = await _setup(client)
    await _add(client, admin, comp, chal)
    async with SessionLocal() as db:
        entries = (
            await db.scalars(
                select(AuditLogEntry).where(AuditLogEntry.event_name == "challenge.updated")
            )
        ).all()
    assert any(e.payload.get("changed_fields") == ["judge_testcases"] for e in entries)


# --- RBAC + scoping --------------------------------------------------------------


async def test_authoring_requires_challenge_edit(client):
    admin, comp, chal = await _setup(client)
    player = await _participant(client, comp)
    for method, path in (
        ("GET", ""),
        ("PUT", ""),
        ("POST", "/testcases"),
    ):
        resp = await client.request(
            method, _base(comp, chal) + path, json={}, headers=_auth(player)
        )
        assert resp.status_code == 403, (method, path, resp.status_code)


async def test_challenge_from_another_competition_404(client):
    admin, comp, chal = await _setup(client)
    other = await _competition(client, admin)
    resp = await client.get(_base(other, chal), headers=_auth(admin))
    assert resp.status_code == 404


async def test_status_endpoint(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    player = await _participant(client, comp)
    url = f"/api/competitions/{comp}/judge/status"
    body = (await client.get(url, headers=_auth(player))).json()
    # The default time limit pre-fills the package import form (#451).
    assert body == {"module_enabled": True, "judge_enabled": False, "ready": False,
                    "languages": [], "default_time_limit_ms": 2000}

    async with SessionLocal() as db:
        db.add(JudgeSettings(id=JUDGE_SETTINGS_ID, enabled=True))
        db.add(JudgeLanguage(key="python3", name="Python 3", image_ref="python:3.14-slim",
                             source_filename="main.py", run_command=["python3", "{source}"]))
        db.add(JudgeLanguage(key="c", name="C", image_ref="gcc:16", enabled=False,
                             source_filename="main.c", run_command=["./a.out"]))
        await db.commit()
    body = (await client.get(url, headers=_auth(player))).json()
    # Only enabled languages, and only key + name — never images or commands.
    assert body == {"module_enabled": True, "judge_enabled": True, "ready": True,
                    "languages": [{"key": "python3", "name": "Python 3"}],
                    "default_time_limit_ms": 2000}

    await _set_module(client, admin, comp, False)
    body = (await client.get(url, headers=_auth(player))).json()
    assert body["module_enabled"] is False and body["ready"] is False


# --- lifecycle: delete, clone, purge, backup ---------------------------------------


async def test_challenge_delete_removes_test_data(client, object_storage):
    admin, comp, chal = await _setup(client)
    await _add(client, admin, comp, chal)
    key = (await _problem_row(chal)).object_key
    assert object_storage.exists(key)
    resp = await client.delete(
        f"/api/competitions/{comp}/challenges/{chal}", headers=_auth(admin)
    )
    assert resp.status_code == 204
    assert not object_storage.exists(key)
    assert await _problem_row(chal) is None


async def test_clone_copies_problem_and_test_data(client, object_storage):
    admin, comp, chal = await _setup(client)
    await client.put(_base(comp, chal), json={"time_limit_ms": 3000}, headers=_auth(admin))
    await _add(client, admin, comp, chal, "4 4", "8", sample=True)
    source_key = (await _problem_row(chal)).object_key

    clone = (
        await client.post(
            f"/api/competitions/{comp}/clone", json={"name": "Code Cup II"}, headers=_auth(admin)
        )
    ).json()
    new_chal = (
        await client.get(f"/api/competitions/{clone['id']}/challenges", headers=_auth(admin))
    ).json()[0]["id"]
    body = (await client.get(_base(clone["id"], new_chal), headers=_auth(admin))).json()
    assert body["time_limit_ms"] == 3000
    assert [c["input_preview"] for c in body["testcases"]] == ["4 4\n"]
    new_key = (await _problem_row(new_chal)).object_key
    assert new_key != source_key and new_key.startswith(f"{clone['id']}/judge/{new_chal}/")
    assert object_storage.get(new_key) == object_storage.get(source_key)


async def test_competition_purge_removes_test_data(client, object_storage):
    from utils.retention import delete_competition_tree

    admin, comp, chal = await _setup(client)
    await _add(client, admin, comp, chal)
    key = (await _problem_row(chal)).object_key
    async with SessionLocal() as db:
        await delete_competition_tree(db, object_storage, await db.get(Competition, comp))
    assert not object_storage.exists(key)


async def test_problem_rides_the_backup(client, object_storage):
    admin, comp, chal = await _setup(client)
    await client.put(_base(comp, chal), json={"compare_mode": "exact"}, headers=_auth(admin))
    await _add(client, admin, comp, chal, "x", "y", sample=True)

    async with SessionLocal() as db:
        doc = await backup.export_data(db, object_storage, ["competitions"])
    [row] = doc["data"]["judge_problems"]
    assert row["_object_data"]
    async with SessionLocal() as db:
        await db.delete(await db.get(Competition, comp))
        await db.commit()

    storage = InMemoryStorage()
    async with SessionLocal() as db:
        result = await backup.import_data(db, storage, doc, ["competitions"])
    assert result["judge_problems"]["created"] == 1
    async with SessionLocal() as db:
        problem = await db.scalar(select(JudgeProblem))
    assert problem.compare_mode == "exact"
    assert problem.object_key.startswith(f"{problem.competition_id}/judge/{problem.challenge_id}/")
    [case] = td.load(storage, problem.object_key, problem.testcases)
    assert case.sample and case.input == b"x\n" and case.answer == b"y\n"


async def test_backup_import_drops_a_foreign_object_key(client, object_storage):
    """A row whose test data didn't travel with it (or a crafted row naming some
    other competition's object) is imported without test data, never pointing at
    a key it doesn't own."""
    admin, comp, chal = await _setup(client)
    await _add(client, admin, comp, chal)
    async with SessionLocal() as db:
        doc = await backup.export_data(db, object_storage, ["competitions"])
    doc["data"]["judge_problems"][0]["_object_data"] = None
    doc["data"]["judge_problems"][0]["object_key"] = "victim-comp/judge/x/secret.zip"
    async with SessionLocal() as db:
        await db.delete(await db.get(Competition, comp))
        await db.commit()
    async with SessionLocal() as db:
        await backup.import_data(db, InMemoryStorage(), doc, ["competitions"])
    async with SessionLocal() as db:
        problem = await db.scalar(select(JudgeProblem))
    assert problem.object_key is None and problem.testcases == []


@pytest.mark.parametrize(
    "bad",
    [
        {"compare_mode": "regex"},
        {"time_limit_ms": "5000"},
        {"allowed_languages": "python3"},
        {"testcases": [{"id": 1}]},
    ],
)
async def test_backup_import_rejects_an_invalid_problem(client, object_storage, bad):
    admin, comp, chal = await _setup(client)
    await _add(client, admin, comp, chal)
    async with SessionLocal() as db:
        doc = await backup.export_data(db, object_storage, ["competitions"])
    doc["data"]["judge_problems"][0].update(bad)
    async with SessionLocal() as db:
        await db.delete(await db.get(Competition, comp))
        await db.commit()
    async with SessionLocal() as db:
        with pytest.raises(backup.ImportError_):
            await backup.import_data(db, InMemoryStorage(), doc, ["competitions"])


# --- reading stored test data (GHSA-wvjv-56qv-9v42) ----------------------------


def _stored_testdata(object_storage, inputs: list[bytes], *, method=zipfile.ZIP_DEFLATED,
                     extra: int = 0) -> tuple[str, list[dict]]:
    """A test-data zip as a restored backup could plant it: one secret case per
    input (answer ``1``), the inputs compressed with ``method``, plus ``extra``
    stray entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, data in enumerate(inputs, start=1):
            zf.writestr(f"data/secret/{i:03d}.in", data, compress_type=method)
            zf.writestr(f"data/secret/{i:03d}.ans", b"1\n")
        for i in range(extra):
            zf.writestr(f"stray/{i}", b"")
    object_storage.put("planted", buf.getvalue(), "application/zip")
    rows = [{"id": f"c{i}", "sample": False, "input_bytes": 1, "answer_bytes": 2}
            for i in range(len(inputs))]
    return "planted", rows


def test_stored_test_data_is_read_within_the_caps(object_storage, monkeypatch):
    """The judge reads a problem's zip on every judging and problem view, and a
    restored backup decides its bytes — so it's read under the caps it was
    written under, never trusting the zip's own sizes or compression."""
    monkeypatch.setattr(td, "MAX_FILE_BYTES", 1024)
    with pytest.raises(td.TestdataError, match="larger"):  # one file over its cap
        td.load(object_storage, *_stored_testdata(object_storage, [b"\0" * 4096]))
    monkeypatch.setattr(td, "MAX_TOTAL_BYTES", 2048)
    with pytest.raises(td.TestdataError, match="larger"):  # each under, together over
        td.load(object_storage, *_stored_testdata(object_storage, [b"\0" * 1000] * 3))
    for method in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):  # would inflate whole
        with pytest.raises(td.TestdataError, match="malformed"):
            td.load(object_storage, *_stored_testdata(object_storage, [b"1\n"], method=method))
    # Within every cap, it reads as ever.
    [case] = td.load(object_storage, *_stored_testdata(object_storage, [b"\0" * 1000]))
    assert case.input == b"\0" * 1000 and case.answer == b"1\n"


def test_stored_test_data_entry_count_is_capped_before_parsing(object_storage, monkeypatch):
    monkeypatch.setattr(td, "MAX_MEMBERS", 4)
    td.load(object_storage, *_stored_testdata(object_storage, [b"1\n"], extra=2))
    with pytest.raises(td.TestdataError, match="malformed"):
        td.load(object_storage, *_stored_testdata(object_storage, [b"1\n"], extra=3))
    # Two entries a case: a problem with more cases than the cap is still read.
    assert len(td.load(object_storage, *_stored_testdata(object_storage, [b"1\n"] * 3))) == 3
