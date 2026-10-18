"""POST /models/register, POST /models/{id}/promote, GET /models/promotions (B8)."""
import hashlib
import json
from types import SimpleNamespace

import pytest

import app.models.router as models_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction):
        self._docs.sort(key=lambda d: d.get(key), reverse=direction < 0)
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._docs:
            return self._docs.pop(0)
        raise StopAsyncIteration


class _Coll:
    def __init__(self):
        self.docs = []
        self.fail = False

    async def insert_one(self, doc):
        if self.fail:
            raise ConnectionError("mongo down")
        doc = {**doc, "_id": f"id{len(self.docs) + 1}"}
        self.docs.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    async def delete_one(self, q):
        self.docs = [d for d in self.docs if d["_id"] != q["_id"]]

    def find(self, q, projection=None):
        wanted = q.get("action", {}).get("$in")
        docs = [
            {k: v for k, v in d.items() if k != "_id"}
            for d in self.docs if wanted is None or d.get("action") in wanted
        ]
        return _Cursor(docs)


class _Db:
    def __init__(self):
        self.colls = {}

    def __getitem__(self, name):
        return self.colls.setdefault(name, _Coll())


@pytest.fixture
def db(monkeypatch):
    fake = _Db()
    monkeypatch.setattr(models_router, "get_db", lambda: fake)
    return fake


@pytest.fixture
def env(tmp_path, monkeypatch, db):
    """Temp registry + data root with a served fish v1 and an artifact for a v2."""
    reg = tmp_path / "registry"
    reg.mkdir()
    data_root = tmp_path / "data"
    monkeypatch.setattr(models_router, "REGISTRY_DIR", reg)
    monkeypatch.setenv("SYNTHVEDA_DATA_ROOT", str(data_root))

    def artifact(rel, content):
        p = data_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    (data_root / "checkpoints/fish/backbone").mkdir(parents=True)
    v1_sha = artifact("checkpoints/fish/head.pt", b"head-v1")
    v2_sha = artifact("checkpoints/fish/v2/head.pt", b"head-v2")
    router_sha = artifact("checkpoints/router/v2/router.npz", b"router-v2")
    (reg / "fish_v1.json").write_text(json.dumps({
        "model_id": "fish_v1", "route": "fish",
        "base_model": "data:checkpoints/fish/backbone",
        "artifact_uri": "data:checkpoints/fish/head.pt", "checksum": v1_sha,
        "status": "experimental", "created_at": "2026-08-03",
        "label_set_version": "v1", "training_dataset_version": "2026-08-03-cap5000",
        "metrics": {"test_accuracy": 0.95, "test_macro_f1": 0.80, "test_size": 500},
    }, indent=2) + "\n")
    return SimpleNamespace(reg=reg, data_root=data_root, v2_sha=v2_sha, router_sha=router_sha, db=db)


def _register_body(**overrides):
    body = {
        "model_id": "fish_v2",
        "route": "fish",
        "base_model": "data:checkpoints/fish/backbone",
        "artifact_uri": "data:checkpoints/fish/v2/head.pt",
        "checksum": None,
        "metrics": {"test_accuracy": 0.97, "test_macro_f1": 0.86, "test_size": 520},
        "label_set_version": "v1",
        "training_dataset_version": "tbatch_202610_fish",
        "label_set": ["known_species", "possible_novelty", "low_quality_unusable"],
        "created_at": "2026-10-18",
    }
    body.update(overrides)
    return body


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _register(client, env, admin_token, **overrides):
    body = _register_body(**overrides)
    if body["checksum"] is None:
        body["checksum"] = env.v2_sha
    return await client.post("/models/register", json=body, headers=_auth(admin_token))


def _file(env, name):
    return json.loads((env.reg / name).read_text())


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/models/register", "/models/fish_v1/promote"])
async def test_write_endpoints_require_admin(client, env, researcher_token, curator_token, path):
    body = _register_body(checksum=env.v2_sha) if path.endswith("register") else {}
    assert (await client.post(path, json=body)).status_code == 401
    assert (await client.post(path, json=body, headers=_auth(researcher_token))).status_code == 403
    assert (await client.post(path, json=body, headers=_auth(curator_token))).status_code == 403
    assert sorted(p.name for p in env.reg.iterdir()) == ["fish_v1.json"]


@pytest.mark.anyio
async def test_promotions_log_requires_admin(client, env, curator_token):
    assert (await client.get("/models/promotions")).status_code == 401
    assert (await client.get("/models/promotions", headers=_auth(curator_token))).status_code == 403


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_register_writes_a_candidate_that_is_not_served(client, env, admin_token):
    r = await _register(client, env, admin_token)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["registry_file"] == "fish_v2.json"
    # Newer created_at than fish_v1, but a candidate never outranks a serving tier.
    assert out["serving_model_id"] == "fish_v1"
    saved = _file(env, "fish_v2.json")
    assert saved["status"] == "candidate"
    assert saved["checksum"] == env.v2_sha
    assert saved["registered_by"] == "usr_admin_001"
    status = (await client.get("/models/status")).json()["routes"]["fish"]
    assert status["model_id"] == "fish_v1"
    assert "fish_v2" in status["registered_model_ids"]
    [audit] = env.db["audit_logs"].docs
    assert audit["action"] == "model_registered"
    assert audit["actor_email"] == "admin@example.com"


@pytest.mark.anyio
async def test_register_rejects_checksum_mismatch(client, env, admin_token):
    r = await _register(client, env, admin_token, checksum="0" * 64)
    assert r.status_code == 422
    assert "checksum mismatch" in r.json()["detail"]
    assert not (env.reg / "fish_v2.json").exists()
    assert env.db["audit_logs"].docs == []


@pytest.mark.anyio
@pytest.mark.parametrize("uri,needle", [
    ("data:checkpoints/fish/v3/head.pt", "not found"),
    ("data:../outside/head.pt", "inside the data root"),
    ("data:/etc/head.pt", "inside the data root"),
    ("hf://synthveda/fish_v2", "data:<relative path>"),
    ("data:checkpoints/fish/v2/eval_report.json", "must end in .pt or .bin"),
])
async def test_register_rejects_bad_artifact_uri(client, env, admin_token, uri, needle):
    r = await _register(client, env, admin_token, artifact_uri=uri)
    assert r.status_code == 422
    assert needle in r.json()["detail"]
    assert not (env.reg / "fish_v2.json").exists()


@pytest.mark.anyio
@pytest.mark.parametrize("metrics,needle", [
    ({"test_accuracy": 0.9, "test_size": 10}, "missing metric test_macro_f1"),
    ({"test_accuracy": 1.2, "test_macro_f1": 0.8, "test_size": 10}, "must be in [0, 1]"),
    ({"test_accuracy": 0.9, "test_macro_f1": 0.8, "test_size": 0}, "positive integer"),
    ({"test_accuracy": True, "test_macro_f1": 0.8, "test_size": 10}, "finite number"),
])
async def test_register_requires_metrics(client, env, admin_token, metrics, needle):
    r = await _register(client, env, admin_token, metrics=metrics)
    assert r.status_code == 422
    assert needle in r.json()["detail"]


@pytest.mark.anyio
async def test_register_rejects_duplicates_bad_ids_and_routes(client, env, admin_token):
    assert (await _register(client, env, admin_token)).status_code == 201
    dup = await _register(client, env, admin_token)
    assert dup.status_code == 409
    # Same model_id as an existing entry stored under another file name.
    assert (await _register(client, env, admin_token, model_id="fish_v1")).status_code == 409
    assert (await _register(client, env, admin_token, model_id="../evil")).status_code == 422
    assert (await _register(client, env, admin_token, model_id="x2", route="low_quality")).status_code == 422
    missing_backbone = await _register(client, env, admin_token, model_id="fish_v3",
                                       base_model="data:checkpoints/fish/nope")
    assert missing_backbone.status_code == 422


@pytest.mark.anyio
async def test_register_rolls_back_when_audit_fails(client, env, admin_token):
    env.db["audit_logs"].fail = True
    r = await _register(client, env, admin_token)
    assert r.status_code == 503
    assert not (env.reg / "fish_v2.json").exists()


# ---------------------------------------------------------------------------
# Promote
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_promote_dry_run_shows_deltas_and_writes_nothing(client, env, admin_token):
    await _register(client, env, admin_token)
    before = {p.name: p.read_bytes() for p in env.reg.glob("*.json")}
    r = await client.post("/models/fish_v2/promote", json={"dry_run": True}, headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["dry_run"] is True
    assert plan["current_model_id"] == "fish_v1"
    assert plan["from_status"] == "candidate"
    deltas = {d["metric"]: d for d in plan["metric_deltas"]}
    assert [d["metric"] for d in plan["metric_deltas"]][:3] == ["test_accuracy", "test_macro_f1", "test_size"]
    assert deltas["test_macro_f1"] == {"metric": "test_macro_f1", "candidate": 0.86, "current": 0.80, "delta": 0.06}
    assert any("dataset versions differ" in w for w in plan["warnings"])
    assert {p.name: p.read_bytes() for p in env.reg.glob("*.json")} == before
    assert "model_eval_metrics" not in env.db.colls


@pytest.mark.anyio
async def test_promote_changes_selection_and_records_metrics_and_audit(client, env, admin_token):
    await _register(client, env, admin_token)
    r = await client.post(
        "/models/fish_v2/promote",
        json={"expected_current_model_id": "fish_v1", "notes": "Oct batch"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["serving_model_id"] == "fish_v2"

    promoted = _file(env, "fish_v2.json")
    assert promoted["status"] == "production"
    assert promoted["promoted_by"] == "usr_admin_001"
    assert promoted["promoted_from_status"] == "candidate"
    # fish_v1 was experimental, not production: nothing to demote.
    assert _file(env, "fish_v1.json")["status"] == "experimental"

    status = (await client.get("/models/status")).json()["routes"]["fish"]
    assert status["model_id"] == "fish_v2"
    assert status["registry_status"] == "production"
    assert status["status"] == "ready"
    reg = (await client.get("/models/registry")).json()
    assert reg["selected_by_route"]["fish"] == "fish_v2"

    [m] = env.db["model_eval_metrics"].docs
    assert (m["model_id"], m["eval_set"], m["accuracy"], m["f1_macro"], m["n"]) == ("fish_v2", "test", 0.97, 0.86, 520)
    assert m["compared_to_model_id"] == "fish_v1"
    assert m["checksum"] == env.v2_sha
    promo_audit = [a for a in env.db["audit_logs"].docs if a["action"] == "model_promoted"]
    assert len(promo_audit) == 1
    a = promo_audit[0]
    assert (a["previous_model_id"], a["actor_id"], a["notes"]) == ("fish_v1", "usr_admin_001", "Oct batch")

    log = (await client.get("/models/promotions", headers=_auth(admin_token))).json()["events"]
    assert [e["action"] for e in log] == ["model_promoted", "model_registered"]


@pytest.mark.anyio
async def test_second_promotion_demotes_the_first(client, env, admin_token):
    await _register(client, env, admin_token)
    assert (await client.post("/models/fish_v2/promote", json={}, headers=_auth(admin_token))).status_code == 200
    # fish_v1 is older but goes straight to production; v2 must step down.
    r = await client.post("/models/fish_v1/promote", json={"dry_run": True}, headers=_auth(admin_token))
    assert r.json()["current_model_id"] == "fish_v2"
    assert r.json()["demoted_model_ids"] == ["fish_v2"]
    r = await client.post("/models/fish_v1/promote", json={}, headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    v2 = _file(env, "fish_v2.json")
    assert (v2["status"], v2["demoted_for"]) == ("staging", "fish_v1")
    assert _file(env, "fish_v1.json")["status"] == "production"
    statuses = [_file(env, n)["status"] for n in ("fish_v1.json", "fish_v2.json")]
    assert statuses.count("production") == 1
    assert (await client.get("/models/status")).json()["routes"]["fish"]["model_id"] == "fish_v1"


@pytest.mark.anyio
async def test_promote_refuses_stale_confirmation(client, env, admin_token):
    await _register(client, env, admin_token)
    before = (env.reg / "fish_v2.json").read_bytes()
    r = await client.post("/models/fish_v2/promote", json={"expected_current_model_id": "fish_v0"},
                          headers=_auth(admin_token))
    assert r.status_code == 409
    assert (env.reg / "fish_v2.json").read_bytes() == before


@pytest.mark.anyio
async def test_promote_reverifies_checksum(client, env, admin_token):
    await _register(client, env, admin_token)
    (env.data_root / "checkpoints/fish/v2/head.pt").write_bytes(b"swapped after registration")
    r = await client.post("/models/fish_v2/promote", json={}, headers=_auth(admin_token))
    assert r.status_code == 422
    assert "checksum mismatch" in r.json()["detail"]
    assert _file(env, "fish_v2.json")["status"] == "candidate"


@pytest.mark.anyio
@pytest.mark.parametrize("failing", ["model_eval_metrics", "audit_logs"])
async def test_promote_rolls_back_when_a_record_cannot_be_written(client, env, admin_token, failing):
    await _register(client, env, admin_token)
    assert (await client.post("/models/fish_v2/promote", json={}, headers=_auth(admin_token))).status_code == 200
    await _register(client, env, admin_token, model_id="fish_v3")
    before = {p.name: p.read_bytes() for p in env.reg.glob("*.json")}
    n_metrics = len(env.db["model_eval_metrics"].docs)
    env.db[failing].fail = True
    r = await client.post("/models/fish_v3/promote", json={}, headers=_auth(admin_token))
    assert r.status_code == 503
    assert {p.name: p.read_bytes() for p in env.reg.glob("*.json")} == before
    assert len(env.db["model_eval_metrics"].docs) == n_metrics
    assert not list(env.reg.glob(".*.tmp"))


@pytest.mark.anyio
async def test_promote_status_errors(client, env, admin_token):
    assert (await client.post("/models/nope/promote", json={}, headers=_auth(admin_token))).status_code == 404
    await _register(client, env, admin_token)
    await client.post("/models/fish_v2/promote", json={}, headers=_auth(admin_token))
    again = await client.post("/models/fish_v2/promote", json={}, headers=_auth(admin_token))
    assert again.status_code == 409
    retired = {**_file(env, "fish_v1.json"), "status": "retired"}
    (env.reg / "fish_v1.json").write_text(json.dumps(retired))
    assert (await client.post("/models/fish_v1/promote", json={}, headers=_auth(admin_token))).status_code == 409


@pytest.mark.anyio
async def test_promote_rejects_legacy_entry_without_required_metrics(client, env, admin_token):
    (env.reg / "nt.json").write_text(json.dumps({
        "model_id": "nt_fish", "route": "fish", "base_model": "InstaDeepAI/nt-50m",
        "artifact_uri": None, "status": "experimental", "metrics": {},
    }))
    r = await client.post("/models/nt_fish/promote", json={}, headers=_auth(admin_token))
    assert r.status_code == 422
    assert "missing metric test_accuracy" in r.json()["detail"]


@pytest.mark.anyio
async def test_router_entry_registers_and_promotes(client, env, admin_token):
    r = await _register(
        client, env, admin_token,
        model_id="kmer_router_v2", route="router", base_model="kmer8-linear-svm",
        artifact_uri="data:checkpoints/router/v2/router.npz", checksum=env.router_sha,
        label_set_version="routes-v1",
    )
    assert r.status_code == 201, r.text
    assert _file(env, "kmer_router_v2.json")["head_type"] == "route_classification"
    # A router entry must point at an .npz.
    bad = await _register(client, env, admin_token, model_id="kmer_router_v3", route="router",
                          base_model="kmer8-linear-svm")
    assert bad.status_code == 422
    r = await client.post("/models/kmer_router_v2/promote", json={"expected_current_model_id": None},
                          headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert "no model currently serves" in r.json()["warnings"][0]
    sel = (await client.get("/models/registry")).json()["selected_by_route"]
    assert sel["router"] == "kmer_router_v2"
    assert sel["fish"] == "fish_v1"


@pytest.mark.anyio
async def test_registry_lists_selection_for_real_registry(client):
    data = (await client.get("/models/registry")).json()
    assert set(data["selected_by_route"]) == set(models_router.MODEL_ROUTES) | {"router"}


# ---------------------------------------------------------------------------
# Supabase mirror (model_versions + model_eval_metrics, best-effort)
# ---------------------------------------------------------------------------

class _FakeSupabase:
    """Records SupabaseClient calls; `fail` makes promote_model raise."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def install(self, monkeypatch):
        for name in ("_get", "get_training_batch_uuid", "register_model_version",
                     "upsert_eval_metrics", "promote_model"):
            monkeypatch.setattr(models_router.SupabaseClient, name, getattr(self, name))

    def _get(self):
        return object()

    async def get_training_batch_uuid(self, batch_id):
        self.calls.append(("batch", batch_id))
        return "batch-uuid"

    async def register_model_version(self, data):
        self.calls.append(("model_versions", data))
        return {"id": f"uuid-{data['model_id']}", **data}

    async def upsert_eval_metrics(self, version_id, eval_set, row):
        self.calls.append(("model_eval_metrics", version_id, eval_set, row))
        return row

    async def promote_model(self, model_id, promoted_by):
        if self.fail:
            raise ConnectionError("supabase down")
        self.calls.append(("promote", model_id, promoted_by))


@pytest.mark.anyio
async def test_supabase_not_configured_is_reported_not_fatal(client, env, admin_token):
    r = await _register(client, env, admin_token)
    assert r.json()["supabase_mirror"] == "not_configured"
    r = await client.post("/models/fish_v2/promote", json={}, headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.json()["supabase_mirror"] == "not_configured"


@pytest.mark.anyio
async def test_register_and_promote_mirror_model_versions_and_eval_metrics(client, env, admin_token, monkeypatch):
    fake = _FakeSupabase()
    fake.install(monkeypatch)
    r = await _register(client, env, admin_token)
    assert r.json()["supabase_mirror"] == "written"
    [batch, version, metrics] = fake.calls
    assert batch == ("batch", "tbatch_202610_fish")
    assert version[1]["status"] == "candidate"
    assert version[1]["training_batch_id"] == "batch-uuid"
    assert version[1]["checksum"] == env.v2_sha
    assert metrics == ("model_eval_metrics", "uuid-fish_v2", "test",
                       {"f1": 0.86, "accuracy": 0.97, "sample_count": 520})

    fake.calls.clear()
    r = await client.post("/models/fish_v2/promote", json={}, headers=_auth(admin_token))
    assert r.json()["supabase_mirror"] == "written"
    assert fake.calls[-1] == ("promote", "fish_v2", "usr_admin_001")
    # The row is upserted with its pre-promotion status; promote_model flips it.
    assert [c[1]["status"] for c in fake.calls if c[0] == "model_versions"] == ["candidate"]


@pytest.mark.anyio
async def test_supabase_failure_does_not_undo_a_promotion(client, env, admin_token, monkeypatch):
    await _register(client, env, admin_token)
    _FakeSupabase(fail=True).install(monkeypatch)
    r = await client.post("/models/fish_v2/promote", json={}, headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["supabase_mirror"] == "failed"
    assert _file(env, "fish_v2.json")["status"] == "production"
    assert len(env.db["model_eval_metrics"].docs) == 1


def test_eval_metric_rows_maps_test_and_dev_metrics():
    from app.models.promotion import eval_metric_rows
    rows = dict(eval_metric_rows({"test_accuracy": 0.99, "test_macro_f1": 0.8, "test_size": 505,
                                  "dev_accuracy": 0.98, "dev_size": 500, "dev_loss_best": 0.04}))
    assert rows == {"test": {"f1": 0.8, "accuracy": 0.99, "sample_count": 505},
                    "val": {"accuracy": 0.98, "sample_count": 500}}
    # dev_size alone is not an evaluation.
    assert [s for s, _ in eval_metric_rows({"test_accuracy": 0.9, "dev_size": 10})] == ["test"]
