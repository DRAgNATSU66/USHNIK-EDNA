"""
B25: Abyss routes with the learned k-mer router, offline, and says which
router ran.

Abyss used to import the worker's app.model_router, which collides with the
API's own `app` package, so every Abyss result was GC-only. The API now has an
inference-only copy (app/abyss/learned_router.py). These tests check:

  * a registry entry + router.npz routes Abyss results with router_method
    "learned", and the batch reports model_id / version / sha256;
  * the copy gives the same probabilities as the worker's own learned.py on
    the same artifact (synthetic always; the real v1 artifact when present);
  * every way the router can be unavailable is reported, never silent;
  * nothing is fetched: non-local URIs are refused and routing works with
    sockets disabled.
"""
from __future__ import annotations

import importlib.util
import json
import socket
import sys
import types
from pathlib import Path

import numpy as np
import pytest

import app.abyss.analysis as analysis
import app.abyss.learned_router as lr
from app.abyss.models import AbyssSequenceInput, ExpeditionDoc
from app.abyss.offline_pack import build_pack_manifest

REPO = Path(__file__).resolve().parents[3]
WORKER_ROUTER_DIR = REPO / "services" / "worker" / "app" / "model_router"
ROUTES = ["fish", "plant", "bacteria_pathogen", "animal_general",
          "human_domestic_contamination", "misc_unknown"]

SEQS = [
    "ATGCGTACGTTAGCATGCATGCAAGTCGATCGATGCATGCATGCATCGA" * 3,
    "GGCCGGCGCGCCGATCGGCGCCGCGGCGATATCGCGCCGGCGCGCGCCGG" * 2,
    "acgtacgtnnnnacgtTTGACCAGTACGATCGATCGGGATCCATGCAAAT" * 2,
    "AAAAATTTTTAAAAATTTTTAAAAATTTTTAAAAATTTTTAAAAATTTTT",
]
# Abyss QC treats U as invalid (low_quality), so RNA input is only used where
# the router is called directly.
RNA = "UGCAUGCAUGCAUGCAUGCAUGCAUGCAUGCAUGCAUGCAUGCAUGCA"


def _write_artifact(path: Path, k: int = 3, seed: int = 0, temperature: float = 0.5) -> str:
    rng = np.random.default_rng(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = {"version": "vtest", "k": k, "canonical": False, "routes": ROUTES,
           "temperature": temperature, "min_kmers": 1, "model_id": "kmer_router_test"}
    np.savez(
        path,
        weights=rng.normal(size=(4 ** k, len(ROUTES))).astype(np.float32),
        bias=rng.normal(size=len(ROUTES)).astype(np.float32),
        config_json=np.array(json.dumps(cfg)),
    )
    return lr._sha256_file(path)


def _registry(tmp_path: Path, monkeypatch, *, artifact_uri: str | None = None,
              checksum: str | None = None, write: bool = True, entries: bool = True) -> Path:
    data_root = tmp_path / "data"
    reg_dir = tmp_path / "registry"
    reg_dir.mkdir()
    npz = data_root / "checkpoints" / "router" / "vtest" / "router.npz"
    sha = _write_artifact(npz) if write else "0" * 64
    if entries:
        entry = {
            "model_id": "kmer_router_test", "route": "router", "base_model": "kmer3-linear",
            "artifact_uri": artifact_uri or "data:checkpoints/router/vtest/router.npz",
            "checksum": sha if checksum is None else checksum,
            "status": "experimental", "created_at": "2026-10-18",
        }
        (reg_dir / "kmer_router_test.json").write_text(json.dumps(entry))
    monkeypatch.setattr(lr, "_registry_dir", lambda: reg_dir)
    monkeypatch.setattr(lr, "_data_root", lambda: data_root)
    return npz


def _worker_learned(monkeypatch):
    """Import the worker's learned.py + kmer.py under an isolated package name,
    without running the worker package __init__ (and without touching `app`)."""
    name = "_sv_worker_model_router"
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(WORKER_ROUTER_DIR)]
    monkeypatch.setitem(sys.modules, name, pkg)
    for sub in ("kmer", "learned"):
        spec = importlib.util.spec_from_file_location(f"{name}.{sub}", WORKER_ROUTER_DIR / f"{sub}.py")
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, f"{name}.{sub}", mod)
        spec.loader.exec_module(mod)
    return sys.modules[f"{name}.learned"]


def _inputs(seqs=SEQS):
    return [AbyssSequenceInput(sequence_id=f"s{i}", sequence=s) for i, s in enumerate(seqs)]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv(lr.ROUTER_ENV, raising=False)
    analysis._LOGGED_FALLBACKS.clear()
    lr.reset_router()
    yield
    analysis._LOGGED_FALLBACKS.clear()
    lr.reset_router()


# ---------------------------------------------------------------------------
# Learned routing end to end
# ---------------------------------------------------------------------------

def test_abyss_uses_learned_router_from_registry(tmp_path, monkeypatch):
    npz = _registry(tmp_path, monkeypatch)
    res = analysis.run_abyss_analysis("exp_1", _inputs())
    for r in res.results:
        assert r.router_method == "learned"
        assert r.router_version == "vtest"
        assert r.router_error_fallback is False
        assert r.router_fallback_reason is None
        assert r.probabilities_calibrated is True
        assert set(r.route_probabilities) == set(ROUTES)
        assert abs(sum(r.route_probabilities.values()) - 1.0) < 1e-3
        assert r.route == max(r.route_probabilities, key=r.route_probabilities.get)
        assert r.reason_codes[0] == "learned_router"
    assert res.router.method == "learned"
    assert res.router.model_id == "kmer_router_test"
    assert res.router.version == "vtest"
    assert res.router.artifact_sha256 == lr._sha256_file(npz)
    assert res.router.counts == {"learned": len(SEQS)}


def test_low_quality_results_say_gate(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    res = analysis.run_abyss_analysis("exp_1", _inputs(["ACGT"]))
    assert res.results[0].router_method == "low_quality_gate"
    assert res.router.counts == {"low_quality_gate": 1}


def test_sequence_without_valid_kmer_falls_back_per_sequence(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    # IUPAC R passes Abyss QC (valid base, not N) but every 3-mer window has one.
    res = analysis.run_abyss_analysis("exp_1", _inputs(["ACR" * 20, SEQS[0]]))
    bad, good = res.results
    assert bad.router_method == "gc_fallback"
    assert bad.router_fallback_reason == "no_valid_kmers"
    assert bad.router_error_fallback is True
    assert good.router_method == "learned"
    assert res.router.method == "learned"
    assert res.router.counts == {"gc_fallback": 1, "learned": 1}


# ---------------------------------------------------------------------------
# Parity with the worker implementation
# ---------------------------------------------------------------------------

def test_matches_worker_implementation_on_synthetic_artifact(tmp_path, monkeypatch):
    npz = tmp_path / "router.npz"
    sha = _write_artifact(npz, k=4, seed=7, temperature=0.4471)
    worker = _worker_learned(monkeypatch).load_router_artifact(npz, expected_sha256=sha)
    api = lr.load_router_artifact(npz, expected_sha256=sha)
    for s in SEQS + [RNA, "ACR" * 20]:
        w = worker.predict_proba(s.upper())
        a = api.predict_proba(s.upper())
        if w is None:
            assert a is None
            continue
        w_probs, _raw = w
        assert a.keys() == w_probs.keys()
        for route in a:
            assert a[route] == pytest.approx(w_probs[route], abs=1e-6)


_REAL_ENTRY = REPO / "models" / "registry" / "kmer_router_v1.json"


def test_matches_worker_on_real_v1_artifact(monkeypatch):
    """The deployed router v1, when its artifact is on this machine."""
    lr.reset_router()
    model, reason, _detail = lr.get_router()
    if model is None:
        pytest.skip(f"real router artifact not available here ({reason})")
    assert model.model_id == json.loads(_REAL_ENTRY.read_text())["model_id"]
    assert model.sha256 == json.loads(_REAL_ENTRY.read_text())["checksum"]
    worker = _worker_learned(monkeypatch).load_router_artifact(
        model.artifact_path, expected_sha256=model.sha256)
    seqs = [s.upper() for s in SEQS + [RNA]]
    processed = Path(model.artifact_path).parents[3] / "processed"
    for route in ROUTES:
        csv_path = processed / route / "test.csv"
        if csv_path.is_file():
            import csv
            with open(csv_path, newline="", encoding="utf-8") as fh:
                for i, row in enumerate(csv.DictReader(fh)):
                    if i >= 10:
                        break
                    seqs.append(row["sequence"].upper())
    for s in seqs:
        w = worker.predict_proba(s)
        a = model.predict_proba(s)
        if w is None:
            assert a is None
            continue
        for route, p in w[0].items():
            assert a[route] == pytest.approx(p, abs=1e-6)


# ---------------------------------------------------------------------------
# Unavailable router: always reported
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"write": False}, "artifact_missing"),
        ({"checksum": "f" * 64}, "checksum_mismatch"),
        ({"entries": False}, "no_registry_entry"),
        ({"artifact_uri": "zhihan1996/kmer-router"}, "artifact_not_local"),
        ({"artifact_uri": "https://example.org/router.npz"}, "artifact_not_local"),
    ],
)
def test_unavailable_router_is_reported(tmp_path, monkeypatch, kwargs, reason):
    _registry(tmp_path, monkeypatch, **kwargs)
    res = analysis.run_abyss_analysis("exp_1", _inputs(SEQS[:2]))
    for r in res.results:
        assert r.router_method == "gc_fallback"
        assert r.router_fallback_reason == reason
        assert r.router_error_fallback is True
        assert r.router_error.startswith(reason)
        assert r.reason_codes[0] == "router_error_fallback"
        assert r.route_probabilities == {}
    assert res.router.method == "gc_fallback"
    assert res.router.fallback_reason == reason
    assert res.router.model_id is None


def test_corrupt_artifact_is_reported(tmp_path, monkeypatch):
    npz = _registry(tmp_path, monkeypatch)
    npz.write_bytes(b"not an npz")
    reg = next((tmp_path / "registry").glob("*.json"))
    entry = json.loads(reg.read_text())
    entry["checksum"] = lr._sha256_file(npz)
    reg.write_text(json.dumps(entry))
    model, reason, detail = lr.get_router()
    assert model is None
    assert reason == "artifact_load_error"
    assert detail


def test_numpy_missing_is_reported(tmp_path, monkeypatch):
    npz = _registry(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, "numpy", None)
    with pytest.raises(lr.RouterUnavailable) as exc:
        lr.load_router_artifact(npz)
    assert exc.value.reason == "numpy_unavailable"


def test_kill_switch_forces_gc_only(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    monkeypatch.setenv(lr.ROUTER_ENV, "heuristic")
    res = analysis.run_abyss_analysis("exp_1", _inputs(SEQS[:1]))
    r = res.results[0]
    assert r.router_method == "gc_only"
    assert r.router_fallback_reason == lr.FORCED_REASON
    assert r.router_error_fallback is False  # deliberate, not an error
    assert "router_error_fallback" not in r.reason_codes
    assert res.router.method == "gc_only"


# ---------------------------------------------------------------------------
# Offline: nothing is fetched
# ---------------------------------------------------------------------------

def test_routes_with_network_disabled(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)

    def no_network(*_a, **_k):
        raise AssertionError("Abyss routing tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    res = analysis.run_abyss_analysis("exp_1", _inputs())
    assert res.router.method == "learned"
    assert all(r.router_method == "learned" for r in res.results)


# ---------------------------------------------------------------------------
# Pack manifest lists the router as found on disk
# ---------------------------------------------------------------------------

def test_pack_manifest_reports_router_available(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    m = build_pack_manifest(ExpeditionDoc(name="x", created_by="u"))
    comp = next(c for c in m.components if c.component_type == "route_classifier")
    assert comp.status == "available"
    assert comp.name == "kmer_router_test"
    assert comp.artifact_uri == "data:checkpoints/router/vtest/router.npz"
    assert comp.size_mb_estimate > 0


def test_pack_manifest_reports_router_unavailable(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, write=False)
    m = build_pack_manifest(ExpeditionDoc(name="x", created_by="u"))
    comp = next(c for c in m.components if c.component_type == "route_classifier")
    assert comp.status == "unavailable"
    assert "artifact_missing" in comp.description
