"""
GET /partner/cooccurrence and GET /partner/rhythms (t-1027-1, M3).

The conftest mock DB returns an empty cursor for every find (empty-database
case); the rest patch in a small in-memory Mongo supporting the filters these
endpoints use (equality, $gte/$lt on created_at, $in on upload_id) and
recording the projections asked for.
"""
from __future__ import annotations

import copy
from datetime import datetime
from unittest.mock import patch

import pytest

import app.db.mongo as _mongo_module
from app.auth.jwt import create_access_token
from app.models.user import UserRole
from app.partner import community

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
        self.queries: list[tuple[dict, dict]] = []

    def find(self, flt=None, projection=None):
        self.queries.append((flt, projection))
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


def _seq(taxon=None, rank=None, contam=False, legacy=False):
    r = {"sequence_id": "s", "predicted_taxon": None, "contamination_flagged": contam, "embedding": [0.1] * 4}
    if legacy:
        r["predicted_taxon"] = taxon
    else:
        r["decision"] = {"predicted_taxon": taxon, "taxon_rank": rank}
    return r


def _sp(name, n=1):
    return [_seq(name, "species") for _ in range(n)]


def _seed(db):
    db["uploads"].docs.extend([
        # Thursday 06:00 UTC collection
        {"upload_id": "upl_1", "user_id": OWNER, "created_at": datetime(2026, 10, 2, 8),
         "collected_at": datetime(2026, 10, 1, 6)},
        # no collected_at: placed by upload time, Saturday 08:00
        {"upload_id": "upl_2", "user_id": OWNER, "created_at": datetime(2026, 10, 3, 8)},
        # no analysis yet; Monday 22:30 collection
        {"upload_id": "upl_3", "user_id": OWNER, "created_at": datetime(2026, 10, 6, 8),
         "collected_at": datetime(2026, 10, 5, 22, 30)},
        {"upload_id": "upl_x", "user_id": OTHER, "created_at": datetime(2026, 10, 2, 8),
         "collected_at": datetime(2026, 10, 1, 6)},
    ])
    db["analysis_results"].docs.extend([
        # older run of upl_1: must be ignored
        {"analysis_id": "ana_1_old", "upload_id": "upl_1", "user_id": OWNER, "created_at": datetime(2026, 10, 2, 9),
         "results": _sp("Old taxon") + _sp("Other old taxon")},
        {"analysis_id": "ana_1_new", "upload_id": "upl_1", "user_id": OWNER, "created_at": datetime(2026, 10, 4, 9),
         "results": _sp("Alpha a", 2) + _sp("Beta b") + _sp("Gamma c") + [
             _seq("Genusia", "genus"),
             _seq("Homo sapiens", "species", contam=True),
             _seq("Legacyus fish", legacy=True),
             _seq(None, None),
         ]},
        {"analysis_id": "ana_2", "upload_id": "upl_2", "user_id": OWNER, "created_at": datetime(2026, 10, 3, 9),
         "results": _sp("Alpha a") + _sp("Beta b")},
        {"analysis_id": "ana_x", "upload_id": "upl_x", "user_id": OTHER, "created_at": datetime(2026, 10, 2, 9),
         "results": _sp("Alpha a") + _sp("Beta b") + _sp("Delta d")},
    ])


# ---------------------------------------------------------------------------
# Auth + validation
# ---------------------------------------------------------------------------

@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/partner/cooccurrence", "/partner/rhythms"])
async def test_requires_auth(client, path):
    assert (await client.get(path)).status_code == 401


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/partner/cooccurrence", "/partner/rhythms"])
@pytest.mark.parametrize("params", [{"scope": "all"}, {"user_id": OTHER}])
async def test_researcher_cannot_read_others(client, researcher_token, path, params):
    resp = await client.get(path, params=params, headers=_auth(researcher_token))
    assert resp.status_code == 403


@pytest.mark.anyio
@pytest.mark.parametrize("path,params", [
    ("/partner/cooccurrence", {"date_from": "2026-10-05", "date_to": "2026-10-01"}),
    ("/partner/cooccurrence", {"rank": "subspecies"}),
    ("/partner/cooccurrence", {"limit": 0}),
    ("/partner/cooccurrence", {"limit": 51}),
    ("/partner/rhythms", {"date_from": "2026-10-05", "date_to": "2026-10-01"}),
    ("/partner/rhythms", {"scope": "everyone"}),
])
async def test_validation_errors(client, researcher_token, path, params):
    resp = await client.get(path, params=params, headers=_auth(researcher_token))
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Empty database
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_cooccurrence_empty_database(client, researcher_token):
    resp = await client.get("/partner/cooccurrence", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == {"mode": "mine", "user_id": OWNER, "date_from": None, "date_to": None}
    assert body["rank"] == "species"
    assert body["samples"] == body["pairs_total"] == 0 and body["pairs"] == [] and body["nodes"] == []
    assert body["notes"] == ["No uploads in this scope and date range."]
    assert {"sample", "taxon", "rank", "samples_together", "jaccard", "interpretation"} <= set(body["definitions"])


@pytest.mark.anyio
async def test_rhythms_empty_database(client, researcher_token):
    resp = await client.get("/partner/rhythms", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["timezone"] == "UTC"
    assert [b["label"] for b in body["by_hour"]] == [f"{h:02d}:00" for h in range(24)]
    assert [b["label"] for b in body["by_weekday"]] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert set(body["totals"].values()) == {0}
    assert all(b["uploads"] == b["detections"] == 0 for b in body["by_hour"] + body["by_weekday"])
    assert any("every count is zero" in n for n in body["notes"])


# ---------------------------------------------------------------------------
# Co-occurrence
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_cooccurrence_counts_species_pairs_per_sample(client, researcher_token, db):
    _seed(db)
    resp = await client.get("/partner/cooccurrence", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["uploads_in_scope"] == 3
    assert body["samples"] == 2  # upl_3 has no analysis
    assert body["samples_with_taxa"] == 2
    assert body["taxa"] == 3  # Alpha, Beta, Gamma; not the old run, the genus, the contaminant, the legacy taxon
    assert body["contamination_sequences_excluded"] == 1
    assert body["taxa_by_rank"] == {"genus": 1, "species": 3, "unrecorded": 1}
    pairs = [(p["taxon_a"], p["taxon_b"], p["samples_together"], p["samples_a"], p["samples_b"], p["jaccard"])
             for p in body["pairs"]]
    assert pairs == [
        ("Alpha a", "Beta b", 2, 2, 2, 1.0),
        ("Alpha a", "Gamma c", 1, 2, 1, 0.5),
        ("Beta b", "Gamma c", 1, 2, 1, 0.5),
    ]
    assert all(p["rank_a"] == p["rank_b"] == "species" for p in body["pairs"])
    assert body["pairs_total"] == 3
    nodes = {n["taxon"]: (n["samples"], n["sequences"]) for n in body["nodes"]}
    assert nodes == {"Alpha a": (2, 3), "Beta b": (2, 2), "Gamma c": (1, 1)}
    assert any("only included with rank=any" in n for n in body["notes"])


@pytest.mark.anyio
async def test_cooccurrence_rank_any_includes_every_recorded_rank(client, researcher_token, db):
    _seed(db)
    body = (await client.get("/partner/cooccurrence", params={"rank": "any"},
                             headers=_auth(researcher_token))).json()
    assert body["rank"] == "any"
    names = {n["taxon"]: n["rank"] for n in body["nodes"]}
    assert names == {"Alpha a": "species", "Beta b": "species", "Gamma c": "species",
                     "Genusia": "genus", "Legacyus fish": "unrecorded"}
    # 5 taxa in upl_1 -> 10 pairs; (Alpha, Beta) also in upl_2.
    assert body["pairs_total"] == 10
    assert body["pairs"][0]["taxon_a"] == "Alpha a" and body["pairs"][0]["samples_together"] == 2
    assert "Homo sapiens" not in names


@pytest.mark.anyio
async def test_cooccurrence_genus_rank_has_no_pairs(client, researcher_token, db):
    _seed(db)
    body = (await client.get("/partner/cooccurrence", params={"rank": "genus"},
                             headers=_auth(researcher_token))).json()
    assert body["taxa"] == 1 and body["pairs"] == []
    assert any("two or more taxa at rank genus" in n for n in body["notes"])


@pytest.mark.anyio
async def test_cooccurrence_limit_reports_truncation_and_ties(client, researcher_token, db):
    _seed(db)
    body = (await client.get("/partner/cooccurrence", params={"limit": 2},
                             headers=_auth(researcher_token))).json()
    assert len(body["pairs"]) == 2 and body["pairs_total"] == 3
    assert any("top 2 of 3 pairs" in n for n in body["notes"])
    assert any("falls inside a tie" in n for n in body["notes"])
    assert {n["taxon"] for n in body["nodes"]} == {"Alpha a", "Beta b", "Gamma c"}


@pytest.mark.anyio
async def test_cooccurrence_scope_all_for_admin(client, admin_token, db):
    _seed(db)
    body = (await client.get("/partner/cooccurrence", params={"scope": "all"}, headers=_auth(admin_token))).json()
    assert body["scope"]["mode"] == "all" and body["samples"] == 3
    top = body["pairs"][0]
    assert (top["taxon_a"], top["taxon_b"], top["samples_together"]) == ("Alpha a", "Beta b", 3)
    assert body["taxa"] == 4  # + Delta d from the other user


@pytest.mark.anyio
async def test_cooccurrence_other_user_for_company_owner(client, company_owner_token, db):
    _seed(db)
    body = (await client.get("/partner/cooccurrence", params={"user_id": OTHER},
                             headers=_auth(company_owner_token))).json()
    assert body["scope"] == {"mode": "user", "user_id": OTHER, "date_from": None, "date_to": None}
    assert body["samples"] == 1 and body["pairs_total"] == 3
    assert any("Only one sample has taxa at rank species" in n for n in body["notes"])


@pytest.mark.anyio
async def test_cooccurrence_date_window_filters_uploads(client, researcher_token, db):
    _seed(db)
    body = (await client.get("/partner/cooccurrence", params={"date_from": "2026-10-03", "date_to": "2026-10-03"},
                             headers=_auth(researcher_token))).json()
    assert body["uploads_in_scope"] == 1 and body["samples"] == 1
    assert [(p["taxon_a"], p["taxon_b"]) for p in body["pairs"]] == [("Alpha a", "Beta b")]


@pytest.mark.anyio
async def test_cooccurrence_reads_only_the_fields_it_counts(client, researcher_token, db):
    _seed(db)
    await client.get("/partner/cooccurrence", headers=_auth(researcher_token))
    (flt, proj), = db["analysis_results"].queries
    assert flt == {"upload_id": {"$in": ["upl_1", "upl_2", "upl_3"]}, "user_id": OWNER}
    assert "results" not in proj and not any("embedding" in k for k in proj)
    assert proj["results.decision.predicted_taxon"] == 1


def test_taxa_per_sample_cap(monkeypatch):
    import asyncio
    monkeypatch.setattr(community, "MAX_TAXA_PER_SAMPLE", 2)
    fake = _FakeDb()
    _seed(fake)
    scope = community.CommunityScopeInfo(mode="mine", user_id=OWNER)
    body = asyncio.run(community.build_cooccurrence(fake, scope=scope, owner_filter={"user_id": OWNER}))
    # upl_1 keeps the two species with most sequences (Alpha 2, then Beta by name).
    assert [(p.taxon_a, p.taxon_b, p.samples_together) for p in body.pairs] == [("Alpha a", "Beta b", 2)]
    assert any("only the 2 with the most sequences" in n for n in body.notes)


# ---------------------------------------------------------------------------
# Rhythms
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_rhythms_bins_by_collected_at_else_upload_time(client, researcher_token, db):
    _seed(db)
    resp = await client.get("/partner/rhythms", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    t = body["totals"]
    assert t == {"uploads": 3, "uploads_collected_at": 2, "uploads_upload_time": 1, "uploads_without_timestamp": 0,
                 "samples_analysed": 2,
                 # upl_1 newest run: Alpha x2, Beta, Gamma, Genusia, Legacyus (contaminant excluded); upl_2: 2
                 "detections": 8, "contamination_sequences_excluded": 1}
    hours = {b["bin"]: b for b in body["by_hour"] if b["uploads"]}
    assert set(hours) == {6, 8, 22}
    assert (hours[6]["uploads_collected_at"], hours[6]["uploads_upload_time"], hours[6]["detections"]) == (1, 0, 6)
    assert (hours[8]["uploads_collected_at"], hours[8]["uploads_upload_time"], hours[8]["detections"]) == (0, 1, 2)
    assert (hours[22]["uploads_collected_at"], hours[22]["detections"]) == (1, 0)
    days = {b["label"]: b["uploads"] for b in body["by_weekday"] if b["uploads"]}
    assert days == {"Thu": 1, "Sat": 1, "Mon": 1}
    assert sum(b["uploads"] for b in body["by_hour"]) == sum(b["uploads"] for b in body["by_weekday"]) == 3
    assert any("1 of 3 uploads have no collected_at" in n for n in body["notes"])
    assert any("not an activity rhythm" in n for n in body["notes"])
    assert {"timestamp", "timezone", "detections", "interpretation"} <= set(body["definitions"])
