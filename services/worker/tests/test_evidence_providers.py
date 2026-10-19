"""
Evidence-provider interface (app/evidence/base.py, providers.py; Day 9,
tracker t-1022-1): one record per input in input order, and a missing
model / DB / tool or a raising scorer gives "unavailable" with a reason,
never an exception.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import bson
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import get_worker_settings
from app.evidence import (
    ContaminationProvider,
    EvidenceProvider,
    EvidenceRecord,
    NoveltyProvider,
    ReferenceEvidenceProvider,
    RouteHeadProvider,
)
from app.evidence.base import plain
from app.evidence.reference_lookup import ReferenceLookupProvider
from app.inference.models import InferenceMode, PredictionResult

ITEMS = [("s1", "ACGT" * 30), ("s2", "TTGA" * 30), ("s3", "GGCC" * 30)]


def _pred(sid, route, mode=InferenceMode.model, rc="known_species", conf=0.91, reason=None):
    return PredictionResult(sequence_id=sid, result_class=rc, predicted_taxon=None, confidence=conf,
                            model_version_used=f"m_{route}", inference_mode=mode,
                            label_scores={rc: conf} if mode == InferenceMode.model else {},
                            embedding=[0.1, 0.2] if mode == InferenceMode.model else None, stub_reason=reason)


def test_record_rejects_unknown_status():
    with pytest.raises(ValueError):
        EvidenceRecord("p", "1", "s", "fish", "maybe")


def test_providers_satisfy_the_protocol():
    s = get_worker_settings()
    for p in (RouteHeadProvider(lambda **kw: None), ReferenceEvidenceProvider(object(), settings=s),
              ContaminationProvider(lambda d: None), NoveltyProvider(lambda d: None)):
        assert isinstance(p, EvidenceProvider)
        assert p.name and p.version


# -- route head ----------------------------------------------------------------

def test_head_runs_any_route_in_input_order():
    calls = []

    def infer(sequence_id, sequence, route):
        calls.append((sequence_id, route))
        return _pred(sequence_id, route)

    recs = RouteHeadProvider(infer).collect(ITEMS, "plant")   # not the router's pick: any route works
    assert [r.sequence_id for r in recs] == ["s1", "s2", "s3"]
    assert all(r.ok and r.route == "plant" for r in recs)
    assert calls == [("s1", "plant"), ("s2", "plant"), ("s3", "plant")]
    # the embedding travels in artifacts, never in the stored dict
    assert recs[0].artifacts["embedding"] == [0.1, 0.2]
    assert "embedding" not in str(recs[0].to_dict())


def test_head_stub_and_raise_are_unavailable():
    def infer(sequence_id, sequence, route):
        if sequence_id == "s2":
            raise RuntimeError("CUDA out of memory")
        if sequence_id == "s3":
            return _pred(sequence_id, route, mode=InferenceMode.stub, rc="unknown_needs_online_confirmation",
                         conf=0.0, reason="head_missing")
        return _pred(sequence_id, route)

    recs = RouteHeadProvider(infer).collect(ITEMS, "fish")
    assert [r.status for r in recs] == ["ok", "unavailable", "unavailable"]
    assert "RuntimeError" in recs[1].reason
    assert "head_missing" in recs[2].reason


def test_head_skips_low_quality():
    recs = RouteHeadProvider(lambda **kw: pytest.fail("no head runs on low_quality")).collect(ITEMS, "low_quality")
    assert [r.status for r in recs] == ["skipped"] * 3


# -- reference lookup ------------------------------------------------------------

def test_reference_missing_db_is_unavailable(tmp_path):
    s = get_worker_settings().model_copy(update={"reference_db_root": str(tmp_path / "nope")})
    prov = ReferenceEvidenceProvider(ReferenceLookupProvider(s), settings=s)
    recs = prov.collect(ITEMS, "fish")
    assert [r.sequence_id for r in recs] == ["s1", "s2", "s3"]
    assert all(r.status == "unavailable" and r.reason for r in recs)


def test_reference_lookup_raising_is_unavailable():
    class Boom:
        def lookup(self, items, route):
            raise OSError("disk gone")

    recs = ReferenceEvidenceProvider(Boom(), settings=get_worker_settings()).collect(ITEMS, "fish")
    assert all(r.status == "unavailable" and "OSError" in r.reason for r in recs)


def test_reference_payload_is_bounded():
    from app.evidence.reference_lookup import ReferenceEvidence, ReferenceHit, TaxonAssignment

    hits = [ReferenceHit(target_id=f"t{i}", taxid=None, accession=f"A{i}", source="midori2", marker="COI", identity=99.0 - i,
                         query_coverage=100.0, alignment_length=300, lineage={"species": f"Sp {i}"})
            for i in range(10)]

    class Fake:
        def lookup(self, items, route):
            return [ReferenceEvidence(sequence_id=sid, route=route, available=True, status="assigned",
                                      assignment=TaxonAssignment(status="assigned", taxon="Sp 0", rank="species",
                                                                 lineage={"species": "Sp 0"}, identity=99.0),
                                      hits=hits, reference_db="synthveda-reference/fish", reference_db_version="v2")
                    for sid, _ in items]

    recs = ReferenceEvidenceProvider(Fake(), max_hits=3, settings=get_worker_settings()).collect(ITEMS, "fish")
    assert len(recs[0].payload["hits"]) == 3
    assert recs[0].payload["taxon"] == "Sp 0" and recs[0].payload["reference_db_version"] == "v2"
    bson.BSON.encode(recs[0].to_dict())


def test_reference_skips_low_quality():
    recs = ReferenceEvidenceProvider(object(), settings=get_worker_settings()).collect(ITEMS, "low_quality")
    assert [r.status for r in recs] == ["skipped"] * 3


# -- contamination ----------------------------------------------------------------

def _cr(flagged=False):
    return SimpleNamespace(contamination_score=0.8 if flagged else 0.1, is_flagged=flagged,
                           contamination_type="lab_reagent" if flagged else None,
                           signals={"route": 0.0}, reason_codes=["contamination_flagged" if flagged else "clean_sequence"])


def test_contamination_grch38_hit_flags_human_dna():
    ctx = [{"human_genome": {"hit": True, "contamination": True, "identity": 99.9}}, {}, {"human_genome": None}]
    recs = ContaminationProvider(lambda d: _cr(False)).collect(ITEMS, "misc_unknown", ctx)
    assert recs[0].payload["flagged"] and recs[0].payload["contamination_type"] == "human_dna"
    assert "grch38_human_hit" in recs[0].payload["reason_codes"]
    assert "clean_sequence" not in recs[0].payload["reason_codes"]
    assert not recs[1].payload["flagged"] and not recs[2].payload["flagged"]


def test_contamination_scorer_raising_is_unavailable():
    def boom(d):
        raise KeyError("gc_ratio")
    recs = ContaminationProvider(boom).collect(ITEMS, "fish")
    assert [r.status for r in recs] == ["unavailable"] * 3


# -- novelty ------------------------------------------------------------------------

def test_novelty_needs_a_head_prediction():
    seen = []

    def score(d):
        seen.append(d["sequence_id"])
        return SimpleNamespace(novelty_score=0.6, novelty_level="medium", signals={"x": 1.0}, reason_codes=[],
                               abyss_recommendation="preserve_sample", requires_cloud_confirmation=True)

    ctx = [{"head_ok": True, "result_class": "possible_novelty", "confidence": 0.5}, {"head_ok": False}, None]
    recs = NoveltyProvider(score).collect(ITEMS, "fish", ctx)
    assert [r.status for r in recs] == ["ok", "skipped", "skipped"]
    assert seen == ["s1"]
    assert recs[0].payload["novelty_score"] == 0.6


def test_novelty_scorer_raising_is_unavailable():
    def boom(d):
        raise ValueError("bad")
    recs = NoveltyProvider(boom).collect(ITEMS, "fish", [{"head_ok": True}] * 3)
    assert [r.status for r in recs] == ["unavailable"] * 3


def test_plain_makes_numpy_bson_safe():
    np = pytest.importorskip("numpy")
    v = plain({"a": np.float32(0.5), "b": [np.int64(3)], 4: (np.bool_(True),)})
    bson.BSON.encode(v)
    assert v == {"a": 0.5, "b": [3], "4": [True]}
