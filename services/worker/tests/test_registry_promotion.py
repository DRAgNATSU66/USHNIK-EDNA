"""
Worker side of B8: what a promotion written by the API changes in selection.

The API registers models as status "candidate" and promotes by rewriting the
entry with status "production" (os.replace). These tests pin the worker's half:
candidates are never selected, production beats a newer experimental entry,
a long-lived registry notices the rewrite, and the learned-router cache
reloads when the router selection changes.
"""
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.inference.registry as registry_mod
from app.inference.registry import ModelRegistry
from app.model_router import learned
from app.model_router.learned import sha256_file

ROUTES = ["fish", "plant", "bacteria_pathogen", "animal_general", "human_domestic_contamination", "misc_unknown"]


def _write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)  # same as the API's write_json_atomic


def _entry(model_id, route="fish", status="experimental", created_at="2026-08-03", **kw):
    return {"model_id": model_id, "route": route, "base_model": "data:checkpoints/fish/backbone",
            "artifact_uri": f"data:checkpoints/{model_id}/head.pt", "status": status,
            "created_at": created_at, **kw}


def test_candidate_is_never_selected(tmp_path):
    _write(tmp_path / "v1.json", _entry("fish_v1"))
    _write(tmp_path / "v2.json", _entry("fish_v2", status="candidate", created_at="2026-10-18"))
    reg = ModelRegistry(tmp_path)
    assert reg.best_available("fish").model_id == "fish_v1"
    assert [e.model_id for e in reg.for_route("fish")] == ["fish_v1"]
    # Alone on its route, a candidate still does not serve.
    _write(tmp_path / "p.json", _entry("plant_v2", route="plant", status="candidate"))
    reg.refresh()
    assert reg.best_available("plant") is None


def test_production_beats_newer_experimental(tmp_path):
    _write(tmp_path / "v1.json", _entry("fish_v1", status="production", created_at="2026-08-03"))
    _write(tmp_path / "v3.json", _entry("fish_v3", created_at="2026-12-01"))
    assert ModelRegistry(tmp_path).best_available("fish").model_id == "fish_v1"


def test_long_lived_registry_notices_a_promotion(tmp_path):
    _write(tmp_path / "v1.json", _entry("fish_v1"))
    _write(tmp_path / "v2.json", _entry("fish_v2", status="candidate", created_at="2026-10-18"))
    reg = ModelRegistry(tmp_path, recheck_seconds=0)
    assert reg.best_available("fish").model_id == "fish_v1"
    _write(tmp_path / "v2.json", _entry("fish_v2", status="production", created_at="2026-10-18"))
    assert reg.best_available("fish").model_id == "fish_v2"


def test_recheck_is_throttled(tmp_path, monkeypatch):
    _write(tmp_path / "v1.json", _entry("fish_v1"))
    reg = ModelRegistry(tmp_path, recheck_seconds=3600)
    assert reg.best_available("fish").model_id == "fish_v1"
    _write(tmp_path / "v2.json", _entry("fish_v2", status="production"))
    # Within the window the cached view is served; refresh() forces a reload.
    assert reg.best_available("fish").model_id == "fish_v1"
    reg.refresh()
    assert reg.best_available("fish").model_id == "fish_v2"


def _router_npz(path, favour):
    w = np.zeros((16, len(ROUTES)), np.float32)
    b = np.zeros(len(ROUTES), np.float32)
    b[ROUTES.index(favour)] = 5.0
    cfg = {"version": favour, "routes": ROUTES, "k": 2, "canonical": False, "temperature": 1.0}
    np.savez_compressed(path, weights=w, bias=b, config_json=np.array(json.dumps(cfg)))
    return sha256_file(path)


@pytest.fixture
def router_registry(tmp_path, monkeypatch):
    reg_dir = tmp_path / "registry"
    reg_dir.mkdir()
    reg = ModelRegistry(reg_dir, recheck_seconds=0)
    monkeypatch.setattr(registry_mod, "get_registry", lambda: reg)
    monkeypatch.delenv("SYNTHVEDA_ROUTER", raising=False)
    learned.reset_learned_router()
    yield tmp_path, reg_dir
    learned.reset_learned_router()


def test_router_cache_follows_a_router_promotion(router_registry):
    tmp_path, reg_dir = router_registry
    for name, favour in (("r1", "fish"), ("r2", "plant")):
        sha = _router_npz(tmp_path / f"{name}.npz", favour)
        status = "experimental" if name == "r1" else "candidate"
        _write(reg_dir / f"{name}.json", {"model_id": f"kmer_{name}", "route": "router", "base_model": "kmer2",
                                          "artifact_uri": str(tmp_path / f"{name}.npz"), "checksum": sha,
                                          "status": status, "created_at": "2026-10-18"})
    model, reason = learned.get_learned_router()
    assert (model.model_id, reason) == ("kmer_r1", None)
    # Registering the candidate changes nothing.
    assert learned.get_learned_router()[0].model_id == "kmer_r1"

    entry = json.loads((reg_dir / "r2.json").read_text())
    _write(reg_dir / "r2.json", {**entry, "status": "production"})
    model, _ = learned.get_learned_router()
    assert model.model_id == "kmer_r2"
    assert model.version == "plant"


def test_pinned_router_is_kept(router_registry):
    tmp_path, reg_dir = router_registry
    sha = _router_npz(tmp_path / "r1.npz", "fish")
    _write(reg_dir / "r1.json", {"model_id": "kmer_r1", "route": "router", "base_model": "kmer2",
                                 "artifact_uri": str(tmp_path / "r1.npz"), "checksum": sha,
                                 "status": "experimental", "created_at": "2026-10-18"})
    pinned = learned.load_router_artifact(tmp_path / "r1.npz", model_id="pinned")
    learned.set_learned_router(pinned)
    assert learned.get_learned_router()[0].model_id == "pinned"
