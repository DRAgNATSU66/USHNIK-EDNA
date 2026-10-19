"""
Orchestrator engine and job_runner stage with fake providers (Day 9,
tracker t-1022-2). The head and reference providers are fakes; the
contamination and novelty providers wrap the real scorers.
"""
from __future__ import annotations

import asyncio
import os
import sys

import bson
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import job_runner
from app.config import get_worker_settings
from app.evidence.base import EVIDENCE_OK, EVIDENCE_UNAVAILABLE, EvidenceRecord
from app.orchestrator import ORCHESTRATOR_VERSION, Orchestrator

FISH, PLANT, ANIMAL, HUMAN, MISC = "fish", "plant", "animal_general", "human_domestic_contamination", "misc_unknown"
SEQ = "ACGTTGCA" * 40

FISH_LIN = {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Chordata", "class": "Actinopteri",
            "genus": "Salmo", "species": "Salmo trutta"}
PLANT_LIN = {"superkingdom": "Eukaryota", "kingdom": "Viridiplantae", "phylum": "Streptophyta",
             "genus": "Quercus", "species": "Quercus robur"}


def settings(**over):
    base = dict(orchestrator_max_routes=3, orchestrator_confidence_threshold=0.70, orchestrator_margin_threshold=0.6,
                orchestrator_weak_routes=[HUMAN, MISC], orchestrator_reference_expansion=True,
                orchestrator_reference_enabled=True, orchestrator_genus_cap_routes=[PLANT],
                reference_species_identity=97.0, reference_tie_delta=0.5, orchestrator_trace_max_hits=3)
    base.update(over)
    return get_worker_settings().model_copy(update=base)


def routed(sid: str, probs: dict[str, float]) -> dict:
    top = max(probs, key=probs.get)
    return {"sequence_id": sid, "sequence": SEQ, "length": len(SEQ), "gc_ratio": 0.5, "n_ratio": 0.0,
            "has_invalid_chars": False, "route": top, "route_confidence": probs[top], "confidence_tier": "high",
            "fallback_routes": [r for r in probs if r != top], "reason_codes": ["learned_router"],
            "router_method": "learned", "router_version": "v2", "route_probabilities": probs,
            "route_probabilities_calibrated": True}


class FakeHead:
    name, version = "route_head", "test"

    def __init__(self, table: dict, default=("ok", "known_species", 0.9)):
        self.table, self.default, self.calls = table, default, []

    def collect(self, items, route, context=None):
        self.calls.append((route, [sid for sid, _ in items]))
        out = []
        for sid, _ in items:
            if route == "low_quality":
                out.append(EvidenceRecord(self.name, self.version, sid, route, "skipped", reason="lq"))
                continue
            status, rc, conf = self.table.get((sid, route), self.default)
            if status != EVIDENCE_OK:
                out.append(EvidenceRecord(self.name, self.version, sid, route, EVIDENCE_UNAVAILABLE, reason="no head"))
                continue
            out.append(EvidenceRecord(self.name, self.version, sid, route, EVIDENCE_OK,
                                      payload={"result_class": rc, "confidence": conf, "label_scores": {rc: conf},
                                               "model_version_used": f"m_{route}", "inference_mode": "model",
                                               "stub_reason": None},
                                      artifacts={"embedding": [0.0] * 8}))
        return out


class FakeReference:
    name, version = "reference_lookup", "test"

    def __init__(self, table: dict, unavailable: bool = False):
        self.table, self.unavailable, self.calls = table, unavailable, []

    def collect(self, items, route, context=None):
        self.calls.append((route, [sid for sid, _ in items]))
        out = []
        for sid, _ in items:
            if self.unavailable:
                out.append(EvidenceRecord(self.name, self.version, sid, route, EVIDENCE_UNAVAILABLE,
                                          reason="no reference DB"))
                continue
            status, identity, lineage = self.table.get((sid, route), ("no_hit", None, {}))
            rank = "species" if lineage.get("species") else ("genus" if lineage.get("genus") else None)
            out.append(EvidenceRecord(self.name, self.version, sid, route, EVIDENCE_OK, payload={
                "status": status, "taxon": lineage.get(rank) if rank else None, "rank": rank, "identity": identity,
                "lineage": lineage, "hits": [], "reference_db": f"synthveda-reference/{route}",
                "reference_db_version": "v2", "human_genome": None}))
        return out


CONFIDENT_FISH = {FISH: 0.97, PLANT: 0.02, ANIMAL: 0.01}
WEAK_MISC = {MISC: 0.9, PLANT: 0.06, FISH: 0.04}


def _has_key(obj, key) -> bool:
    if isinstance(obj, dict):
        return key in obj or any(_has_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key(v, key) for v in obj)
    return False


def run(seqs, head=None, ref=None, s=None, phases=None):
    orch = Orchestrator(s or settings(), head=head or FakeHead({}), reference=ref or FakeReference({}),
                        novelty_threshold=0.45)
    return orch.run(seqs, on_phase=(phases.append if phases is not None else None))


def test_decision_and_trace_contract():
    seqs = [routed("a", CONFIDENT_FISH)]
    run(seqs, ref=FakeReference({("a", FISH): ("assigned", 99.5, FISH_LIN)}))
    seq = seqs[0]
    d, t = seq["decision"], seq["decision_trace"]
    assert set(d) == {"final_route", "result_class", "predicted_taxon", "taxon_rank", "percent_identity",
                      "reference_db", "reference_db_version", "confidence", "rule"}
    assert set(t) == {"orchestrator_version", "plan", "evidence", "combine"}
    assert t["orchestrator_version"] == ORCHESTRATOR_VERSION
    assert d == {"final_route": FISH, "result_class": "known_species", "predicted_taxon": "Salmo trutta",
                 "taxon_rank": "species", "percent_identity": 99.5, "reference_db": "synthveda-reference/fish",
                 "reference_db_version": "v2", "confidence": 0.9, "rule": "head_class"}
    assert {e["provider"] for e in t["evidence"]} == {"route_head", "reference_lookup", "contamination", "novelty"}
    # legacy fields follow the decision
    assert seq["route"] == FISH and seq["router_route"] == FISH
    assert seq["result_class"] == "known_species" and seq["predicted_taxon"] == "Salmo trutta"
    assert seq["confidence"] == 0.9 and seq["model_version_used"] == "m_fish"
    assert isinstance(seq["novelty_score"], float) and isinstance(seq["contamination_score"], float)
    # BSON-serializable and free of embeddings
    bson.BSON.encode({"decision": d, "decision_trace": t})
    assert not _has_key(t, "embedding")


def test_reference_miss_expands_and_overrides_route():
    seqs = [routed("a", CONFIDENT_FISH)]
    head, ref = FakeHead({}), FakeReference({("a", PLANT): ("assigned", 99.9, PLANT_LIN)})
    run(seqs, head=head, ref=ref)
    seq = seqs[0]
    plan = seq["decision_trace"]["plan"]
    assert plan["routes"] == [FISH, PLANT]
    assert [r["rule"] for r in plan["rules_fired"]] == ["confident_router", "reference_miss"]
    assert seq["decision"]["final_route"] == PLANT and seq["route"] == PLANT and seq["router_route"] == FISH
    assert seq["route_confidence"] == 0.02            # the router's probability for the final route
    assert "orchestrator_route_changed" in seq["reason_codes"]
    assert seq["decision"]["predicted_taxon"] == "Quercus"   # plant: genus cap
    rules = [c["rule"] for c in seq["decision_trace"]["combine"]]
    assert "reference_overrides_router" in rules and "genus_cap" in rules
    # primary lookup first, then the expansion
    assert ref.calls == [(FISH, ["a"]), (PLANT, ["a"])]


def test_batched_by_route():
    seqs = [routed("a", CONFIDENT_FISH), routed("b", CONFIDENT_FISH), routed("c", WEAK_MISC)]
    ref = FakeReference({(sid, r): ("assigned", 99.0, FISH_LIN if r == FISH else PLANT_LIN)
                         for sid in "abc" for r in (FISH, PLANT, MISC)})
    head = FakeHead({})
    run(seqs, head=head, ref=ref)
    # one reference call per route per pass, sequences grouped
    assert (FISH, ["a", "b"]) in ref.calls and (MISC, ["c"]) in ref.calls
    assert len([c for c in ref.calls if c[0] == FISH]) == 2   # primaries a,b; then c's planned fish
    by_route = {}
    for route, sids in head.calls:
        by_route.setdefault(route, []).append(sids)
    assert all(len(v) == 1 for v in by_route.values())        # one head call per route
    assert by_route[FISH] == [["a", "b", "c"]]


def test_reference_disabled_is_heads_only():
    seqs = [routed("a", CONFIDENT_FISH)]
    ref = FakeReference({})
    run(seqs, ref=ref, s=settings(orchestrator_reference_enabled=False))
    t = seqs[0]["decision_trace"]
    assert ref.calls == []
    refs = [e for e in t["evidence"] if e["provider"] == "reference_lookup"]
    assert refs and refs[0]["status"] == "skipped" and "ORCHESTRATOR_REFERENCE_ENABLED" in refs[0]["reason"]
    assert any(c["rule"] == "heads_only" for c in t["combine"])
    assert seqs[0]["decision"]["result_class"] == "known_species"
    assert seqs[0]["decision"]["predicted_taxon"] is None


def test_reference_unavailable_falls_back_to_heads():
    seqs = [routed("a", WEAK_MISC)]
    run(seqs, ref=FakeReference({}, unavailable=True), head=FakeHead({}, default=("ok", "possible_novelty", 0.8)))
    seq = seqs[0]
    assert seq["decision"]["final_route"] == MISC and seq["decision"]["result_class"] == "possible_novelty"
    route_step = [c for c in seq["decision_trace"]["combine"] if c["step"] == "route"][0]
    assert route_step["rule"] == "router_primary" and "heads only" in route_step["detail"]


def test_nothing_available_is_honest():
    seqs = [routed("a", CONFIDENT_FISH)]
    run(seqs, head=FakeHead({}, default=("unavailable", None, None)), ref=FakeReference({}, unavailable=True))
    seq = seqs[0]
    assert seq["decision"]["result_class"] == "unknown_needs_online_confirmation"
    assert seq["decision"]["rule"] == "no_evidence" and seq["decision"]["confidence"] is None
    assert seq["confidence"] == 0.0 and seq["novelty_score"] == 0.0
    assert seq["inference_mode"] == "stub" and "novelty_unscored" in seq["novelty_reason_codes"]


def test_novelty_suppressed_by_reference_end_to_end():
    seqs = [routed("a", CONFIDENT_FISH)]
    run(seqs, head=FakeHead({}, default=("ok", "possible_novelty", 0.95)),
        ref=FakeReference({("a", FISH): ("assigned", 99.8, FISH_LIN)}))
    seq = seqs[0]
    assert seq["result_class"] == "known_species"
    assert seq["novelty_score"] == 0.0 and seq["novelty_raw_score"] > 0
    assert seq["novelty_gate_rule"] == "novelty_suppressed_by_reference"


def test_low_quality_passes_through():
    seq = {"sequence_id": "q", "sequence": "ACGTN" * 3, "length": 15, "n_ratio": 0.2, "route": "low_quality",
           "route_confidence": 1.0, "route_probabilities": {}, "router_method": "learned"}
    ref = FakeReference({})
    run([seq], ref=ref)
    assert ref.calls == []
    assert seq["decision"]["result_class"] == "low_quality_unusable" and seq["route"] == "low_quality"
    bson.BSON.encode(seq["decision_trace"])


def test_phases_and_misbehaving_provider():
    class Short(FakeHead):
        def collect(self, items, route, context=None):
            return super().collect(items, route, context)[:-1]   # one record short

    phases = []
    seqs = [routed("a", CONFIDENT_FISH), routed("b", CONFIDENT_FISH)]
    run(seqs, head=Short({}), phases=phases)
    assert phases == ["evidence", "scoring"]
    heads = [e for s in seqs for e in s["decision_trace"]["evidence"] if e["provider"] == "route_head"]
    assert all(e["status"] == "unavailable" and "records for 2 inputs" in e["reason"] for e in heads)


def test_empty_batch():
    assert run([])["sequences"] == 0


# ---------------------------------------------------------------------------
# job_runner
# ---------------------------------------------------------------------------

class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.updates = []

    async def find_one(self, q):
        return next((d for d in self.docs if all(d.get(k) == v for k, v in q.items())), None)

    async def update_one(self, q, u):
        self.updates.append(u["$set"])

    async def insert_one(self, d):
        self.docs.append(d)

    async def insert_many(self, ds):
        self.docs.extend(ds)


class _DB(dict):
    def __missing__(self, k):
        self[k] = _Coll()
        return self[k]


def test_run_job_records_decision_and_trace(monkeypatch):
    db = _DB()
    db["analysis_jobs"] = _Coll([{"job_id": "job_1", "upload_id": "up_1"}])
    db["uploads"] = _Coll([{"upload_id": "up_1"}])

    async def fake_parse(upload):
        return [{"sequence_id": "a", "sequence": SEQ, "length": len(SEQ), "gc_ratio": 0.5, "n_ratio": 0.0,
                 "has_invalid_chars": False, "sha256": "x", "source_file": "t.fa"},
                {"sequence_id": "b", "sequence": SEQ[::-1], "length": len(SEQ), "gc_ratio": 0.5, "n_ratio": 0.0,
                 "has_invalid_chars": False, "sha256": "y", "source_file": "t.fa"}]

    def fake_orchestrate(seqs, on_phase=None):
        orch = Orchestrator(settings(), head=FakeHead({}, default=("ok", "possible_novelty", 0.6)),
                            reference=FakeReference({}), novelty_threshold=0.45)
        return orch.run(seqs, on_phase=on_phase)

    monkeypatch.setattr(job_runner, "_stage_parse", fake_parse)
    monkeypatch.setattr(job_runner, "run_orchestrator", fake_orchestrate)
    asyncio.run(job_runner.run_job(db, "job_1"))

    states = [u["state"] for u in db["analysis_jobs"].updates]
    assert states == ["parsing", "qc", "routing", "inferencing", "novelty_scoring", "reporting", "completed"]
    doc = db["analysis_results"].docs[0]
    assert doc["orchestrator_version"] == ORCHESTRATOR_VERSION
    assert doc["summary"]["total_sequences"] == 2
    for r in doc["results"]:
        assert r["decision"]["final_route"] == r["route"]
        assert r["decision_trace"]["plan"]["primary_route"] == r["router_route"]
    doc.pop("_id", None)
    bson.BSON.encode(doc)
