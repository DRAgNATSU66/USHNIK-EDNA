"""
GET /partner/incidents and GET /partner/tasks (t-1028-2, Industrial page).

Uses the in-memory Mongo from test_partner_audits (equality, dotted keys,
$gte/$lt, $in). Every expected count below is derived by hand from the seeded
documents, so a change to the incident or flag rules shows up here.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

import app.db.mongo as _mongo_module
from app.config import NOVELTY_THRESHOLD
from test_partner_audits import OTHER, OWNER, _auth, _FakeDb, company_owner_token  # noqa: F401  (fixture)


def _r(seq, *, rc="known_species", novelty=0.0, contaminated=False, ctype=None, decision=None):
    out = {"sequence_id": seq, "route": "fish", "result_class": rc, "novelty_score": novelty,
           "contamination_flagged": contaminated, "contamination_type": ctype}
    if decision is not None:
        out["decision"] = decision
    return out


@pytest.fixture
def db():
    fake = _FakeDb()
    fake["uploads"].docs.extend([
        {"upload_id": "upl_a", "user_id": OWNER, "original_filename": "outfall_a.fasta",
         "location_label": "Outfall A", "collected_at": datetime(2026, 9, 30, 7), "created_at": datetime(2026, 10, 1, 8)},
        {"upload_id": "upl_b", "user_id": OWNER, "original_filename": "berth_b.fasta",
         "created_at": datetime(2026, 10, 3, 8)},
        {"upload_id": "upl_c", "user_id": OWNER, "original_filename": "clean_c.fasta",
         "created_at": datetime(2026, 10, 4, 8)},
        {"upload_id": "upl_o", "user_id": OTHER, "original_filename": "other.fasta",
         "created_at": datetime(2026, 10, 2, 8)},
    ])
    fake["analysis_results"].docs.extend([
        # 2 contamination flags (human x2), 1 novelty flag (possible_novelty class).
        {"analysis_id": "ana_a", "upload_id": "upl_a", "user_id": OWNER, "created_at": datetime(2026, 10, 1, 9),
         "results": [
             _r("a1", rc="possible_contaminant", contaminated=True, ctype="human"),
             _r("a2", rc="possible_contaminant", contaminated=True, ctype="human"),
             _r("a3", rc="possible_novelty"),
             _r("a4"),
         ]},
        # No flags at all, but an open urgent review -> still an incident.
        # known_species with a high novelty_score is NOT a novelty flag
        # (worker summary rule); the decision's result_class is read first.
        {"analysis_id": "ana_b", "upload_id": "upl_b", "user_id": OWNER, "created_at": datetime(2026, 10, 3, 9),
         "results": [
             _r("b1", rc="possible_novelty", novelty=0.95, decision={"final_route": "fish",
                                                                       "result_class": "known_species"}),
         ]},
        # Clean: no flags, only a closed urgent review -> not an incident.
        {"analysis_id": "ana_c", "upload_id": "upl_c", "user_id": OWNER, "created_at": datetime(2026, 10, 4, 9),
         "results": [_r("c1"), _r("c2", rc="unknown_needs_online_confirmation", novelty=NOVELTY_THRESHOLD - 0.01)]},
        # Another user's flagged analysis: only in scope=all.
        {"analysis_id": "ana_o", "upload_id": "upl_o", "user_id": OTHER, "created_at": datetime(2026, 10, 2, 9),
         "results": [_r("o1", rc="unknown_needs_online_confirmation", novelty=NOVELTY_THRESHOLD)]},
    ])
    fake["reviews"].docs.extend([
        {"review_id": "rev_a_urgent", "analysis_id": "ana_a", "sequence_id": "a1", "review_type": "auto_contamination",
         "state": "submitted", "triage_priority": "urgent", "contamination_score": 0.9,
         "created_at": datetime(2026, 10, 1, 10)},
        {"review_id": "rev_a_normal", "analysis_id": "ana_a", "sequence_id": "a3", "review_type": "auto_novelty",
         "state": "triaged", "triage_priority": "normal", "created_at": datetime(2026, 10, 1, 10)},
        {"review_id": "rev_a_done", "analysis_id": "ana_a", "sequence_id": "a2", "review_type": "auto_contamination",
         "state": "accepted", "triage_priority": "urgent", "created_at": datetime(2026, 10, 1, 10)},
        {"review_id": "rev_b_urgent", "analysis_id": "ana_b", "sequence_id": "b1", "review_type": "manual_novelty",
         "state": "needs_evidence", "triage_priority": "urgent", "created_at": datetime(2026, 9, 30, 10)},
        {"review_id": "rev_c_closed", "analysis_id": "ana_c", "sequence_id": "c1", "review_type": "manual_correction",
         "state": "rejected", "triage_priority": "urgent", "created_at": datetime(2026, 10, 4, 10)},
    ])
    fake["field_log_entries"].docs.extend([
        {"entry_id": "t_done", "analysis_id": "ana_a", "kind": "task", "body": "Archive swabs", "task_status": "done",
         "due_date": "2020-01-01", "author_name": "R", "created_at": datetime(2026, 10, 1, 11), "edits": []},
        {"entry_id": "t_late", "analysis_id": "ana_a", "kind": "task", "body": "Re-extract a1",
         "task_status": "open", "due_date": "2020-02-01", "author_name": "R", "created_at": datetime(2026, 10, 1, 12),
         "edits": [{"edit_id": "e"}]},
        {"entry_id": "t_nodue", "analysis_id": "ana_b", "kind": "task", "body": "Call lab", "task_status": "in_progress",
         "author_name": "R", "created_at": datetime(2026, 10, 3, 12)},
        {"entry_id": "t_future", "analysis_id": "ana_c", "kind": "task", "body": "Resample", "task_status": "open",
         "due_date": "2099-01-01", "assignee": "Field team", "author_name": "R", "created_at": datetime(2026, 10, 4, 12)},
        {"entry_id": "n_note", "analysis_id": "ana_a", "kind": "note", "body": "not a task",
         "created_at": datetime(2026, 10, 1, 12)},
        {"entry_id": "t_other", "analysis_id": "ana_o", "kind": "task", "body": "Other user's", "task_status": "open",
         "created_at": datetime(2026, 10, 2, 12)},
    ])
    with patch.object(_mongo_module, "_db", fake):
        yield fake


# ---------------------------------------------------------------------------
# /partner/incidents
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_incidents_requires_auth(client):
    assert (await client.get("/partner/incidents")).status_code == 401
    assert (await client.get("/partner/tasks")).status_code == 401


@pytest.mark.anyio
async def test_incidents_empty_database(client, researcher_token):
    # conftest mock DB: every collection empty.
    resp = await client.get("/partner/incidents", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == body["analyses_in_scope"] == body["urgent_reviews_total"] == 0
    assert body["incidents"] == [] and body["urgent_reviews"] == []
    assert any("No analyses in this scope" in n for n in body["notes"])
    assert {"incident", "urgent_review", "contamination_flag", "novelty_flag"} <= set(body["definitions"])


@pytest.mark.anyio
async def test_incidents_own_scope(client, researcher_token, db):
    body = (await client.get("/partner/incidents", headers=_auth(researcher_token))).json()
    assert body["scope"] == {"mode": "mine", "user_id": OWNER, "date_from": None, "date_to": None}
    assert body["analyses_in_scope"] == 3
    # ana_c is clean; newest first.
    assert [i["analysis_id"] for i in body["incidents"]] == ["ana_b", "ana_a"]
    assert body["total"] == 2 and body["truncated"] is False
    assert body["contamination_flags"] == 2 and body["novelty_flags"] == 1

    b, a = body["incidents"]
    assert a["source_file"] == "outfall_a.fasta" and a["location_label"] == "Outfall A"
    assert a["collected_at"].startswith("2026-09-30T07:00")
    assert a["sequences"] == 4
    assert a["contamination_flags"] == 2 and a["novelty_flags"] == 1
    assert a["contamination_types"] == {"human": 2}
    assert a["open_reviews"] == 2 and a["urgent_open_reviews"] == 1  # accepted review is closed
    assert [(f["sequence_id"], f["flag"]) for f in a["flagged_sequences"]] == [
        ("a1", "contamination"), ("a2", "contamination"), ("a3", "novelty")]

    assert b["contamination_flags"] == 0 and b["novelty_flags"] == 0  # decision says known_species
    assert b["urgent_open_reviews"] == 1 and b["source_file"] == "berth_b.fasta" and b["location_label"] is None

    # Open urgent reviews only, oldest first.
    assert [r["review_id"] for r in body["urgent_reviews"]] == ["rev_b_urgent", "rev_a_urgent"]
    assert body["urgent_reviews_total"] == 2
    assert body["urgent_reviews"][1]["contamination_score"] == 0.9


@pytest.mark.anyio
async def test_incidents_scope_all_needs_privilege(client, researcher_token, company_owner_token, db):
    resp = await client.get("/partner/incidents", params={"scope": "all"}, headers=_auth(researcher_token))
    assert resp.status_code == 403
    resp = await client.get("/partner/incidents", params={"user_id": OTHER}, headers=_auth(researcher_token))
    assert resp.status_code == 403
    body = (await client.get("/partner/incidents", params={"scope": "all"},
                             headers=_auth(company_owner_token))).json()
    assert [i["analysis_id"] for i in body["incidents"]] == ["ana_b", "ana_o", "ana_a"]
    assert body["incidents"][1]["novelty_flags"] == 1  # novelty_score == threshold counts
    body = (await client.get("/partner/incidents", params={"user_id": OTHER},
                             headers=_auth(company_owner_token))).json()
    assert body["scope"]["mode"] == "user" and [i["analysis_id"] for i in body["incidents"]] == ["ana_o"]


@pytest.mark.anyio
async def test_incidents_date_window_and_limit(client, researcher_token, db):
    body = (await client.get("/partner/incidents", params={"date_from": "2026-10-02"},
                             headers=_auth(researcher_token))).json()
    assert [i["analysis_id"] for i in body["incidents"]] == ["ana_b"]
    assert body["analyses_in_scope"] == 2
    body = (await client.get("/partner/incidents", params={"limit": 1}, headers=_auth(researcher_token))).json()
    assert [i["analysis_id"] for i in body["incidents"]] == ["ana_b"]
    assert body["total"] == 2 and body["truncated"] is True
    assert len(body["urgent_reviews"]) == 1 and body["urgent_reviews_truncated"] is True
    assert any("1 newest of 2" in n for n in body["notes"])


@pytest.mark.anyio
async def test_incidents_none_flagged_note(client, researcher_token, db):
    body = (await client.get("/partner/incidents", params={"date_from": "2026-10-04"},
                             headers=_auth(researcher_token))).json()
    assert body["total"] == 0 and body["analyses_in_scope"] == 1
    assert any("None of the 1 analyses" in n for n in body["notes"])


@pytest.mark.anyio
@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 201}, {"scope": "everyone"}, {"date_from": "2026-10-05", "date_to": "2026-10-01"},
])
async def test_incidents_validation(client, researcher_token, params):
    resp = await client.get("/partner/incidents", params=params, headers=_auth(researcher_token))
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# /partner/tasks
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_tasks_empty_database(client, researcher_token):
    body = (await client.get("/partner/tasks", headers=_auth(researcher_token))).json()
    assert body["total"] == 0 and body["tasks"] == []


@pytest.mark.anyio
async def test_tasks_own_scope_order_and_overdue(client, researcher_token, db):
    body = (await client.get("/partner/tasks", headers=_auth(researcher_token))).json()
    # Not done first, earliest due first, no due date last among not-done, done last.
    assert [t["entry_id"] for t in body["tasks"]] == ["t_late", "t_future", "t_nodue", "t_done"]
    assert body["total"] == 4
    by_id = {t["entry_id"]: t for t in body["tasks"]}
    assert by_id["t_late"]["overdue"] is True
    assert by_id["t_done"]["overdue"] is False  # done tasks are never overdue
    assert by_id["t_future"]["overdue"] is False and by_id["t_future"]["assignee"] == "Field team"
    assert "edits" not in by_id["t_late"]


@pytest.mark.anyio
async def test_tasks_filters(client, researcher_token, company_owner_token, db):
    body = (await client.get("/partner/tasks", params={"status": "open"}, headers=_auth(researcher_token))).json()
    assert [t["entry_id"] for t in body["tasks"]] == ["t_late", "t_future"]
    body = (await client.get("/partner/tasks", params={"limit": 1}, headers=_auth(researcher_token))).json()
    assert body["total"] == 4 and body["truncated"] is True and len(body["tasks"]) == 1
    body = (await client.get("/partner/tasks", params={"scope": "all"}, headers=_auth(company_owner_token))).json()
    assert "t_other" in [t["entry_id"] for t in body["tasks"]] and body["total"] == 5
    resp = await client.get("/partner/tasks", params={"scope": "all"}, headers=_auth(researcher_token))
    assert resp.status_code == 403
    resp = await client.get("/partner/tasks", params={"status": "blocked"}, headers=_auth(researcher_token))
    assert resp.status_code == 422
