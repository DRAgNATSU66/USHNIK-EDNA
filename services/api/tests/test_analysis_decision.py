"""
GET /analysis/{id} carries the worker orchestrator's per-sequence decision
and decision trace (decision Q7, Day 9). Before this the API models had no
such fields and pydantic's default extra="ignore" dropped them silently.

The stored result below has the shape services/worker/app/orchestrator/
engine.py writes (trimmed: one evidence record per provider kind).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import app.db.mongo as _mongo_module
from app.models.analysis import AnalysisResultDoc


class _Collection:
    def __init__(self):
        self.docs: list[dict] = []

    async def find_one(self, query):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None


class _FakeDb:
    def __init__(self):
        self.collections: dict[str, _Collection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.fixture
def fake_db():
    db = _FakeDb()
    with patch.object(_mongo_module, "_db", db):
        yield db


DECISION = {"final_route": "fish", "result_class": "known_species", "predicted_taxon": "Lophius budegassa",
            "taxon_rank": "species", "percent_identity": 100.0, "reference_db": "synthveda-reference/fish",
            "reference_db_version": "v2", "confidence": 0.9213, "rule": "novelty_suppressed_by_reference"}

TRACE = {
    "orchestrator_version": "orchestrator-1.2.0",
    "plan": {"primary_route": "fish", "routes": ["fish"], "max_routes": 3,
             "rules_fired": [{"rule": "confident_router", "stage": "router", "detail": "no wide-plan rule fired",
                              "added": []}],
             "router": {"method": "learned", "version": "v2", "calibrated": True, "top_probability": 0.99,
                        "margin": 0.98, "ranked": [["fish", 0.99], ["animal_general", 0.01]]}},
    "evidence": [
        {"provider": "route_head", "provider_version": "1.0", "sequence_id": "s1", "route": "fish", "status": "ok",
         "payload": {"result_class": "possible_novelty", "confidence": 0.9213}, "elapsed_ms": 12.0, "reason": None},
        {"provider": "reference_lookup", "provider_version": "1.0", "sequence_id": "s1", "route": "fish",
         "status": "ok", "payload": {"status": "assigned", "taxon": "Lophius budegassa", "identity": 100.0,
                                     "hits": []}, "elapsed_ms": 30.0, "reason": None},
    ],
    "combine": [{"step": "route", "rule": "single_route", "outcome": "fish", "detail": None},
                {"step": "class", "rule": "novelty_suppressed_by_reference", "outcome": "known_species",
                 "detail": "head said possible_novelty; reference counts against novelty (QNA-020 Q4)"}],
}


def _result(**over) -> dict:
    r = {"sequence_id": "s1", "sequence": "ACGT" * 30, "length": 120, "gc_ratio": 0.5, "n_ratio": 0.0,
         "route": "fish", "route_confidence": 0.99, "result_class": "known_species",
         "predicted_taxon": "Lophius budegassa", "confidence": 0.9213, "novelty_score": 0.0,
         "contamination_score": 0.05, "router_route": "fish", "decision": DECISION, "decision_trace": TRACE,
         "embedding": [0.0] * 8}
    r.update(over)
    return r


def _doc(results) -> dict:
    return {"analysis_id": "ana_dec001", "job_id": "job_dec001", "upload_id": "upl_dec001",
            "user_id": "usr_test_001", "mode": "online_full", "model_version_set": "stub_none",
            "orchestrator_version": "orchestrator-1.2.0", "results": results,
            "created_at": datetime(2026, 10, 19, tzinfo=timezone.utc)}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_model_keeps_decision_and_trace():
    d = AnalysisResultDoc(**_doc([_result()])).model_dump()
    assert d["orchestrator_version"] == "orchestrator-1.2.0"
    r = d["results"][0]
    assert r["decision"] == DECISION
    assert r["decision_trace"] == TRACE
    assert r["router_route"] == "fish"
    assert "embedding" not in r            # still not exposed


def test_pre_orchestrator_result_still_validates():
    old = _result()
    for k in ("decision", "decision_trace", "router_route"):
        old.pop(k)
    r = AnalysisResultDoc(**_doc([old])).model_dump()["results"][0]
    assert r["decision"] is None and r["decision_trace"] is None and r["router_route"] is None


@pytest.mark.anyio
async def test_get_analysis_returns_decision_and_trace(client, researcher_token, fake_db):
    fake_db["uploads"].docs.append({"upload_id": "upl_dec001", "user_id": "usr_test_001",
                                    "original_filename": "s.fasta", "file_size_bytes": 1, "status": "stored"})
    fake_db["analysis_results"].docs.append(_doc([_result()]))
    resp = await client.get("/analysis/ana_dec001", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["orchestrator_version"] == "orchestrator-1.2.0"
    r = body["results"][0]
    assert r["decision"] == DECISION
    assert r["decision_trace"]["plan"]["primary_route"] == "fish"
    assert [c["rule"] for c in r["decision_trace"]["combine"]] == ["single_route", "novelty_suppressed_by_reference"]

    resp = await client.get("/analysis/ana_dec001?include_trace=false", headers=_auth(researcher_token))
    assert resp.status_code == 200
    r = resp.json()["results"][0]
    assert r["decision"] == DECISION and r["decision_trace"] is None
