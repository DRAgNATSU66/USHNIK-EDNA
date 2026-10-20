"""
GET /partner/hotspots and GET /partner/alerts (t-1027-3, M2; app/partner/regional.py).

Same approach as test_partner_summary.py: the conftest mock DB covers the
empty case; the rest patch in a small in-memory Mongo supporting equality,
$gte/$lt and $in, and recording projections.
"""
from __future__ import annotations

import copy
from datetime import datetime
from unittest.mock import patch

import pytest

import app.db.mongo as _mongo_module
from app.auth.jwt import create_access_token
from app.config import NOVELTY_THRESHOLD
from app.models.user import UserRole
from app.partner.regional import cell_index

OWNER = "usr_test_001"  # researcher_token's user (conftest)
OTHER = "usr_other"


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


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._docs:
            return copy.deepcopy(self._docs.pop(0))
        raise StopAsyncIteration


class _Collection:
    def __init__(self):
        self.docs: list[dict] = []
        self.projections: list[dict] = []

    def find(self, flt=None, projection=None):
        self.projections.append(projection)
        return _Cursor(d for d in self.docs if all(_cmp(d.get(k), v) for k, v in (flt or {}).items()))


class _FakeDb:
    def __init__(self):
        self.collections: dict[str, _Collection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.fixture
def db():
    fake = _FakeDb()
    with patch.object(_mongo_module, "_db", fake):
        yield fake


@pytest.fixture
def company_owner_token():
    return create_access_token(
        "usr_company_001",
        {"email": "owner@example.com", "role": UserRole.company_owner, "name": "Company Owner"},
    )


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seq(rc="known_species", taxon=None, novelty=0.0, contam=False, ctype=None, decision=None):
    r = {"sequence_id": "s", "route": "fish", "result_class": rc, "predicted_taxon": taxon,
         "novelty_score": novelty, "contamination_flagged": contam, "embedding": [0.1] * 4}
    if ctype is not None:
        r["contamination_type"] = ctype
    if decision is not None:
        r["decision"] = decision
    return r


def _seed(db):
    db["uploads"].docs.extend([
        # upl_a and upl_c share the 1-degree cell 15:82; upl_d is in 10:80.
        {"upload_id": "upl_a", "user_id": OWNER, "created_at": datetime(2026, 10, 1, 8),
         "latitude": 15.6, "longitude": 82.3, "collected_at": datetime(2026, 10, 1, 6),
         "location_label": "Visakhapatnam", "original_filename": "a.fasta"},
        {"upload_id": "upl_c", "user_id": OWNER, "created_at": datetime(2026, 10, 4, 8),
         "latitude": 15.1, "longitude": 82.9, "collected_at": datetime(2026, 10, 3, 6),
         "location_label": "Kakinada"},
        {"upload_id": "upl_d", "user_id": OWNER, "created_at": datetime(2026, 10, 5, 8),
         "latitude": 10.0, "longitude": 80.0},
        {"upload_id": "upl_b", "user_id": OWNER, "created_at": datetime(2026, 10, 3, 8)},  # no coordinates
        {"upload_id": "upl_bad", "user_id": OWNER, "created_at": datetime(2026, 10, 3, 9),
         "latitude": 95.0, "longitude": 10.0},
        {"upload_id": "upl_x", "user_id": OTHER, "created_at": datetime(2026, 10, 2, 8),
         "latitude": 15.5, "longitude": 82.5},
    ])
    db["analysis_results"].docs.extend([
        {"analysis_id": "ana_a", "upload_id": "upl_a", "user_id": OWNER, "created_at": datetime(2026, 10, 1, 9),
         "results": [
             _seq("known_species", taxon="Sardinella longiceps"),
             _seq("possible_novelty", novelty=0.2),
             _seq("likely_taxonomic_group", novelty=NOVELTY_THRESHOLD, contam=True, ctype="bacterial"),
             _seq("unknown_needs_online_confirmation", decision={
                 "final_route": "fish", "result_class": "known_species",
                 "predicted_taxon": "Rastrelliger kanagurta", "taxon_rank": "species"}),
         ]},
        {"analysis_id": "ana_c", "upload_id": "upl_c", "user_id": OWNER, "created_at": datetime(2026, 10, 4, 9),
         "results": [_seq("known_species", taxon="Sardinella longiceps"),
                     _seq("possible_contamination", contam=True)]},
        # Clean analysis: no flags, no urgent review -> mapped but not an alert.
        {"analysis_id": "ana_d", "upload_id": "upl_d", "user_id": OWNER, "created_at": datetime(2026, 10, 5, 9),
         "results": [_seq("known_species", taxon="Thunnus albacares")]},
        # Unmapped upload, but an open urgent review -> urgent alert.
        {"analysis_id": "ana_b", "upload_id": "upl_b", "user_id": OWNER, "created_at": datetime(2026, 10, 3, 9),
         "results": [_seq("known_species", taxon="Thunnus albacares")]},
        {"analysis_id": "ana_x", "upload_id": "upl_x", "user_id": OTHER, "created_at": datetime(2026, 10, 2, 9),
         "results": [_seq("possible_contamination", contam=True)]},
    ])
    db["reviews"].docs.extend([
        {"review_id": "r1", "analysis_id": "ana_a", "state": "submitted", "review_type": "auto_novelty",
         "triage_priority": "urgent"},
        {"review_id": "r2", "analysis_id": "ana_a", "state": "accepted", "review_type": "auto_contamination",
         "triage_priority": "urgent"},  # closed: not counted
        {"review_id": "r3", "analysis_id": "ana_c", "state": "triaged", "review_type": "manual_correction",
         "triage_priority": "normal"},
        {"review_id": "r4", "analysis_id": "ana_b", "state": "needs_evidence", "review_type": "auto_contamination",
         "triage_priority": "urgent"},
        {"review_id": "r5", "analysis_id": "ana_x", "state": "submitted", "review_type": "auto_contamination",
         "triage_priority": "urgent"},
    ])


# ---------------------------------------------------------------------------
# Auth + validation
# ---------------------------------------------------------------------------

@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/partner/hotspots", "/partner/alerts"])
async def test_requires_auth(client, path):
    resp = await client.get(path)
    assert resp.status_code in (401, 403)


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/partner/hotspots", "/partner/alerts"])
async def test_researcher_cannot_read_all_or_others(client, researcher_token, path):
    assert (await client.get(path, params={"scope": "all"}, headers=_auth(researcher_token))).status_code == 403
    assert (await client.get(path, params={"user_id": OTHER}, headers=_auth(researcher_token))).status_code == 403


@pytest.mark.anyio
@pytest.mark.parametrize("path,params", [
    ("/partner/hotspots", {"cell_deg": 0.01}),
    ("/partner/hotspots", {"cell_deg": 11}),
    ("/partner/hotspots", {"date_from": "2026-10-05", "date_to": "2026-10-01"}),
    ("/partner/alerts", {"limit": 0}),
    ("/partner/alerts", {"limit": 201}),
    ("/partner/alerts", {"date_from": "2026-10-05", "date_to": "2026-10-01"}),
])
async def test_validation_errors(client, researcher_token, path, params):
    resp = await client.get(path, params=params, headers=_auth(researcher_token))
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_empty_database(client, researcher_token):
    hs = (await client.get("/partner/hotspots", headers=_auth(researcher_token))).json()
    assert hs["cells"] == [] and hs["coverage"]["uploads_in_scope"] == 0
    assert hs["cell_deg"] == 1.0 and "cell" in hs["definitions"]
    assert any("No uploads" in n for n in hs["notes"])
    al = (await client.get("/partner/alerts", headers=_auth(researcher_token))).json()
    assert al["alerts"] == [] and al["total"] == 0 and al["truncated"] is False
    assert {"alert", "priority", "novelty_flag", "contamination_flag"} <= set(al["definitions"])
    assert any("No analyses" in n for n in al["notes"])


# ---------------------------------------------------------------------------
# Hotspots
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_hotspots_aggregate_own_uploads_into_cells(client, researcher_token, db):
    _seed(db)
    resp = await client.get("/partner/hotspots", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["coverage"] == {
        "uploads_in_scope": 5, "uploads_with_coordinates": 3, "uploads_without_coordinates": 1,
        "uploads_invalid_coordinates": 1, "analyses_in_scope": 4, "analyses_mapped": 3,
    }
    cells = {c["cell_id"]: c for c in body["cells"]}
    assert set(cells) == {"15:82", "10:80"}
    c = cells["15:82"]
    assert (c["lat_min"], c["lat_max"], c["lng_min"], c["lng_max"]) == (15.0, 16.0, 82.0, 83.0)
    assert (c["center_lat"], c["center_lng"]) == (15.5, 82.5)
    assert c["uploads"] == 2 and c["analyses"] == 2 and c["sequences"] == 6
    # possible_novelty + likely_taxonomic_group at the threshold (decision-first: the
    # unknown_needs_online_confirmation row became known_species)
    assert c["novelty_flags"] == 2 and c["contamination_flags"] == 2
    assert c["sequences_with_taxon"] == 3 and c["distinct_taxa"] == 2
    assert c["top_taxa"][0] == {"taxon": "Sardinella longiceps", "taxon_rank": None, "sequences": 2}
    assert c["open_reviews"] == 2 and c["open_urgent_reviews"] == 1
    assert c["upload_ids"] == ["upl_c", "upl_a"]  # newest first
    assert c["location_labels"] == ["Kakinada", "Visakhapatnam"]
    assert c["first_collected_at"].startswith("2026-10-01T06:00")
    assert c["last_collected_at"].startswith("2026-10-03T06:00")
    # urgent cell sorts first
    assert body["cells"][0]["cell_id"] == "15:82"
    assert cells["10:80"]["novelty_flags"] == 0 and cells["10:80"]["distinct_taxa"] == 1

    notes = " ".join(body["notes"])
    assert "1 upload(s) in scope have no coordinates" in notes
    assert "outside [-90, 90]" in notes
    assert "1 analysis(es) in scope belong to uploads that are unmapped" in notes


@pytest.mark.anyio
async def test_hotspots_never_fetch_embeddings(client, researcher_token, db):
    _seed(db)
    await client.get("/partner/hotspots", headers=_auth(researcher_token))
    proj = db["analysis_results"].projections[0]
    assert proj["_id"] == 0 and "results.contamination_type" in proj
    assert not any("embedding" in k for k in proj) and "results" not in proj


@pytest.mark.anyio
async def test_hotspots_cell_size_and_date_range(client, researcher_token, db):
    _seed(db)
    body = (await client.get("/partner/hotspots", params={"cell_deg": 10},
                             headers=_auth(researcher_token))).json()
    # 15.6/82.3, 15.1/82.9 and 10.0/80.0 all fall in [10, 20) x [80, 90)
    assert [(c["cell_id"], c["uploads"]) for c in body["cells"]] == [("1:8", 3)]
    assert body["cell_deg"] == 10

    body = (await client.get("/partner/hotspots", params={"date_from": "2026-10-04"},
                             headers=_auth(researcher_token))).json()
    assert {c["cell_id"] for c in body["cells"]} == {"15:82", "10:80"}
    assert body["coverage"]["uploads_in_scope"] == 2


@pytest.mark.anyio
async def test_hotspots_company_owner_scope_all(client, company_owner_token, db):
    _seed(db)
    body = (await client.get("/partner/hotspots", params={"scope": "all"},
                             headers=_auth(company_owner_token))).json()
    assert body["scope"]["mode"] == "all"
    cell = next(c for c in body["cells"] if c["cell_id"] == "15:82")
    assert cell["uploads"] == 3 and cell["open_urgent_reviews"] == 2


def test_cell_index_edges():
    assert cell_index(15.6, 82.3, 1.0) == (15, 82)
    assert cell_index(-0.5, -0.5, 1.0) == (-1, -1)
    assert cell_index(90, 180, 1.0) == (89, 179)
    assert cell_index(-90, -180, 1.0) == (-90, -180)
    assert cell_index(90, 180, 0.25) == (359, 719)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_alerts_from_real_flags(client, researcher_token, db):
    _seed(db)
    resp = await client.get("/partner/alerts", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["analyses_in_scope"] == 4 and body["total"] == 3 and body["urgent"] == 2
    # urgent first (newest first within), then flagged; clean ana_d is not an alert
    assert [(a["analysis_id"], a["priority"]) for a in body["alerts"]] == [
        ("ana_b", "urgent"), ("ana_a", "urgent"), ("ana_c", "flagged"),
    ]
    a = body["alerts"][1]
    assert a["reasons"] == ["open_urgent_review", "contamination_flags", "novelty_flags"]
    assert a["novelty_flags"] == 2 and a["contamination_flags"] == 1
    assert a["contamination_types"] == {"bacterial": 1}
    assert a["open_reviews"] == 1 and a["open_urgent_reviews"] == 1
    assert a["open_reviews_by_type"] == {"auto_novelty": 1}
    assert (a["latitude"], a["longitude"], a["location_label"]) == (15.6, 82.3, "Visakhapatnam")
    assert a["original_filename"] == "a.fasta" and a["upload_found"] is True

    b = body["alerts"][0]
    assert b["reasons"] == ["open_urgent_review"] and b["latitude"] is None
    c = body["alerts"][2]
    assert c["reasons"] == ["contamination_flags"] and c["contamination_types"] == {"unrecorded": 1}
    assert c["open_reviews"] == 1 and c["open_urgent_reviews"] == 0


@pytest.mark.anyio
async def test_alerts_limit_and_missing_upload(client, researcher_token, db):
    _seed(db)
    db["uploads"].docs = [u for u in db["uploads"].docs if u["upload_id"] != "upl_c"]
    body = (await client.get("/partner/alerts", params={"limit": 1}, headers=_auth(researcher_token))).json()
    assert body["total"] == 3 and body["truncated"] is True and len(body["alerts"]) == 1
    notes = " ".join(body["notes"])
    assert "first 1 of 3" in notes and "no longer exists" in notes


@pytest.mark.anyio
async def test_alerts_none_flagged_says_so(client, researcher_token, db):
    db["analysis_results"].docs.append({"analysis_id": "ana_ok", "upload_id": "upl_ok", "user_id": OWNER,
                                        "created_at": datetime(2026, 10, 1), "results": [_seq()]})
    body = (await client.get("/partner/alerts", headers=_auth(researcher_token))).json()
    assert body["alerts"] == [] and body["analyses_in_scope"] == 1
    assert any("None of the 1 analyses" in n for n in body["notes"])
