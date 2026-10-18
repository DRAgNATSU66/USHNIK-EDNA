"""
Tests for the learned k-mer router (B19): featurisation, artifact loading,
the never-silent heuristic fallback, and an integration test against the real
artifact that is skipped when the artifact is not on this machine.
"""
import csv
import json
import os
import random
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.model_router import learned
from app.model_router.kmer import kmer_indices, kmer_matrix, kmer_vector, n_features
from app.model_router.learned import (
    LearnedRouterModel,
    RouterLoadError,
    load_from_registry,
    load_router_artifact,
    sha256_file,
)
from app.model_router.models import RouterInput, RouterMethod, TaxonomicRoute
from app.model_router.router import route_batch, route_sequence, route_sequence_heuristic
from app.inference.registry import ModelRegistry

ROUTES = ["fish", "plant", "bacteria_pathogen", "animal_general", "human_domestic_contamination", "misc_unknown"]


@pytest.fixture(autouse=True)
def _reset_router(monkeypatch):
    monkeypatch.delenv("SYNTHVEDA_ROUTER", raising=False)
    learned.reset_learned_router()
    yield
    learned.reset_learned_router()


def _inp(seq: str, seq_id: str = "s1", n_ratio: float = 0.0) -> RouterInput:
    return RouterInput(sequence_id=seq_id, sequence=seq, length=len(seq), gc_ratio=0.5, n_ratio=n_ratio, sha256="x")


def _toy_model(k: int = 2, favour: str = "fish", version: str = "test") -> LearnedRouterModel:
    """A model whose bias makes `favour` the clear winner for any input."""
    w = np.zeros((4 ** k, len(ROUTES)), dtype=np.float32)
    b = np.zeros(len(ROUTES), dtype=np.float32)
    b[ROUTES.index(favour)] = 5.0
    return LearnedRouterModel(model_id="kmer_router_test", version=version, routes=ROUTES, k=k,
                              canonical=False, weights=w, bias=b, temperature=1.0)


def _save_toy(path: Path, k: int = 2, temperature: float = 2.0, weights=None) -> str:
    w = np.random.default_rng(0).normal(size=(4 ** k, len(ROUTES))).astype(np.float32) if weights is None else weights
    cfg = {"version": "vtest", "routes": ROUTES, "k": k, "canonical": False, "temperature": temperature}
    np.savez_compressed(path, weights=w, bias=np.zeros(len(ROUTES), np.float32), config_json=np.array(json.dumps(cfg)))
    return sha256_file(path)


# ---------------------------------------------------------------------------
# Featurisation
# ---------------------------------------------------------------------------

class TestKmerFeatures:
    def test_indices_are_base4(self):
        # AC=0*4+1=1, CG=1*4+2=6, GT=2*4+3=11
        assert kmer_indices("ACGT", 2).tolist() == [1, 6, 11]

    def test_windows_with_non_acgt_are_skipped(self):
        # windows: AC, CN, NG, GT -> only AC and GT survive
        assert kmer_indices("ACNGT", 2).tolist() == [1, 11]
        assert kmer_indices("NNNNNN", 3).size == 0

    def test_lowercase_and_u_are_accepted(self):
        assert kmer_indices("acgu", 2).tolist() == kmer_indices("ACGT", 2).tolist()

    def test_shorter_than_k_is_empty(self):
        assert kmer_indices("ACG", 4).size == 0
        idx, vals = kmer_vector("ACG", 4)
        assert idx.size == 0 and vals.size == 0

    def test_canonical_is_strand_invariant(self):
        seq = "ATGCGTACCGTTAGGCATTAC"
        rc = seq.translate(str.maketrans("ACGT", "TGCA"))[::-1]
        a_idx, a_val = kmer_vector(seq, 5, canonical=True)
        b_idx, b_val = kmer_vector(rc, 5, canonical=True)
        assert a_idx.tolist() == b_idx.tolist()
        assert np.allclose(a_val, b_val)
        # Non-canonical features differ between strands.
        assert kmer_vector(seq, 5)[0].tolist() != kmer_vector(rc, 5)[0].tolist()

    def test_vector_is_l2_normalised_counts(self):
        idx, vals = kmer_vector("AAAAC", 2)  # AA x3, AC x1
        assert idx.tolist() == [0, 1]
        assert np.isclose(np.linalg.norm(vals), 1.0)
        assert np.isclose(vals[0] / vals[1], 3.0)

    def test_matrix_rows_match_vectors(self):
        seqs = ["ACGTACGTAA", "TTTT", "NNNN", "GGGCCC"]
        X = kmer_matrix(seqs, 3)
        assert X.shape == (4, n_features(3))
        for i, s in enumerate(seqs):
            idx, vals = kmer_vector(s, 3)
            row = X.getrow(i)
            assert row.indices.tolist() == idx.tolist()
            assert np.allclose(row.data, vals)

    def test_invalid_k_rejected(self):
        with pytest.raises(ValueError):
            kmer_indices("ACGT", 0)


# ---------------------------------------------------------------------------
# Artifact loading
# ---------------------------------------------------------------------------

class TestArtifact:
    def test_round_trip(self, tmp_path):
        p = tmp_path / "router.npz"
        sha = _save_toy(p, temperature=2.0)
        m = load_router_artifact(p, model_id="m1", expected_sha256=sha)
        assert m.version == "vtest" and m.k == 2 and m.temperature == 2.0 and m.routes == ROUTES
        probs, raw = m.predict_proba("ACGTACGTTTGA")
        assert set(probs) == set(ROUTES)
        assert abs(sum(probs.values()) - 1.0) < 1e-6
        # Temperature only rescales: the argmax of probs and raw logits agree.
        assert max(probs, key=probs.get) == max(raw, key=raw.get)

    def test_missing_file(self, tmp_path):
        with pytest.raises(RouterLoadError) as e:
            load_router_artifact(tmp_path / "nope.npz")
        assert e.value.reason == "artifact_missing"

    def test_checksum_mismatch(self, tmp_path):
        p = tmp_path / "router.npz"
        _save_toy(p)
        with pytest.raises(RouterLoadError) as e:
            load_router_artifact(p, expected_sha256="0" * 64)
        assert e.value.reason == "checksum_mismatch"

    def test_shape_mismatch_is_load_error(self, tmp_path):
        p = tmp_path / "router.npz"
        _save_toy(p, k=2, weights=np.zeros((10, len(ROUTES)), np.float32))
        with pytest.raises(RouterLoadError) as e:
            load_router_artifact(p)
        assert e.value.reason == "artifact_load_error"

    def test_load_from_registry(self, tmp_path):
        p = tmp_path / "router.npz"
        sha = _save_toy(p)
        reg = tmp_path / "registry"
        reg.mkdir()
        (reg / "kmer_router_vtest.json").write_text(json.dumps({
            "model_id": "kmer_router_vtest", "route": "router", "base_model": str(tmp_path),
            "artifact_uri": str(p), "checksum": sha, "status": "experimental", "created_at": "2026-10-17",
        }))
        m = load_from_registry(ModelRegistry(registry_dir=reg))
        assert m.model_id == "kmer_router_vtest"

    def test_registry_without_router_entry(self, tmp_path):
        with pytest.raises(RouterLoadError) as e:
            load_from_registry(ModelRegistry(registry_dir=tmp_path))
        assert e.value.reason == "no_registry_entry"


# ---------------------------------------------------------------------------
# Routing with the learned model and the visible fallback
# ---------------------------------------------------------------------------

SEQ = "ATGCGTACCGTTAGGCATTACGGATCCATGCAAGT" * 4


class TestLearnedRouting:
    def test_learned_result(self):
        learned.set_learned_router(_toy_model(favour="plant"))
        r = route_sequence(_inp(SEQ))
        assert r.route == TaxonomicRoute.plant
        assert r.router_method == RouterMethod.learned == "learned"
        assert r.router_version == "test"
        assert r.router_fallback_reason is None
        assert r.probabilities_calibrated is True
        assert set(r.route_probabilities) == set(ROUTES)
        assert abs(sum(r.route_probabilities.values()) - 1.0) < 1e-6
        assert r.route_confidence == round(r.route_probabilities["plant"], 4)
        assert "learned_router" in r.reason_codes
        assert "misc_unknown" in r.fallback_routes

    def test_low_quality_gate_runs_first(self):
        learned.set_learned_router(_toy_model())
        r = route_sequence(_inp("ACGT"))
        assert r.route == TaxonomicRoute.low_quality
        assert r.router_method == "low_quality_gate"

    def test_to_dict_carries_router_fields(self):
        learned.set_learned_router(_toy_model())
        d = route_sequence(_inp(SEQ)).to_dict()
        for key in ("router_method", "router_version", "route_probabilities",
                    "probabilities_calibrated", "router_fallback_reason"):
            assert key in d
        json.dumps(d)

    def test_batch_uses_learned(self):
        learned.set_learned_router(_toy_model(favour="fish"))
        res = route_batch([_inp(SEQ, f"s{i}") for i in range(3)])
        assert [r.router_method for r in res] == ["learned"] * 3
        assert [r.sequence_id for r in res] == ["s0", "s1", "s2"]


class TestFallback:
    def test_missing_artifact_falls_back_visibly(self):
        learned.set_learned_router(None, reason="artifact_missing")
        r = route_sequence(_inp(SEQ))
        h = route_sequence_heuristic(_inp(SEQ))
        assert r.route == h.route                      # same decision as the heuristic
        assert r.router_method == "heuristic_fallback"
        assert r.router_fallback_reason == "artifact_missing"
        assert "router_heuristic_fallback" in r.reason_codes
        assert r.router_version is None
        assert r.probabilities_calibrated is False
        assert abs(sum(r.route_probabilities.values()) - 1.0) < 1e-6

    def test_no_registry_entry_falls_back(self, monkeypatch, tmp_path):
        monkeypatch.setattr(learned, "load_from_registry",
                            lambda registry=None: load_from_registry(ModelRegistry(registry_dir=tmp_path)))
        r = route_sequence(_inp(SEQ))
        assert r.router_method == "heuristic_fallback"
        assert r.router_fallback_reason == "no_registry_entry"

    def test_unexpected_load_exception_falls_back(self, monkeypatch):
        def boom(registry=None):
            raise RuntimeError("registry exploded")
        monkeypatch.setattr(learned, "load_from_registry", boom)
        r = route_sequence(_inp(SEQ))
        assert r.router_method == "heuristic_fallback"
        assert r.router_fallback_reason == "router_load_error"

    def test_load_failure_is_cached(self, monkeypatch):
        calls = []

        def missing(registry=None):
            calls.append(1)
            raise RouterLoadError("artifact_missing")
        monkeypatch.setattr(learned, "load_from_registry", missing)
        route_batch([_inp(SEQ, f"s{i}") for i in range(5)])
        assert len(calls) == 1

    def test_no_valid_kmers_falls_back_per_sequence(self):
        learned.set_learned_router(_toy_model(k=2))
        # 40 IUPAC 'R' bases: passes the gate (not N, long enough), no ACGT k-mer.
        r = route_sequence(_inp("R" * 40))
        assert r.router_method == "heuristic_fallback"
        assert r.router_fallback_reason == "no_valid_kmers"
        # The next normal sequence still uses the learned model.
        assert route_sequence(_inp(SEQ)).router_method == "learned"

    def test_predict_exception_falls_back(self, monkeypatch):
        m = _toy_model()
        learned.set_learned_router(m)
        monkeypatch.setattr(m, "predict_proba", lambda s: (_ for _ in ()).throw(ValueError("bad")))
        r = route_sequence(_inp(SEQ))
        assert r.router_method == "heuristic_fallback"
        assert r.router_fallback_reason == "predict_error"

    def test_env_kill_switch_forces_heuristic(self, monkeypatch):
        learned.set_learned_router(_toy_model())
        monkeypatch.setenv("SYNTHVEDA_ROUTER", "heuristic")
        r = route_sequence(_inp(SEQ))
        assert r.router_method == "heuristic"
        assert r.router_fallback_reason == "router_forced_heuristic"
        assert "router_heuristic_fallback" not in r.reason_codes


# ---------------------------------------------------------------------------
# Integration: the real artifact from the registry (skipped when absent)
# ---------------------------------------------------------------------------

def _real_router_or_skip():
    try:
        return load_from_registry()
    except RouterLoadError as exc:
        pytest.skip(f"learned router artifact not available here ({exc.reason})")


class TestRealArtifact:
    def test_real_router_routes_held_out_sequences(self):
        model = _real_router_or_skip()
        from app.inference.registry import _resolve_data_root

        processed = _resolve_data_root() / "processed"
        if not processed.is_dir():
            pytest.skip("processed/ test splits not available")
        learned.set_learned_router(model)
        rng = random.Random(1)
        correct = total = 0
        for route in ROUTES:
            with open(processed / route / "test.csv", newline="") as fh:
                rows = [r["sequence"] for r in csv.DictReader(fh) if r["label"] != "low_quality_unusable"]
            for seq in rng.sample(rows, 25):
                from app.fastx_parser import compute_qc
                gc, nr, _, sha = compute_qc(seq)
                r = route_sequence(RouterInput(sequence_id="t", sequence=seq, length=len(seq),
                                               gc_ratio=gc, n_ratio=nr, sha256=sha))
                if r.router_method == "learned":
                    assert abs(sum(r.route_probabilities.values()) - 1.0) < 1e-5
                    assert r.router_version == model.version
                correct += str(r.route) == route
                total += 1
        # The heuristic scores ~24% on this protocol; the learned router must be far above it.
        assert correct / total >= 0.75, f"{correct}/{total}"

    def test_default_route_sequence_uses_learned_router(self):
        _real_router_or_skip()
        r = route_sequence(_inp(SEQ))
        assert r.router_method == "learned", r.router_fallback_reason


def _revcomp(s: str) -> str:
    return s.translate(str.maketrans("ACGTN", "TGCAN"))[::-1]


class TestRealV2Artifact:
    """Router v2 (B23): registered as a candidate, so it is loaded straight from
    its registry entry rather than through selection. Skipped when absent."""

    def _v2(self):
        from app.inference.registry import ModelRegistry

        entry = ModelRegistry().get("kmer_router_v2")
        if entry is None:
            pytest.skip("kmer_router_v2 not in the registry")
        try:
            return load_router_artifact(entry.artifact_uri, model_id=entry.model_id, expected_sha256=entry.checksum)
        except RouterLoadError as exc:
            pytest.skip(f"router v2 artifact not available here ({exc.reason})")

    def test_v2_is_candidate_and_not_served(self):
        from app.inference.registry import ModelRegistry

        reg = ModelRegistry()
        entry = reg.get("kmer_router_v2")
        if entry is None:
            pytest.skip("kmer_router_v2 not in the registry")
        assert entry.status == "candidate"
        assert reg.best_available("router").model_id != "kmer_router_v2"

    def test_v2_routes_both_strands_of_held_out_sequences(self):
        model = self._v2()
        from app.inference.registry import _resolve_data_root

        processed = _resolve_data_root() / "processed"
        if not processed.is_dir():
            pytest.skip("processed/ test splits not available")
        rng = random.Random(2)
        fwd = rc = total = 0
        for route in ROUTES:
            with open(processed / route / "test.csv", newline="") as fh:
                rows = [r["sequence"].upper() for r in csv.DictReader(fh) if r["label"] != "low_quality_unusable"]
            for seq in rng.sample(rows, 25):
                pf, _ = model.predict_proba(seq)
                pr, _ = model.predict_proba(_revcomp(seq))
                # Strand-invariant by construction when canonical; within float
                # tolerance for any v2 the protocol could have selected.
                for r in ROUTES:
                    assert pr[r] == pytest.approx(pf[r], abs=1e-4)
                fwd += max(pf, key=pf.get) == route
                rc += max(pr, key=pr.get) == route
                total += 1
        assert fwd / total >= 0.75, f"{fwd}/{total}"
        assert rc / total >= 0.75, f"{rc}/{total}"
