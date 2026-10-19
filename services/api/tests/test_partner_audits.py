"""
Partner audits (t-1028-1, M1): POST /partner/audits, GET /partner/audits,
and the tasks/audits sections of GET /partner/summary.

The conftest mock DB returns None / an empty cursor for everything, which
covers the empty-database cases; the rest patch in a small in-memory Mongo
that supports what these routes use: equality (dotted keys too), $gte/$lt,
$in, sort, limit, insert_one, find_one.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import app.db.mongo as _mongo_module
from app.auth.jwt import create_access_token
from app.models.user import UserRole

OWNER = "usr_test_001"  # researcher_token's user (conftest)
OTHER = "usr_other"


# ---------------------------------------------------------------------------
# In-memory Mongo
# ---------------------------------------------------------------------------

def _get(doc: dict, key: str):
    for part in key.split("."):
        if not isinstance(doc, dict):
            return None
        doc = doc.get(part)
    return doc


def _cmp(value, cond) -> bool:
    if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
        for op, arg in cond.items():
            if op == "$gte" and not (value is not None and value >= arg):
                return False
            if op == "$lt" and not (value is not None and value < arg):
                return False
            if op == "$in" and value not in arg:
                return False
        return True
    return value == cond


def _matches(doc: dict, flt: dict) -> bool:
    return all(_cmp(_get(doc, k), v) for k, v in flt.items())


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field, direction=1):
        self._docs.sort(key=lambda d: d.get(field), reverse=direction < 0)
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._docs:
            return copy.deepcopy(self._docs.pop(0))
        raise StopAsyncIteration


class _Collection:
    def __init__(self):
        self.docs: list[dict] = []

    async def find_one(self, flt):
        for d in self.docs:
            if _matches(d, flt):
                return copy.deepcopy(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(dict(doc)))

    def find(self, flt=None, projection=None):
        return _Cursor(d for d in self.docs if _matches(d, flt or {}))


class _FakeDb:
    def __init__(self):
        self.collections: dict[str, _Collection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.fixture
def db():
    fake = _FakeDb()
    fake["uploads"].docs.extend([
        {"upload_id": "upl_own", "user_id": OWNER, "created_at": datetime(2026, 10, 1, 8)},
        {"upload_id": "upl_other", "user_id": OTHER, "created_at": datetime(2026, 10, 1, 8)},
    ])
    fake["analysis_results"].docs.extend([
        {"analysis_id": "ana_own", "upload_id": "upl_own", "user_id": OWNER,
         "created_at": datetime(2026, 10, 1, 9), "results": []},
        {"analysis_id": "ana_other", "upload_id": "upl_other", "user_id": OTHER,
         "created_at": datetime(2026, 10, 1, 9), "results": []},
    ])
    with patch.object(_mongo_module, "_db", fake):
        yield fake


@pytest.fixture
def viewer_token():
    return create_access_token("usr_viewer_001", {"email": "v@example.com", "role": UserRole.viewer, "name": "Viewer"})


@pytest.fixture
def company_owner_token():
    return create_access_token(
        "usr_company_001",
        {"email": "owner@example.com", "role": UserRole.company_owner, "name": "Company Owner"},
    )


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _audit(**over):
    body = {
        "target": {"kind": "site", "label": "Outfall zone B"},
        "scope": "Effluent eDNA sampling against the 2026 discharge permit",
        "findings": [{"severity": "medium", "description": "Two contamination flags unreviewed"}],
    }
    body.update(over)
    return body


# ---------------------------------------------------------------------------
# POST /partner/audits
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_create_requires_auth(client):
    resp = await client.post("/partner/audits", json=_audit())
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_viewer_cannot_create(client, viewer_token, db):
    resp = await client.post("/partner/audits", json=_audit(), headers=_auth(viewer_token))
    assert resp.status_code == 403
    assert db["audits"].docs == []


@pytest.mark.anyio
async def test_create_audit_happy_path(client, researcher_token, db):
    resp = await client.post("/partner/audits", json=_audit(due_date="2026-11-30"), headers=_auth(researcher_token))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["audit_id"].startswith("aud_")
    assert body["created_by"] == OWNER and body["created_by_name"] == "Test User"
    assert body["status"] == "scheduled"
    assert body["due_date"] == "2026-11-30"
    assert body["completed_at"] is None
    assert body["target"] == {"kind": "site", "ref": None, "label": "Outfall zone B"}
    assert body["findings"] == [{"severity": "medium", "description": "Two contamination flags unreviewed",
                                 "reference": None}]
    [stored] = db["audits"].docs
    assert stored["audit_id"] == body["audit_id"] and stored["created_by"] == OWNER
    assert stored["due_date"] == "2026-11-30"  # ISO string, BSON has no date-only type
    assert isinstance(stored["created_at"], datetime) and stored["created_at"].tzinfo is None


@pytest.mark.anyio
async def test_created_by_cannot_be_supplied(client, researcher_token, db):
    resp = await client.post("/partner/audits", json=_audit(created_by=OTHER), headers=_auth(researcher_token))
    assert resp.status_code == 422
    assert db["audits"].docs == []


@pytest.mark.anyio
async def test_completed_without_completed_at_is_stamped_now(client, researcher_token, db):
    before = datetime.utcnow()
    resp = await client.post("/partner/audits", json=_audit(status="completed"), headers=_auth(researcher_token))
    assert resp.status_code == 201, resp.text
    stored = db["audits"].docs[0]
    assert stored["status"] == "completed"
    assert before <= stored["completed_at"] <= datetime.utcnow()


@pytest.mark.anyio
async def test_completed_at_with_offset_is_stored_as_utc(client, researcher_token, db):
    resp = await client.post("/partner/audits",
                             json=_audit(status="completed", completed_at="2026-09-30T17:00:00+05:30"),
                             headers=_auth(researcher_token))
    assert resp.status_code == 201, resp.text
    assert db["audits"].docs[0]["completed_at"] == datetime(2026, 9, 30, 11, 30)


@pytest.mark.anyio
@pytest.mark.parametrize("body", [
    {k: v for k, v in _audit().items() if k != "scope"},                     # scope missing
    _audit(scope="   "),                                                     # blank scope
    _audit(target={"kind": "site", "label": ""}),                            # blank label
    _audit(target={"kind": "planet", "label": "Mars"}),                      # unknown target kind
    _audit(target={"kind": "upload", "label": "An upload"}),                 # upload needs ref
    _audit(target={"kind": "analysis", "label": "A run", "ref": None}),      # analysis needs ref
    _audit(findings=[{"severity": "catastrophic", "description": "x"}]),     # unknown severity
    _audit(findings=[{"severity": "low", "description": "  "}]),             # blank finding
    _audit(status="approved"),                                               # unknown status
    _audit(due_date="soon"),
    _audit(completed_at="2026-09-30T10:00:00"),                              # status not completed
    _audit(status="completed",
           completed_at=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat()),  # in the future
    _audit(extra_field=1),
])
async def test_create_validation_errors(client, researcher_token, db, body):
    resp = await client.post("/partner/audits", json=body, headers=_auth(researcher_token))
    assert resp.status_code == 422, resp.text
    assert db["audits"].docs == []


@pytest.mark.anyio
async def test_upload_target_must_exist(client, researcher_token, db):
    resp = await client.post("/partner/audits",
                             json=_audit(target={"kind": "upload", "ref": "upl_missing", "label": "x"}),
                             headers=_auth(researcher_token))
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_upload_target_must_be_visible(client, researcher_token, company_owner_token, db):
    target = {"kind": "upload", "ref": "upl_other", "label": "Someone else's sample"}
    resp = await client.post("/partner/audits", json=_audit(target=target), headers=_auth(researcher_token))
    assert resp.status_code == 403
    resp = await client.post("/partner/audits", json=_audit(target={**target, "ref": "upl_own"}),
                             headers=_auth(researcher_token))
    assert resp.status_code == 201
    # company_owner may read any upload, so may audit it
    resp = await client.post("/partner/audits", json=_audit(target=target), headers=_auth(company_owner_token))
    assert resp.status_code == 201


@pytest.mark.anyio
async def test_analysis_target_access(client, researcher_token, curator_token, db):
    target = {"kind": "analysis", "ref": "ana_other", "label": "Run"}
    resp = await client.post("/partner/audits", json=_audit(target=target), headers=_auth(researcher_token))
    assert resp.status_code == 403
    resp = await client.post("/partner/audits", json=_audit(target={**target, "ref": "ana_missing"}),
                             headers=_auth(researcher_token))
    assert resp.status_code == 404
    resp = await client.post("/partner/audits", json=_audit(target=target), headers=_auth(curator_token))
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# GET /partner/audits
# ---------------------------------------------------------------------------

def _stored(audit_id, created_by, created_at, status="scheduled", kind="site", ref=None, **extra):
    return {"audit_id": audit_id, "target": {"kind": kind, "ref": ref, "label": "L"}, "scope": "s",
            "findings": [], "status": status, "due_date": None, "completed_at": None,
            "created_by": created_by, "created_by_name": created_by, "created_at": created_at, **extra}


@pytest.fixture
def seeded(db):
    db["audits"].docs.extend([
        _stored("aud_1", OWNER, datetime(2026, 10, 1, 9)),
        _stored("aud_2", OWNER, datetime(2026, 10, 5, 9), status="completed",
                completed_at=datetime(2026, 10, 6, 9), kind="upload", ref="upl_own"),
        _stored("aud_3", OTHER, datetime(2026, 10, 3, 9), status="in_progress"),
    ])
    return db


@pytest.mark.anyio
async def test_list_requires_auth(client):
    resp = await client.get("/partner/audits")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_list_empty_database(client, researcher_token, db):
    # In-memory db (the conftest cursor has no sort()); no audits seeded.
    resp = await client.get("/partner/audits", headers=_auth(researcher_token))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_list_own_newest_first(client, researcher_token, seeded):
    resp = await client.get("/partner/audits", headers=_auth(researcher_token))
    assert resp.status_code == 200
    assert [a["audit_id"] for a in resp.json()] == ["aud_2", "aud_1"]


@pytest.mark.anyio
async def test_researcher_cannot_list_others(client, researcher_token, seeded):
    resp = await client.get("/partner/audits", params={"created_by": OTHER}, headers=_auth(researcher_token))
    assert resp.status_code == 403
    resp = await client.get("/partner/audits", params={"created_by": OWNER}, headers=_auth(researcher_token))
    assert [a["audit_id"] for a in resp.json()] == ["aud_2", "aud_1"]


@pytest.mark.anyio
async def test_admin_lists_everyone_and_narrows(client, admin_token, seeded):
    resp = await client.get("/partner/audits", headers=_auth(admin_token))
    assert [a["audit_id"] for a in resp.json()] == ["aud_2", "aud_3", "aud_1"]
    resp = await client.get("/partner/audits", params={"created_by": OTHER}, headers=_auth(admin_token))
    assert [a["audit_id"] for a in resp.json()] == ["aud_3"]


@pytest.mark.anyio
@pytest.mark.parametrize("params,expected", [
    ({"status": "completed"}, ["aud_2"]),
    ({"status": "in_progress"}, ["aud_3"]),
    ({"target_kind": "upload"}, ["aud_2"]),
    ({"target_ref": "upl_own"}, ["aud_2"]),
    ({"date_from": "2026-10-02"}, ["aud_2", "aud_3"]),
    ({"date_to": "2026-10-03"}, ["aud_3", "aud_1"]),  # inclusive
    ({"date_from": "2026-10-02", "date_to": "2026-10-04"}, ["aud_3"]),
    ({"limit": 1}, ["aud_2"]),
])
async def test_list_filters(client, company_owner_token, seeded, params, expected):
    resp = await client.get("/partner/audits", params=params, headers=_auth(company_owner_token))
    assert resp.status_code == 200, resp.text
    assert [a["audit_id"] for a in resp.json()] == expected


@pytest.mark.anyio
@pytest.mark.parametrize("params", [
    {"status": "approved"},
    {"target_kind": "planet"},
    {"date_from": "2026-10-05", "date_to": "2026-10-01"},
    {"limit": 0},
    {"limit": 201},
])
async def test_list_validation_errors(client, researcher_token, params):
    resp = await client.get("/partner/audits", params=params, headers=_auth(researcher_token))
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Summary: tasks + audits sections
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_summary_empty_tasks_and_audits(client, researcher_token):
    body = (await client.get("/partner/summary", headers=_auth(researcher_token))).json()
    assert body["tasks"] == {"total": 0, "by_status": {"open": 0, "in_progress": 0, "done": 0},
                             "overdue": 0, "next_due_date": None}
    audits = body["audits"]
    assert audits["total"] == audits["pending"] == audits["overdue"] == 0
    assert set(audits["by_status"].values()) == {0}
    assert set(audits["findings_by_severity"].values()) == {0}
    assert audits["next_due_date"] is None and audits["last_completed_at"] is None


@pytest.mark.anyio
async def test_summary_empty_note_does_not_contradict_audits(client, researcher_token, db):
    # Audits are not date-filtered, so a scope with no uploads or analyses can
    # still carry audits; the empty-scope note must not claim every count is zero.
    db["uploads"].docs.clear()
    db["analysis_results"].docs.clear()
    db["audits"].docs.append(_stored("aud_1", OWNER, datetime(2026, 10, 1, 9), due_date="2020-01-01",
                                     findings=[{"severity": "high", "description": "d"}]))
    body = (await client.get("/partner/summary", headers=_auth(researcher_token))).json()
    assert set(body["totals"].values()) == {0}
    assert body["audits"]["total"] == 1 and body["audits"]["overdue"] == 1
    assert not any("every count is zero" in n for n in body["notes"]), body["notes"]
    assert any("No uploads or analyses" in n and "1 audit" in n for n in body["notes"]), body["notes"]


@pytest.mark.anyio
async def test_summary_counts_tasks_and_audits(client, researcher_token, company_owner_token, db):
    # Past / far-future due dates keep "overdue" independent of the run date.
    db["field_log_entries"].docs.extend([
        {"entry_id": "t1", "analysis_id": "ana_own", "kind": "task", "task_status": "open", "due_date": "2020-01-01"},
        {"entry_id": "t2", "analysis_id": "ana_own", "kind": "task", "task_status": "in_progress",
         "due_date": "2099-01-01"},
        # done tasks are never overdue
        {"entry_id": "t3", "analysis_id": "ana_own", "kind": "task", "task_status": "done", "due_date": "2019-01-01"},
        {"entry_id": "n1", "analysis_id": "ana_own", "kind": "note"},
        {"entry_id": "t4", "analysis_id": "ana_other", "kind": "task", "task_status": "open"},
    ])
    db["audits"].docs.extend([
        _stored("aud_1", OWNER, datetime(2026, 10, 1, 9), due_date="2020-06-01",
                findings=[{"severity": "high", "description": "d"}, {"severity": "low", "description": "d"}]),
        _stored("aud_2", OWNER, datetime(2026, 10, 2, 9), status="completed",
                completed_at=datetime(2026, 10, 6, 9), findings=[{"severity": "high", "description": "d"}]),
        _stored("aud_3", OWNER, datetime(2026, 10, 3, 9), status="in_progress", due_date="2099-03-01"),
        _stored("aud_4", OTHER, datetime(2026, 10, 3, 9), status="cancelled"),
    ])

    body = (await client.get("/partner/summary", headers=_auth(researcher_token))).json()
    assert body["tasks"] == {"total": 3, "by_status": {"open": 1, "in_progress": 1, "done": 1},
                             "overdue": 1, "next_due_date": "2020-01-01"}
    audits = body["audits"]
    assert audits["total"] == 3 and audits["pending"] == 2 and audits["overdue"] == 1
    assert audits["by_status"] == {"scheduled": 1, "in_progress": 1, "completed": 1, "cancelled": 0}
    assert audits["findings_by_severity"] == {"info": 0, "low": 1, "medium": 0, "high": 2, "critical": 0}
    assert audits["next_due_date"] == "2020-06-01"
    assert audits["last_completed_at"].startswith("2026-10-06T09:00:00")

    body = (await client.get("/partner/summary", params={"scope": "all"},
                             headers=_auth(company_owner_token))).json()
    assert body["tasks"]["total"] == 4
    assert body["audits"]["total"] == 4 and body["audits"]["by_status"]["cancelled"] == 1
