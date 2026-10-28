"""
GET /partner/summary (t-1026-2, B16).

The conftest mock DB returns an empty cursor for every find, which covers the
empty-database case; the rest patch in a small in-memory Mongo that supports
the filters the summary uses (equality, $gte/$lt on created_at, $in) and
records the projections it was asked for.
"""
from __future__ import annotations

import copy
from datetime import date, datetime
from unittest.mock import patch

import pytest

import app.db.mongo as _mongo_module
from app.auth.jwt import create_access_token
from app.config import NOVELTY_THRESHOLD
from app.environment.models import GridPoint, PublicValue, PublicVariableResult
from app.models.analysis import SequenceResultClass, TaxonomicRoute
from app.models.review import ReviewState
from app.models.user import UserRole

OWNER = "usr_test_001"  # researcher_token's user (conftest)
OTHER = "usr_other"


# ---------------------------------------------------------------------------
# In-memory Mongo
# ---------------------------------------------------------------------------

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
    return all(_cmp(doc.get(k), v) for k, v in flt.items())


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
        return _Cursor(d for d in self.docs if _matches(d, flt or {}))


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


def _seq(route="fish", rc="known_species", taxon=None, novelty=0.0, contam=False, decision=None):
    r = {"sequence_id": "s", "route": route, "result_class": rc, "predicted_taxon": taxon,
         "novelty_score": novelty, "contamination_flagged": contam, "embedding": [0.1] * 4}
    if decision is not None:
        r["decision"] = decision
    return r


def _public(provider="noaa_erddap", value=28.4):
    return PublicVariableResult(status="ok", value=PublicValue(
        value=value, unit="°C", provider=provider, source="NOAA OISST", dataset_id="ncdcOisst21Agg",
        source_variable="sst", query_url="https://example.invalid/erddap", access="public_api",
        grid_point=GridPoint(latitude=15.625, longitude=82.375, time="2026-10-01T12:00:00Z"),
        retrieved_at=datetime(2026, 10, 2, 9, 30), licence="public domain", attribution="NOAA",
    )).model_dump(mode="json")


def _seed(db):
    db["uploads"].docs.extend([
        {"upload_id": "upl_a", "user_id": OWNER, "created_at": datetime(2026, 10, 1, 8),
         "latitude": 15.6, "longitude": 82.3, "collected_at": datetime(2026, 10, 1, 6),
         "location_label": "Visakhapatnam", "temperature_celsius": 27.0},
        {"upload_id": "upl_b", "user_id": OWNER, "created_at": datetime(2026, 10, 3, 8)},  # no coordinates
        {"upload_id": "upl_x", "user_id": OTHER, "created_at": datetime(2026, 10, 2, 8),
         "latitude": 10.0, "longitude": 80.0, "collected_at": datetime(2026, 10, 2, 6)},
    ])
    db["analysis_results"].docs.extend([
        {"analysis_id": "ana_a", "upload_id": "upl_a", "user_id": OWNER, "created_at": datetime(2026, 10, 1, 9),
         "results": [
             _seq("fish", "known_species", taxon="Sardinella longiceps"),
             # known_species is never a novelty flag, whatever its score
             _seq("fish", "known_species", taxon="Sardinella longiceps", novelty=0.99),
             _seq("misc_unknown", "possible_novelty", novelty=0.2),
             _seq("bacteria_pathogen", "likely_taxonomic_group", novelty=NOVELTY_THRESHOLD, contam=True),
             _seq("low_quality", "low_quality_unusable"),
             # orchestrator decision overrides the legacy route/class/taxon
             _seq("misc_unknown", "unknown_needs_online_confirmation", decision={
                 "final_route": "fish", "result_class": "known_species",
                 "predicted_taxon": "Rastrelliger kanagurta", "taxon_rank": "species"}),
         ]},
        {"analysis_id": "ana_b", "upload_id": "upl_b", "user_id": OWNER, "created_at": datetime(2026, 10, 3, 9),
         "results": [_seq("plant", "likely_taxonomic_group", taxon="Sardinella longiceps")]},
        {"analysis_id": "ana_x", "upload_id": "upl_x", "user_id": OTHER, "created_at": datetime(2026, 10, 2, 9),
         "results": [_seq("fish", "possible_contamination", contam=True)]},
    ])
    db["reviews"].docs.extend([
        {"review_id": "r1", "analysis_id": "ana_a", "state": "submitted", "review_type": "auto_novelty"},
        {"review_id": "r2", "analysis_id": "ana_a", "state": "accepted", "review_type": "auto_contamination"},
        {"review_id": "r3", "analysis_id": "ana_b", "state": "triaged", "review_type": "manual_correction"},
        {"review_id": "r4", "analysis_id": "ana_x", "state": "submitted", "review_type": "auto_contamination"},
    ])
    db["environment_contexts"].docs.append({
        "upload_id": "upl_a", "user_id": OWNER, "status": "partial",
        "query": {"lookup_latitude": 15.6, "lookup_longitude": 82.3, "date": "2026-10-01", "depth_m": None},
        "public": {"temperature": _public()},
        "retrieved_at": datetime(2026, 10, 2, 9, 30), "requested_at": datetime(2026, 10, 2, 9, 29),
    })


# ---------------------------------------------------------------------------
# Auth + validation
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_summary_requires_auth(client):
    resp = await client.get("/partner/summary")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_researcher_cannot_summarise_all_users(client, researcher_token):
    resp = await client.get("/partner/summary", params={"scope": "all"}, headers=_auth(researcher_token))
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_researcher_cannot_summarise_another_user(client, researcher_token):
    resp = await client.get("/partner/summary", params={"user_id": OTHER}, headers=_auth(researcher_token))
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_curator_is_not_an_all_data_role(client, curator_token):
    resp = await client.get("/partner/summary", params={"scope": "all"}, headers=_auth(curator_token))
    assert resp.status_code == 403


@pytest.mark.anyio
@pytest.mark.parametrize("params", [
    {"date_from": "2026-10-05", "date_to": "2026-10-01"},
    {"date_from": "not-a-date"},
    {"interval": "hour"},
    {"scope": "everyone"},
    {"top_taxa": 0},
    {"top_taxa": 51},
])
async def test_summary_validation_errors(client, researcher_token, params):
    resp = await client.get("/partner/summary", params=params, headers=_auth(researcher_token))
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Empty database
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_empty_database_is_zeros_with_a_note(client, researcher_token):
    resp = await client.get("/partner/summary", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == {"mode": "mine", "user_id": OWNER, "date_from": None, "date_to": None, "interval": "day"}
    assert set(body["totals"].values()) == {0}
    assert body["time_series"] == []
    assert body["top_taxa"] == []
    assert body["sites"] == [] and body["sites_truncated"] is False
    assert body["route_distribution"] == {r.value: 0 for r in TaxonomicRoute}
    assert body["result_class_distribution"] == {c.value: 0 for c in SequenceResultClass}
    assert body["reviews"] == {"total": 0, "open": 0, "by_state": {s.value: 0 for s in ReviewState}, "by_type": {}}
    env = body["environment"]
    assert env["uploads_in_scope"] == env["eligible"] == 0 and env["sources"] == []
    assert any("every count is zero" in n for n in body["notes"])
    assert "novelty_flag" in body["definitions"]


@pytest.mark.anyio
async def test_empty_range_with_bounds_is_zero_filled(client, researcher_token, db):
    resp = await client.get("/partner/summary", params={"date_from": "2026-10-01", "date_to": "2026-10-03"},
                            headers=_auth(researcher_token))
    series = resp.json()["time_series"]
    assert [p["period_start"] for p in series] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert all(p["uploads"] == p["analyses"] == 0 for p in series)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_summary_counts_own_data(client, researcher_token, db):
    _seed(db)
    resp = await client.get("/partner/summary", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["totals"] == {
        "uploads": 2, "analyses": 2, "sequences": 7, "sequences_with_taxon": 4,
        # possible_novelty (score 0.2) + likely_taxonomic_group at the threshold
        "novelty_flags": 2, "contamination_flags": 1, "low_quality": 1,
        "analyses_with_novelty_flags": 1, "analyses_with_contamination_flags": 1,
    }
    routes = body["route_distribution"]
    assert routes["fish"] == 3 and routes["misc_unknown"] == 1 and routes["plant"] == 1
    assert routes["bacteria_pathogen"] == 1 and routes["low_quality"] == 1
    assert body["result_class_distribution"]["known_species"] == 3
    assert body["result_class_distribution"]["unknown_needs_online_confirmation"] == 0

    assert body["top_taxa"] == [
        {"taxon": "Sardinella longiceps", "taxon_rank": None, "sequences": 3, "analyses": 2},
        {"taxon": "Rastrelliger kanagurta", "taxon_rank": "species", "sequences": 1, "analyses": 1},
    ]

    rv = body["reviews"]
    assert rv["total"] == 3 and rv["open"] == 2
    assert rv["by_state"]["submitted"] == 1 and rv["by_state"]["accepted"] == 1 and rv["by_state"]["triaged"] == 1
    assert rv["by_type"] == {"auto_novelty": 1, "auto_contamination": 1, "manual_correction": 1}

    assert [(p["period_start"], p["uploads"], p["analyses"], p["sequences"]) for p in body["time_series"]] == [
        ("2026-10-01", 1, 1, 6), ("2026-10-02", 0, 0, 0), ("2026-10-03", 1, 1, 1),
    ]
    assert body["time_series"][0]["novelty_flags"] == 2 and body["time_series"][0]["contamination_flags"] == 1

    env = body["environment"]
    assert env["uploads_in_scope"] == 2 and env["eligible"] == 1 and env["not_applicable"] == 1
    assert env["by_status"]["partial"] == 1
    # user-entered temperature wins over the public value; the rest were not looked up
    assert env["variables"]["temperature"] == {"ok": 0, "user_provided": 1, "unavailable": 0}
    assert env["variables"]["salinity"] == {"ok": 0, "user_provided": 0, "unavailable": 1}
    assert [s["provider"] for s in env["sources"]] == ["noaa_erddap"]
    assert env["sources"][0]["uploads"] == 1
    assert env["latest_retrieved_at"].startswith("2026-10-02T09:30")

    assert len(body["sites"]) == 1
    site = body["sites"][0]
    assert site["upload_id"] == "upl_a" and site["analyses"] == 1 and site["sequences"] == 6
    assert site["novelty_flags"] == 2 and site["contamination_flags"] == 1
    assert site["environment_status"] == "partial" and site["environment_providers"] == ["noaa_erddap"]


@pytest.mark.anyio
async def test_summary_never_fetches_embeddings(client, researcher_token, db):
    _seed(db)
    await client.get("/partner/summary", headers=_auth(researcher_token))
    proj = db["analysis_results"].projections[0]
    assert proj["_id"] == 0 and "results.route" in proj
    assert not any("embedding" in k for k in proj) and "results" not in proj


@pytest.mark.anyio
async def test_no_taxa_gives_an_explicit_note(client, researcher_token, db):
    db["analysis_results"].docs.append({
        "analysis_id": "ana_n", "upload_id": "upl_n", "user_id": OWNER, "created_at": datetime(2026, 10, 1),
        "results": [_seq(), _seq()],
    })
    body = (await client.get("/partner/summary", headers=_auth(researcher_token))).json()
    assert body["top_taxa"] == []
    assert any("None of the 2 sequences" in n for n in body["notes"])


@pytest.mark.anyio
async def test_eligible_upload_without_lookup_is_not_requested(client, researcher_token, db):
    db["uploads"].docs.append({"upload_id": "upl_q", "user_id": OWNER, "created_at": datetime(2026, 10, 1),
                               "latitude": 1.0, "longitude": 2.0, "collected_at": datetime(2026, 9, 30)})
    body = (await client.get("/partner/summary", headers=_auth(researcher_token))).json()
    assert body["environment"]["by_status"]["not_requested"] == 1
    assert body["sites"][0]["environment_status"] == "not_requested"
    assert body["sites"][0]["environment_retrieved_at"] is None


@pytest.mark.anyio
async def test_date_range_filters_and_week_buckets(client, researcher_token, db):
    _seed(db)
    resp = await client.get("/partner/summary",
                            params={"date_from": "2026-10-02", "date_to": "2026-10-03", "interval": "week"},
                            headers=_auth(researcher_token))
    body = resp.json()
    assert body["totals"]["uploads"] == 1 and body["totals"]["analyses"] == 1  # upl_b / ana_b only
    assert body["reviews"]["total"] == 1
    # 2026-10-02 is a Friday: its ISO week starts Monday 2026-09-28
    assert [p["period_start"] for p in body["time_series"]] == ["2026-09-28"]


@pytest.mark.anyio
async def test_date_to_is_inclusive(client, researcher_token, db):
    _seed(db)
    body = (await client.get("/partner/summary", params={"date_to": "2026-10-01"},
                             headers=_auth(researcher_token))).json()
    assert body["totals"]["uploads"] == 1 and body["totals"]["analyses"] == 1


@pytest.mark.anyio
async def test_month_interval(client, researcher_token, db):
    _seed(db)
    body = (await client.get("/partner/summary", params={"interval": "month"},
                             headers=_auth(researcher_token))).json()
    assert body["time_series"] == [{"period_start": "2026-10-01", "uploads": 2, "analyses": 2, "sequences": 7,
                                    "novelty_flags": 2, "contamination_flags": 1}]


@pytest.mark.anyio
async def test_company_owner_scope_all_and_single_user(client, company_owner_token, db):
    _seed(db)
    body = (await client.get("/partner/summary", params={"scope": "all"},
                             headers=_auth(company_owner_token))).json()
    assert body["scope"]["mode"] == "all" and body["scope"]["user_id"] is None
    assert body["totals"]["uploads"] == 3 and body["totals"]["analyses"] == 3
    assert body["reviews"]["total"] == 4
    assert body["environment"]["by_status"]["not_requested"] == 1  # upl_x

    one = (await client.get("/partner/summary", params={"user_id": OTHER},
                            headers=_auth(company_owner_token))).json()
    assert one["scope"]["mode"] == "user" and one["scope"]["user_id"] == OTHER
    assert one["totals"]["analyses"] == 1 and one["totals"]["contamination_flags"] == 1


@pytest.mark.anyio
async def test_own_user_id_is_allowed_for_anyone(client, researcher_token, db):
    _seed(db)
    resp = await client.get("/partner/summary", params={"user_id": OWNER}, headers=_auth(researcher_token))
    assert resp.status_code == 200
    assert resp.json()["totals"]["analyses"] == 2


def test_period_start_helpers():
    from app.partner.summary import _next_period, period_start
    assert period_start(date(2026, 10, 19), "week") == date(2026, 10, 19)  # Monday
    assert period_start(date(2026, 10, 25), "week") == date(2026, 10, 19)
    assert _next_period(date(2026, 12, 1), "month") == date(2027, 1, 1)
