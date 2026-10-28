"""
Field-log entries of kind "task" (t-1028-1, M1): task_status / due_date /
assignee on create, refused on notes and comments, and changed through the
same PATCH + append-only edit history as body/anchor (B10).

Same in-memory Mongo approach as test_field_log_b10.py: equality filters (a
None filter value matches a missing field, as in Mongo), $set, $push, sort.
"""
from __future__ import annotations

import copy
from unittest.mock import patch

import pytest

import app.db.mongo as _mongo_module

OWNER = "usr_test_001"  # researcher_token's user (conftest)
ANALYSIS = "ana_tasks"
OTHER_ANALYSIS = "ana_someone_else"


def _matches(doc: dict, flt: dict) -> bool:
    return all(doc.get(k) == v for k, v in flt.items())


class _Result:
    def __init__(self, matched: int):
        self.matched_count = matched
        self.modified_count = matched


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field, direction=1):
        self._docs.sort(key=lambda d: d.get(field), reverse=direction < 0)
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._docs:
            return copy.deepcopy(self._docs.pop(0))
        raise StopAsyncIteration


class _FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    async def find_one(self, flt):
        for d in self.docs:
            if _matches(d, flt):
                return copy.deepcopy(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(dict(doc)))

    async def update_one(self, flt, update):
        for d in self.docs:
            if _matches(d, flt):
                for k, v in update.get("$set", {}).items():
                    d[k] = copy.deepcopy(v)
                for k, v in update.get("$push", {}).items():
                    d.setdefault(k, []).append(copy.deepcopy(v))
                return _Result(1)
        return _Result(0)

    def find(self, flt):
        return _Cursor(d for d in self.docs if _matches(d, flt))


class _FakeDb:
    def __init__(self):
        self.collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _FakeCollection())


@pytest.fixture
def db():
    fake = _FakeDb()
    fake["analysis_results"].docs.extend([
        {"analysis_id": ANALYSIS, "user_id": OWNER},
        {"analysis_id": OTHER_ANALYSIS, "user_id": "usr_other"},
    ])
    with patch.object(_mongo_module, "_db", fake):
        yield fake


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _create(client, token, **body):
    payload = {"analysis_id": ANALYSIS, "kind": "task", "body": "Re-run the 12S primer set", **body}
    return await client.post("/field-log/entries", json=payload, headers=_auth(token))


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_create_task_defaults_and_stored_shape(client, researcher_token, db):
    resp = await _create(client, researcher_token, due_date="2026-11-02", assignee="  Wet lab team ")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "task"
    assert body["task_status"] == "open"  # default
    assert body["due_date"] == "2026-11-02"
    assert body["assignee"] == "Wet lab team"
    assert body["author_id"] == OWNER and body["edits"] == []
    stored = db["field_log_entries"].docs[0]
    assert stored["due_date"] == "2026-11-02"  # ISO string, not a datetime
    assert stored["task_status"] == "open"


@pytest.mark.anyio
async def test_create_task_with_explicit_status_and_no_due_date(client, researcher_token, db):
    resp = await _create(client, researcher_token, task_status="in_progress", assignee="   ")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["task_status"] == "in_progress"
    assert body["due_date"] is None
    assert body["assignee"] is None  # blank assignee stored as none


@pytest.mark.anyio
async def test_notes_and_comments_still_have_no_task_fields(client, researcher_token, db):
    for kind in ("note", "comment"):
        resp = await client.post("/field-log/entries", json={"analysis_id": ANALYSIS, "kind": kind, "body": "x"},
                                 headers=_auth(researcher_token))
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["task_status"] is None and body["due_date"] is None and body["assignee"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("field,value", [
    ("task_status", "open"),
    ("due_date", "2026-11-02"),
    ("assignee", "someone"),
])
async def test_task_fields_refused_on_a_note(client, researcher_token, db, field, value):
    resp = await client.post("/field-log/entries",
                             json={"analysis_id": ANALYSIS, "kind": "note", "body": "x", field: value},
                             headers=_auth(researcher_token))
    assert resp.status_code == 422
    assert field in resp.json()["detail"]
    assert db["field_log_entries"].docs == []


@pytest.mark.anyio
@pytest.mark.parametrize("extra", [
    {"task_status": "blocked"},
    {"due_date": "next tuesday"},
    {"assignee": "x" * 201},
    {"body": "   "},
])
async def test_create_task_validation_errors(client, researcher_token, db, extra):
    resp = await _create(client, researcher_token, **extra)
    assert resp.status_code == 422, resp.text
    assert db["field_log_entries"].docs == []


@pytest.mark.anyio
async def test_create_task_on_someone_elses_analysis_is_forbidden(client, researcher_token, db):
    resp = await _create(client, researcher_token, analysis_id=OTHER_ANALYSIS)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_create_task_requires_auth(client, db):
    resp = await client.post("/field-log/entries", json={"analysis_id": ANALYSIS, "kind": "task", "body": "x"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_filters_tasks(client, researcher_token, db):
    await _create(client, researcher_token)
    await client.post("/field-log/entries", json={"analysis_id": ANALYSIS, "kind": "note", "body": "n"},
                      headers=_auth(researcher_token))
    resp = await client.get("/field-log/entries", params={"analysis_id": ANALYSIS, "kind": "task"},
                            headers=_auth(researcher_token))
    assert resp.status_code == 200
    assert [e["kind"] for e in resp.json()] == ["task"]
    resp = await client.get("/field-log/entries", params={"analysis_id": ANALYSIS},
                            headers=_auth(researcher_token))
    assert sorted(e["kind"] for e in resp.json()) == ["note", "task"]


@pytest.mark.anyio
async def test_pre_m1_entry_without_task_fields_loads(client, researcher_token, db):
    # Written before the task kind existed: no task_status/due_date/assignee keys.
    db["field_log_entries"].docs.append({
        "entry_id": "fle_old", "analysis_id": ANALYSIS, "kind": "note", "author_id": OWNER,
        "author_name": "Test User", "body": "old note", "anchor_sequence_id": None, "reply_to": None,
    })
    resp = await client.get("/field-log/entries/fle_old", headers=_auth(researcher_token))
    assert resp.status_code == 200
    assert resp.json()["task_status"] is None


# ---------------------------------------------------------------------------
# PATCH + history
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_patch_task_fields_appends_history(client, researcher_token, db):
    entry = (await _create(client, researcher_token, due_date="2026-11-02")).json()
    eid = entry["entry_id"]

    resp = await client.patch(f"/field-log/entries/{eid}",
                              json={"task_status": "done", "assignee": "Rhea", "due_date": "2026-11-05"},
                              headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task_status"] == "done" and body["assignee"] == "Rhea" and body["due_date"] == "2026-11-05"
    assert len(body["edits"]) == 1
    changes = {c["field"]: (c["old"], c["new"]) for c in body["edits"][0]["changes"]}
    assert changes == {
        "task_status": ("open", "done"),
        "assignee": (None, "Rhea"),
        "due_date": ("2026-11-02", "2026-11-05"),
    }

    # null clears due_date / assignee, and is recorded too
    resp = await client.patch(f"/field-log/entries/{eid}", json={"due_date": None, "assignee": None},
                              headers=_auth(researcher_token))
    body = resp.json()
    assert body["due_date"] is None and body["assignee"] is None
    assert len(body["edits"]) == 2
    stored = db["field_log_entries"].docs[0]
    assert stored["due_date"] is None and len(stored["edits"]) == 2


@pytest.mark.anyio
async def test_patch_same_task_values_records_nothing(client, researcher_token, db):
    eid = (await _create(client, researcher_token, task_status="open")).json()["entry_id"]
    resp = await client.patch(f"/field-log/entries/{eid}", json={"task_status": "open"},
                              headers=_auth(researcher_token))
    assert resp.status_code == 200
    assert resp.json()["edits"] == []


@pytest.mark.anyio
async def test_patch_task_status_null_is_refused(client, researcher_token, db):
    eid = (await _create(client, researcher_token)).json()["entry_id"]
    resp = await client.patch(f"/field-log/entries/{eid}", json={"task_status": None},
                              headers=_auth(researcher_token))
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_patch_task_fields_on_a_note_is_refused(client, researcher_token, db):
    note = (await client.post("/field-log/entries", json={"analysis_id": ANALYSIS, "kind": "note", "body": "n"},
                              headers=_auth(researcher_token))).json()
    resp = await client.patch(f"/field-log/entries/{note['entry_id']}", json={"task_status": "done"},
                              headers=_auth(researcher_token))
    assert resp.status_code == 422
    assert db["field_log_entries"].docs[0].get("edits") == []


@pytest.mark.anyio
async def test_patch_note_body_still_works(client, researcher_token, db):
    note = (await client.post("/field-log/entries", json={"analysis_id": ANALYSIS, "kind": "note", "body": "n"},
                              headers=_auth(researcher_token))).json()
    resp = await client.patch(f"/field-log/entries/{note['entry_id']}", json={"body": "n2"},
                              headers=_auth(researcher_token))
    assert resp.status_code == 200
    assert resp.json()["edits"][0]["changes"] == [{"field": "body", "old": "n", "new": "n2"}]


@pytest.mark.anyio
async def test_curator_can_update_a_researchers_task(client, researcher_token, curator_token, db):
    eid = (await _create(client, researcher_token)).json()["entry_id"]
    resp = await client.patch(f"/field-log/entries/{eid}", json={"task_status": "in_progress"},
                              headers=_auth(curator_token))
    assert resp.status_code == 200
    assert resp.json()["edits"][0]["editor_id"] == "usr_curator_001"
