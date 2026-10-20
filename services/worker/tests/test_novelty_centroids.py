"""
B5 (tracker t-1024-1): centroid embedding isolation, its fallback to the old
L2-norm proxy, and the separate reference low-identity term.
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import get_worker_settings
from app.evidence.base import EVIDENCE_OK, EvidenceRecord
from app.evidence.providers import NoveltyProvider
from app.novelty import centroids as cmod
from app.novelty.centroids import (
    ARRAYS_NAME,
    CHECKSUM_MISMATCH,
    FILE_MISSING,
    MANIFEST_NAME,
    MODEL_MISMATCH,
    NOT_IN_REGISTRY,
    CentroidSet,
    centroids_for_model,
    sha256_file,
)
from app.novelty.scorer import LEGACY_EMBEDDING_WEIGHT, WEIGHTS, score_sequence
from app.novelty.signals import (
    LEGACY_TYPICAL_NORM,
    METHOD_CENTROID,
    METHOD_PROXY,
    embedding_isolation,
    reference_low_identity,
)

DIM = 4


def _set(quantiles=None) -> CentroidSet:
    c = np.eye(DIM, dtype=np.float32)[:2]            # e0, e1
    q = np.linspace(0.0, 0.5, 11, dtype=np.float32) if quantiles is None else quantiles
    return CentroidSet(model_id="m1", route="fish", centroids=c, centroid_class=["known_species", "likely_taxonomic_group"],
                       calib_quantiles=q, sha256="ab" * 32)


def _seq(**kw) -> dict:
    base = dict(sequence_id="s1", confidence=0.6, result_class="known_species", route="fish",
                label_scores={"known_species": 0.6, "possible_novelty": 0.3, "low_quality_unusable": 0.1},
                n_ratio=0.0, length=300, has_invalid_chars=False, contamination_score=0.0)
    base.update(kw)
    return base


def _ref(status="ok", ref_status="no_hit", identity=None) -> dict:
    return {"provider": "reference_lookup", "status": status, "route": "fish",
            "payload": {"status": ref_status, "identity": identity}}


# ---------------------------------------------------------------------------
# centroid distance
# ---------------------------------------------------------------------------

class TestCentroidDistance:
    def test_nearest_is_cosine_distance_to_closest_centroid(self):
        cs = _set()
        d, j = cs.nearest([3.0, 0.0, 0.0, 0.0])         # parallel to e0, any length
        assert j == 0 and d == pytest.approx(0.0, abs=1e-6)
        d, j = cs.nearest([0.0, 1.0, 1.0, 0.0])         # 45 deg from e1
        assert j == 1 and d == pytest.approx(1 - 1 / math.sqrt(2), abs=1e-6)
        d, _ = cs.nearest([0.0, 0.0, 1.0, 0.0])         # orthogonal to both
        assert d == pytest.approx(1.0, abs=1e-6)

    def test_ecdf_is_monotone_and_clipped(self):
        cs = _set()
        assert cs.ecdf(-0.1) == 0.0
        assert cs.ecdf(0.25) == pytest.approx(0.5)
        assert cs.ecdf(0.9) == 1.0
        xs = [cs.ecdf(x) for x in np.linspace(0, 0.6, 25)]
        assert xs == sorted(xs)

    def test_dim_mismatch_and_zero_vector_raise(self):
        cs = _set()
        with pytest.raises(ValueError):
            cs.nearest([1.0, 0.0])
        with pytest.raises(ValueError):
            cs.nearest([0.0] * DIM)

    def test_signal_uses_centroids_when_available(self):
        cs = _set()
        score, code, detail = embedding_isolation(_seq(embedding=[0.0, 0.0, 1.0, 0.0], model_version_used="m1"),
                                                  resolver=lambda mid: (cs, None))
        assert detail["method"] == METHOD_CENTROID
        assert detail["cosine_distance"] == pytest.approx(1.0, abs=1e-5)
        assert score == 1.0 and code == "embedding_isolated"
        near, code, d2 = embedding_isolation(_seq(embedding=[1.0, 0.01, 0.0, 0.0], model_version_used="m1"),
                                             resolver=lambda mid: (cs, None))
        assert near < 0.05 and code == "embedding_near_known" and d2["nearest_class"] == "known_species"


# ---------------------------------------------------------------------------
# fallback
# ---------------------------------------------------------------------------

class TestFallback:
    def test_missing_centroids_fall_back_to_norm_proxy_and_say_so(self):
        emb = [2.0] * 100                                  # norm 20
        score, _, detail = embedding_isolation(_seq(embedding=emb, model_version_used="m1"),
                                               resolver=lambda mid: (None, FILE_MISSING))
        assert detail["method"] == METHOD_PROXY and detail["fallback_reason"] == FILE_MISSING
        assert score == pytest.approx(abs(20 - LEGACY_TYPICAL_NORM) / LEGACY_TYPICAL_NORM, abs=1e-4)
        r = score_sequence(_seq(embedding=emb, model_version_used="m1"), resolver=lambda mid: (None, FILE_MISSING))
        assert f"embedding_proxy_{FILE_MISSING}" in r.reason_codes
        assert r.details["embedding_isolation"]["weight"] == LEGACY_EMBEDDING_WEIGHT

    def test_dim_mismatch_falls_back_not_raises(self):
        score, _, detail = embedding_isolation(_seq(embedding=[1.0] * 7, model_version_used="m1"),
                                               resolver=lambda mid: (_set(), None))
        assert detail["method"] == METHOD_PROXY and detail["fallback_reason"] == "centroids_dim_mismatch"

    def test_no_centroids_and_no_reference_is_exactly_the_old_score(self):
        seq = _seq(embedding=[2.0] * 100, model_version_used="nope", confidence=0.3, result_class="likely_taxonomic_group")
        new = score_sequence(seq, resolver=lambda mid: (None, NOT_IN_REGISTRY)).novelty_score
        s = score_sequence(seq, resolver=lambda mid: (None, NOT_IN_REGISTRY)).signals
        base = (0.35 * s["result_class"] + 0.25 * s["low_confidence"] + 0.07 * s["label_entropy"]
                + 0.03 * s["embedding_isolation"]) / 0.70
        assert new == pytest.approx(round(base * (0.3 + 0.7 * s["high_quality"]) * s["not_contamination"], 4))

    def test_resolver_unknown_model_never_raises(self):
        cs, why = centroids_for_model("definitely_not_a_model_id")
        assert cs is None and why == NOT_IN_REGISTRY
        assert centroids_for_model(None) == (None, "no_model_id")


@dataclass
class _Entry:
    model_id: str
    artifact_uri: str
    checksum: str | None


class _Reg:
    def __init__(self, entry):
        self.entry = entry

    def get(self, mid):
        return self.entry if mid == self.entry.model_id else None


def _write_artifact(d, model_id="m1", head_checksum="h" * 64, tamper=False):
    np.savez(d / ARRAYS_NAME, centroids=np.eye(DIM, dtype=np.float32)[:2],
             centroid_class=np.asarray(["known_species", "known_species"]),
             calib_quantiles=np.linspace(0, 0.5, 11, dtype=np.float32))
    digest = sha256_file(str(d / ARRAYS_NAME))
    (d / MANIFEST_NAME).write_text(json.dumps({"model_id": model_id, "head_checksum": head_checksum,
                                               "npz_sha256": "0" * 64 if tamper else digest}))


class TestArtifactLoading:
    def setup_method(self):
        cmod.clear_cache()

    def test_loads_verified_artifact_beside_head(self, tmp_path):
        _write_artifact(tmp_path)
        reg = _Reg(_Entry("m1", str(tmp_path / "head.pt"), "h" * 64))
        cs, why = centroids_for_model("m1", registry=reg)
        assert why is None and cs.centroids.shape == (2, DIM)
        assert cs.describe()["centroids_k"] == 2

    def test_missing_file(self, tmp_path):
        reg = _Reg(_Entry("m1", str(tmp_path / "head.pt"), None))
        assert centroids_for_model("m1", registry=reg) == (None, FILE_MISSING)

    def test_tampered_npz(self, tmp_path):
        _write_artifact(tmp_path, tamper=True)
        reg = _Reg(_Entry("m1", str(tmp_path / "head.pt"), "h" * 64))
        assert centroids_for_model("m1", registry=reg) == (None, CHECKSUM_MISMATCH)

    def test_artifact_of_another_head(self, tmp_path):
        _write_artifact(tmp_path, model_id="m0")
        reg = _Reg(_Entry("m1", str(tmp_path / "head.pt"), "h" * 64))
        assert centroids_for_model("m1", registry=reg) == (None, MODEL_MISMATCH)
        cmod.clear_cache()
        _write_artifact(tmp_path, head_checksum="x" * 64)
        assert centroids_for_model("m1", registry=reg) == (None, MODEL_MISMATCH)


# ---------------------------------------------------------------------------
# reference low-identity term
# ---------------------------------------------------------------------------

class TestReferenceLowIdentity:
    def test_bands(self):
        f = lambda rec: reference_low_identity({"reference": rec}, 90.0, 80.0)[0]  # noqa: E731
        assert f(_ref(ref_status="no_hit")) == 1.0
        assert f(_ref(ref_status="below_threshold", identity=85.0)) == pytest.approx(0.5)
        assert f(_ref(ref_status="below_threshold", identity=80.0)) == 1.0
        assert f(_ref(ref_status="assigned", identity=90.0)) == 0.0
        assert f(_ref(ref_status="no_consensus", identity=99.0)) == 0.0

    def test_unavailable_reference_is_not_novelty(self):
        assert reference_low_identity({"reference": _ref(status="unavailable")}, 90.0, 80.0)[0] is None
        assert reference_low_identity({}, 90.0, 80.0)[0] is None
        seq = _seq(embedding=None)
        without = score_sequence(seq)
        unavailable = score_sequence({**seq, "reference": _ref(status="unavailable")})
        assert unavailable.novelty_score == without.novelty_score
        assert "reference_low_identity" not in unavailable.signals
        assert "reference_unavailable" in unavailable.reason_codes

    def test_no_hit_raises_and_family_hit_lowers_the_score(self):
        seq = _seq(embedding=None)
        none = score_sequence(seq).novelty_score
        no_hit = score_sequence({**seq, "reference": _ref(ref_status="no_hit")})
        fam = score_sequence({**seq, "reference": _ref(ref_status="assigned", identity=92.0)})
        assert no_hit.novelty_score > none > fam.novelty_score
        assert no_hit.signals["reference_low_identity"] == 1.0
        assert no_hit.details["reference_low_identity"]["weight"] == WEIGHTS["reference_low_identity"]
        assert "reference_no_hit" in no_hit.reason_codes

    def test_uses_the_configured_bands(self):
        s = get_worker_settings().model_copy(update={"reference_family_identity": 95.0,
                                                     "reference_search_min_identity": 85.0})
        r = score_sequence({**_seq(), "reference": _ref(ref_status="below_threshold", identity=90.0)}, settings=s)
        assert r.signals["reference_low_identity"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# provider + engine wiring
# ---------------------------------------------------------------------------

def test_novelty_provider_payload_records_both_terms():
    ctx = {**_seq(embedding=[2.0] * 100, model_version_used="not_registered"), "head_ok": True,
           "reference": _ref(ref_status="no_hit")}
    rec = NoveltyProvider().collect([("s1", "ACGT")], "fish", [ctx])[0]
    assert rec.ok and rec.provider_version == "2.0"
    det = rec.payload["details"]
    assert det["embedding_isolation"]["method"] == METHOD_PROXY
    assert det["embedding_isolation"]["fallback_reason"] == NOT_IN_REGISTRY
    assert det["reference_low_identity"]["reference_status"] == "no_hit"
    assert rec.payload["signals"]["reference_low_identity"] == 1.0


def test_engine_passes_model_id_and_final_route_reference_to_novelty():
    from app.orchestrator import Orchestrator

    seen = []

    class SpyNovelty(NoveltyProvider):
        def collect(self, items, route, context=None):
            seen.extend(context or [])
            return super().collect(items, route, context)

    class Head:
        name, version = "route_head", "t"

        def collect(self, items, route, context=None):
            return [EvidenceRecord(self.name, self.version, sid, route, EVIDENCE_OK,
                                   payload={"result_class": "possible_novelty", "confidence": 0.8,
                                            "label_scores": {"possible_novelty": 0.8}, "model_version_used": "m_fish",
                                            "inference_mode": "model", "stub_reason": None},
                                   artifacts={"embedding": [1.0] * 8}) for sid, _ in items]

    class Ref:
        name, version = "reference_lookup", "t"

        def collect(self, items, route, context=None):
            return [EvidenceRecord(self.name, self.version, sid, route, EVIDENCE_OK,
                                   payload={"status": "below_threshold", "identity": 84.0, "lineage": {}, "hits": []})
                    for sid, _ in items]

    s = get_worker_settings().model_copy(update={"orchestrator_reference_enabled": True})
    seq = {"sequence_id": "a", "sequence": "ACGT" * 60, "length": 240, "gc_ratio": 0.5, "n_ratio": 0.0,
           "has_invalid_chars": False, "route": "fish", "route_confidence": 0.99, "confidence_tier": "high",
           "fallback_routes": [], "reason_codes": [], "route_probabilities": {"fish": 0.99}}
    Orchestrator(s, head=Head(), reference=Ref(), novelty=SpyNovelty(), novelty_threshold=0.45).run([seq])
    assert seen and seen[0]["model_version_used"] == "m_fish"
    assert seen[0]["reference"]["payload"]["identity"] == 84.0
    nov = [e for e in seq["decision_trace"]["evidence"] if e["provider"] == "novelty"][0]
    assert nov["payload"]["signals"]["reference_low_identity"] == pytest.approx(0.6)
    assert nov["payload"]["details"]["embedding_isolation"]["method"] == METHOD_PROXY
