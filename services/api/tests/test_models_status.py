"""GET /models/status and /models/registry: built from the registry, honest about artifacts (B1, B13)."""
import json
import logging

import pytest

import app.models.router as models_router

ALL_ROUTES = {
    "fish", "plant", "bacteria_pathogen", "animal_general",
    "human_domestic_contamination", "misc_unknown",
}


def _entry(model_id, route, **overrides):
    e = {
        "model_id": model_id,
        "route": route,
        "base_model": f"data:checkpoints/{route}/backbone",
        "artifact_uri": f"data:checkpoints/{route}/head.pt",
        "status": "experimental",
        "created_at": "2026-08-03",
        "label_set_version": "v1",
        "metrics": {"test_accuracy": 0.5, "test_macro_f1": 0.4},
    }
    e.update(overrides)
    return e


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Point the router at an empty temp registry and an empty temp data root."""
    reg = tmp_path / "registry"
    reg.mkdir()
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setattr(models_router, "REGISTRY_DIR", reg)
    monkeypatch.setenv("SYNTHVEDA_DATA_ROOT", str(data_root))

    def write(name, content):
        text = content if isinstance(content, str) else json.dumps(content)
        (reg / name).write_text(text, encoding="utf-8")

    def make_artifacts(route, backbone=True, head=True):
        ck = data_root / "checkpoints" / route
        if backbone:
            (ck / "backbone").mkdir(parents=True, exist_ok=True)
        if head:
            ck.mkdir(parents=True, exist_ok=True)
            (ck / "head.pt").write_bytes(b"\0")

    return write, make_artifacts


@pytest.mark.anyio
async def test_status_lists_all_six_routes_from_real_registry(client):
    data = (await client.get("/models/status")).json()
    assert set(data["routes"]) == ALL_ROUTES
    assert data["errors"] == []
    assert data["worker_state"] == "not_observable"
    for route, info in data["routes"].items():
        # The checked-in registry has a runnable DNABERT-2 entry for every route.
        assert info["model_id"], route
        assert info["status"] in {"ready", "missing_artifacts", "unverified", "no_model"}
        assert info["inference_mode"] in {"model", "stub"}
        assert info["status"] != "loaded"


@pytest.mark.anyio
async def test_status_metrics_come_from_registry_entry(client, registry):
    write, make_artifacts = registry
    write("fish.json", _entry("fish_v9", "fish", metrics={"test_accuracy": 0.123}))
    make_artifacts("fish")
    fish = (await client.get("/models/status")).json()["routes"]["fish"]
    assert fish["status"] == "ready"
    assert fish["reason"] == "artifacts_resolved"
    assert fish["inference_mode"] == "model"
    assert fish["model_id"] == "fish_v9"
    assert fish["metrics"] == {"test_accuracy": 0.123}
    assert fish["artifacts"]["backbone"]["present"] is True
    assert fish["artifacts"]["head"]["present"] is True


@pytest.mark.anyio
async def test_missing_artifacts_reported_honestly(client, registry):
    write, _ = registry
    write("plant.json", _entry("plant_v1", "plant"))
    plant = (await client.get("/models/status")).json()["routes"]["plant"]
    assert plant["status"] == "missing_artifacts"
    assert plant["reason"] == "backbone_not_found"
    assert plant["inference_mode"] == "stub"
    assert plant["artifacts"]["backbone"]["present"] is False
    assert plant["artifacts"]["head"]["present"] is False


@pytest.mark.anyio
async def test_missing_head_warns_about_random_init(client, registry):
    write, make_artifacts = registry
    write("animal.json", _entry("animal_v1", "animal_general"))
    make_artifacts("animal_general", backbone=True, head=False)
    info = (await client.get("/models/status")).json()["routes"]["animal_general"]
    assert info["status"] == "missing_artifacts"
    assert info["reason"] == "head_weights_not_found"
    # The worker would still run (random head) and call it "model" — say so.
    assert info["inference_mode"] == "model"
    assert any("randomly initialised" in w for w in info["warnings"])


@pytest.mark.anyio
async def test_route_without_runnable_entry_is_stub(client, registry):
    write, _ = registry
    write("nt.json", _entry("nt_fish", "fish", artifact_uri=None, base_model="org/some-hub-model"))
    routes = (await client.get("/models/status")).json()["routes"]
    assert set(routes) == ALL_ROUTES
    assert routes["fish"]["status"] == "no_model"
    assert routes["fish"]["reason"] == "no_runnable_registry_entry"
    assert routes["fish"]["registered_model_ids"] == ["nt_fish"]
    assert routes["fish"]["inference_mode"] == "stub"
    assert routes["plant"]["reason"] == "no_registry_entry"


@pytest.mark.anyio
async def test_selection_mirrors_worker_tier_order(client, registry):
    write, make_artifacts = registry
    write("a.json", _entry("fish_prod", "fish", status="production", created_at="2026-01-01"))
    write("b.json", _entry("fish_exp_newer", "fish", status="experimental", created_at="2026-09-01"))
    write("c.json", _entry("fish_retired", "fish", status="retired", created_at="2026-10-01"))
    make_artifacts("fish")
    fish = (await client.get("/models/status")).json()["routes"]["fish"]
    assert fish["model_id"] == "fish_prod"
    assert fish["registry_status"] == "production"


@pytest.mark.anyio
async def test_malformed_registry_files_are_logged_and_reported(client, registry, caplog):
    write, _ = registry
    write("good.json", _entry("fish_v1", "fish"))
    write("broken.json", '{"model_id": "x", ')
    write("no_route.json", {"model_id": "y", "base_model": "data:x"})
    write("a_list.json", [1, 2])

    with caplog.at_level(logging.WARNING, logger="app.models.router"):
        status = (await client.get("/models/status")).json()
        reg = (await client.get("/models/registry")).json()

    for body in (status, reg):
        files = {e["file"]: e["error"] for e in body["errors"]}
        assert set(files) == {"broken.json", "no_route.json", "a_list.json"}
        assert "route" in files["no_route.json"]
        assert "JSON object" in files["a_list.json"]

    assert [m["model_id"] for m in reg["models"]] == ["fish_v1"]
    assert reg["count"] == 1
    assert status["routes"]["fish"]["model_id"] == "fish_v1"
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "broken.json" in logged and "no_route.json" in logged
