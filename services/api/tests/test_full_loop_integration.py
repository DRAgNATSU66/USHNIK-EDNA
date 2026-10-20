"""
Full-loop integration test (t-1025-3, roadmap Day 12):

    upload -> orchestrator -> review -> batch -> freeze -> register -> promote

as ONE test, against real services:

* the real FastAPI app (this package), driven in-process over ASGI;
* the real worker code (services/worker), run as a subprocess with the worker
  venv: it BRPOPs the envelope the API pushed onto Redis and calls
  job_runner.run_job -> parser, learned router, orchestrator (route heads on
  the GPU, BLAST reference lookup, novelty, contamination), report;
* a real MongoDB (an isolated, randomly named database, dropped afterwards),
  a real Redis (a separate logical DB, never the stack's db 0), local upload
  storage in a temp dir, and a temp COPY of models/registry (promotion
  rewrites registry files; the checked-in registry is asserted unchanged).

Input: a handful of real sequences from the held-out TEST split
(<SYNTHVEDA_DATA_ROOT>/processed/<route>/test.csv). They are read at run time,
not checked in: the processed splits mix BOLD (CC BY-SA 4.0, attribution +
share-alike) and other sources with no per-row provenance in the CSV.

What it does NOT do: train. The candidate registered at the end is the
currently serving fish head's artifact (same bytes, checksum verified) under a
new model_id whose training_dataset_version is the frozen batch. Retraining is
`make train-run` (GPU hours) and stays outside the test; the test proves the
plumbing from an upload to a promoted registry entry, not a better model.

Opt-in: skipped unless SYNTHVEDA_LOOP_TEST=1. Run it with `make test-loop`
(see the Makefile for the variables). Prerequisites, each skipped/failed with
its own message: Mongo and Redis reachable, SYNTHVEDA_DATA_ROOT with
processed/ splits, checkpoints/ and reference/, a worker venv with the ML
requirements (SYNTHVEDA_WORKER_PYTHON, default services/worker/.venv/bin/python).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from httpx import ASGITransport, AsyncClient

REPO = Path(__file__).resolve().parents[3]
WORKER_DIR = REPO / "services" / "worker"
REGISTRY_SRC = REPO / "models" / "registry"

ENABLED = os.environ.get("SYNTHVEDA_LOOP_TEST") == "1"
MONGO_URI = os.environ.get("SYNTHVEDA_TEST_MONGO_URI", "mongodb://localhost:27017")
REDIS_URL = os.environ.get("SYNTHVEDA_TEST_REDIS_URL", "redis://localhost:6379/15")
DATA_ROOT = Path(os.environ.get("SYNTHVEDA_DATA_ROOT") or REPO / "synthveda-data")
WORKER_PYTHON = Path(os.environ.get("SYNTHVEDA_WORKER_PYTHON") or WORKER_DIR / ".venv" / "bin" / "python")
WORKER_TIMEOUT_S = int(os.environ.get("SYNTHVEDA_LOOP_WORKER_TIMEOUT_S", "900"))
KEEP_DB = os.environ.get("SYNTHVEDA_LOOP_KEEP_DB") == "1"

# The batch/promotion route, and how many held-out test rows to take per
# (route, label). The bacteria row gives the orchestrator a second route and
# the batch a review it must leave out.
BATCH_ROUTE = "fish"
PICKS = [("fish", "known_species", 2), ("fish", "possible_novelty", 1), ("bacteria_pathogen", "known_species", 1)]
QUEUE_KEY = "synthveda:jobs:analysis"   # app/queue.py and services/worker/app/queue.py

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ENABLED, reason="full-loop integration test is opt-in: SYNTHVEDA_LOOP_TEST=1 (make test-loop)"),
]


def _prerequisite_skips() -> list[str]:
    missing = []
    for route in dict.fromkeys(route for route, _, _ in PICKS):
        if not (DATA_ROOT / "processed" / route / "test.csv").is_file():
            missing.append(f"{DATA_ROOT}/processed/{route}/test.csv")
    for p in ("checkpoints", "reference"):
        if not (DATA_ROOT / p).is_dir():
            missing.append(f"{DATA_ROOT}/{p}/")
    if not WORKER_PYTHON.is_file():
        missing.append(f"worker python {WORKER_PYTHON} (set SYNTHVEDA_WORKER_PYTHON)")
    return missing


def _held_out_sequences() -> list[tuple[str, str, str]]:
    """(fasta id, sequence, test-split label): the first rows of each pick, in file order."""
    out = []
    for route, label, n in PICKS:
        with open(DATA_ROOT / "processed" / route / "test.csv", newline="") as fh:
            rows = [(i, r) for i, r in enumerate(csv.DictReader(fh), start=2) if r["label"] == label][:n]
        assert len(rows) == n, f"{route}/test.csv has fewer than {n} {label} rows"
        out += [(f"heldout_{route}_test_line{line}", r["sequence"], label) for line, r in rows]
    return out


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry_digest(d: Path) -> dict[str, str]:
    return {p.name: _sha256(p) for p in sorted(d.glob("*.json"))}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# Runs in the worker venv with cwd=services/worker, so `app` is the worker
# package. Pops ONE envelope (the API's), refuses anything else, runs it.
_WORKER_DRIVER = r"""
import asyncio, json, sys, time
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_worker_settings
from app.queue import connect_redis, close_redis, dequeue_job
from app.job_runner import run_job

async def main(expected):
    s = get_worker_settings()
    await connect_redis()
    try:
        env = await dequeue_job(timeout=10)
    finally:
        await close_redis()
    if env is None or env.get("job_id") != expected:
        print("LOOP_WORKER_ERROR " + json.dumps({"envelope": env, "expected": expected}))
        sys.exit(3)
    client = AsyncIOMotorClient(s.mongodb_uri)
    t0 = time.perf_counter()
    try:
        await run_job(client[s.mongodb_db], env["job_id"])
    finally:
        client.close()
    print("LOOP_WORKER_RESULT " + json.dumps({"envelope": env, "run_job_s": round(time.perf_counter() - t0, 2)}))

asyncio.run(main(sys.argv[1]))
"""

_WORKER_SELECT = r"""
import json, sys
from app.inference.registry import ModelRegistry
e = ModelRegistry(sys.argv[1], recheck_seconds=0).best_available(sys.argv[2])
print("LOOP_WORKER_SELECTS " + json.dumps(e.model_id if e else None))
"""


def _run_worker(code: str, args: list[str], env: dict, timeout: int) -> tuple[str, subprocess.CompletedProcess]:
    proc = subprocess.run(
        [str(WORKER_PYTHON), "-c", code, *args], cwd=WORKER_DIR, env=env,
        capture_output=True, text=True, timeout=timeout,
    )
    return proc.stdout + proc.stderr, proc


def _tagged(output: str, tag: str):
    for line in output.splitlines():
        if line.startswith(tag + " "):
            return json.loads(line[len(tag) + 1:])
    return None


async def test_full_loop_upload_to_promotion(tmp_path, monkeypatch):
    missing = _prerequisite_skips()
    if missing:
        pytest.skip("full-loop prerequisites missing: " + "; ".join(missing))

    redis_db = int((urlparse(REDIS_URL).path or "/0").lstrip("/") or 0)
    assert redis_db != 0, (
        f"SYNTHVEDA_TEST_REDIS_URL={REDIS_URL} is Redis db 0, the running stack's queue: its worker "
        "would pop this test's job. Use another logical db (default /15)."
    )

    import redis as redis_sync
    from motor.motor_asyncio import AsyncIOMotorClient

    import app.db.mongo as mongo_module
    import app.db.supabase_client as sc_module
    import app.models.router as models_router
    import app.queue as api_queue
    from app.auth.jwt import create_access_token
    from app.config import get_settings
    from app.db import connect_mongo, ensure_indexes
    from app.main import create_app
    from app.models.user import UserRole

    timings: dict[str, float] = {}
    t_start = time.perf_counter()

    def lap(name: str, since: float) -> float:
        now = time.perf_counter()
        timings[name] = round(now - since, 2)
        return now

    db_name = f"synthveda_looptest_{uuid.uuid4().hex[:10]}"
    assert db_name != "synthveda"
    uploads_dir = tmp_path / "uploads"
    registry_dir = tmp_path / "registry"
    shutil.copytree(REGISTRY_SRC, registry_dir)
    repo_registry_before = _registry_digest(REGISTRY_SRC)

    r_sync = redis_sync.Redis.from_url(REDIS_URL)
    try:
        r_sync.ping()
    except Exception as exc:
        pytest.fail(f"Redis not reachable at {REDIS_URL}: {exc!r} (make up starts it)")
    r_sync.delete(QUEUE_KEY)

    probe = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    try:
        await probe.admin.command("ping")
    except Exception as exc:
        pytest.fail(f"MongoDB not reachable at {MONGO_URI}: {exc!r} (make up starts it)")

    # API process state: isolated DB, test Redis db, local storage, no
    # Supabase (no mirror writes leave this machine), registry copy, data root.
    settings = get_settings()
    for k, v in {
        "mongodb_uri": MONGO_URI, "mongodb_db": db_name, "redis_url": REDIS_URL,
        "storage_backend": "local", "upload_storage_dir": str(uploads_dir),
        "environment_context_enabled": False, "supabase_url": "",
    }.items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(mongo_module, "_client", None)
    monkeypatch.setattr(mongo_module, "_db", None)
    monkeypatch.setattr(api_queue, "_redis", None)
    monkeypatch.setattr(sc_module, "_client", None)
    monkeypatch.setattr(models_router, "REGISTRY_DIR", registry_dir)
    monkeypatch.setenv("SYNTHVEDA_DATA_ROOT", str(DATA_ROOT))

    worker_env = {
        **os.environ,
        "MONGODB_URI": MONGO_URI, "MONGODB_DB": db_name, "REDIS_URL": REDIS_URL,
        "STORAGE_BACKEND": "local", "UPLOAD_STORAGE_DIR": str(uploads_dir),
        "MODELS_REGISTRY_PATH": str(registry_dir), "SYNTHVEDA_DATA_ROOT": str(DATA_ROOT),
        "PYTHONUNBUFFERED": "1",
    }

    tok = {
        role: create_access_token(f"usr_loop_{role.value}", {"email": f"{role.value}@loop.test", "role": role, "name": role.value})
        for role in (UserRole.researcher, UserRole.curator, UserRole.admin)
    }
    researcher, curator, admin = tok[UserRole.researcher], tok[UserRole.curator], tok[UserRole.admin]

    await connect_mongo()
    await api_queue.connect_queue()
    db = mongo_module.get_db()
    assert db.name == db_name
    try:
        await ensure_indexes(db)
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://loop") as api:
            t = time.perf_counter()

            # -- 1. upload ------------------------------------------------
            seqs = _held_out_sequences()
            fasta = "".join(f">{sid}\n{s}\n" for sid, s, _ in seqs).encode()
            r = await api.post("/uploads", headers=_auth(researcher),
                               files={"file": ("loop_heldout.fasta", fasta, "text/plain")},
                               data={"habitat": "marine", "methodology": "integration test, held-out split"})
            assert r.status_code == 201, r.text
            upload = r.json()
            assert upload["storage_uri"].startswith("local://") and upload["checksum_sha256"] == hashlib.sha256(fasta).hexdigest()

            r = await api.post("/analysis/jobs", headers=_auth(researcher), json={"upload_id": upload["upload_id"]})
            assert r.status_code == 202, r.text
            job_id = r.json()["job_id"]
            assert r_sync.llen(QUEUE_KEY) == 1, "the API did not enqueue the job on the test Redis db"
            t = lap("upload_and_enqueue_s", t)

            # -- 2. worker: queue -> parse -> route -> orchestrator -> report
            out, proc = _run_worker(_WORKER_DRIVER, [job_id], worker_env, WORKER_TIMEOUT_S)
            assert proc.returncode == 0, f"worker run failed (rc={proc.returncode}):\n{out[-6000:]}"
            worker_result = _tagged(out, "LOOP_WORKER_RESULT")
            assert worker_result and worker_result["envelope"]["job_id"] == job_id, out[-3000:]
            worker_log = [line for line in out.splitlines() if line.startswith("[worker]")]
            t = lap("worker_subprocess_s", t)
            timings["worker_run_job_s"] = worker_result["run_job_s"]

            r = await api.get(f"/analysis/jobs/{job_id}", headers=_auth(researcher))
            assert r.status_code == 200 and r.json()["state"] == "completed", r.text
            analysis_id = r.json()["analysis_id"]
            r = await api.get(f"/analysis/{analysis_id}", headers=_auth(researcher))
            assert r.status_code == 200, r.text
            analysis = r.json()
            assert analysis["orchestrator_version"]
            results = {res["sequence_id"]: res for res in analysis["results"]}
            assert set(results) == {sid for sid, _, _ in seqs}
            for res in results.values():
                assert res["decision"] and res["decision"]["final_route"] == res["route"], res["sequence_id"]
                trace = res["decision_trace"]
                assert trace and {"orchestrator_version", "plan", "evidence", "combine"} <= set(trace), res["sequence_id"]
                assert res["router_method"] == "learned", (res["sequence_id"], res["router_method"], res["router_fallback_reason"])
                assert res["inference_mode"] == "model", (res["sequence_id"], res["inference_mode"], res.get("stub_reason"))
            batch_route_ids = {sid for sid, res in results.items() if res["route"] == BATCH_ROUTE}
            assert batch_route_ids, f"no sequence was routed to {BATCH_ROUTE}: {[(s, r['route']) for s, r in results.items()]}"
            t = lap("read_analysis_s", t)

            # -- 3. reviews: the worker's auto reviews + one species correction
            r = await api.get("/reviews/queue", headers=_auth(curator), params={"limit": 200})
            assert r.status_code == 200, r.text
            auto_reviews = r.json()
            assert all(rv["analysis_id"] == analysis_id for rv in auto_reviews)

            # What Species Correction (web_frontend SpeciesCorrection.jsx)
            # sends: one on a batch-route sequence (must join the batch) and
            # one on an off-route sequence, if any (must not).
            manual = []
            off_route = sorted(set(results) - batch_route_ids)
            for target in [sorted(batch_route_ids)[0]] + off_route[:1]:
                r = await api.post("/reviews", headers=_auth(researcher), json={
                    "analysis_id": analysis_id, "sequence_id": target,
                    "correction_type": "species_correction",
                    "proposed_taxon": results[target]["decision"].get("predicted_taxon"),
                    "evidence_notes": "loop test: curator confirms the orchestrator's assignment",
                })
                assert r.status_code == 201, r.text
                manual.append(r.json())

            decided = auto_reviews + manual
            for rv in decided:
                r = await api.post(f"/reviews/{rv['review_id']}/decision", headers=_auth(curator),
                                   json={"decision": "accept", "notes": "loop test accept"})
                assert r.status_code == 200 and r.json()["new_state"] == "accepted", r.text
                assert r.json()["supabase_mirror"] == "not_configured"
            n_decisions = await db["curation_decisions"].count_documents({"analysis_id": analysis_id})
            assert n_decisions == len(decided)
            snapshots = [d async for d in db["review_evidence"].find({"evidence_type": "result_snapshot"})]
            assert {d["review_id"] for d in snapshots} == {rv["review_id"] for rv in decided}
            assert all(d["payload"]["result"].get("decision_trace") for d in snapshots)
            t = lap("reviews_s", t)

            # -- 4. batch: only accepted reviews whose sequence is on the batch route
            expected_in_batch = {rv["review_id"] for rv in decided if rv["sequence_id"] in batch_route_ids}
            r = await api.post("/reviews/batch/create", headers=_auth(admin),
                               json={"route": BATCH_ROUTE, "month_year": "2026-10"})
            assert r.status_code == 200, r.text
            batch = r.json()
            batch_id = batch["batch_id"]
            items = [d async for d in db["training_batch_items"].find({"batch_id": batch_id})]
            assert {d["review_id"] for d in items} == expected_in_batch, (
                f"batch {batch_id} holds {sorted(d['review_id'] for d in items)}, expected the accepted "
                f"{BATCH_ROUTE}-route reviews {sorted(expected_in_batch)}"
            )
            assert batch["sequence_count"] == len(expected_in_batch)
            for rv in decided:
                doc = await db["reviews"].find_one({"review_id": rv["review_id"]})
                if rv["review_id"] in expected_in_batch:
                    assert (doc["state"], doc["training_batch_id"]) == ("included_in_training_batch", batch_id)
                else:
                    assert (doc["state"], doc["training_batch_id"]) == ("accepted", None)

            # -- 5. freeze
            r = await api.post(f"/reviews/batch/{batch_id}/freeze", headers=_auth(admin))
            assert r.status_code == 200 and r.json()["status"] == "frozen", r.text
            assert await db["audit_logs"].count_documents({"action": "training_batch_frozen", "batch_id": batch_id}) == 1
            assert await db["training_batch_items"].count_documents({"batch_id": batch_id, "frozen_at": None}) == 0
            r = await api.post("/reviews/batch/tbatch_does_not_exist/freeze", headers=_auth(admin))
            assert r.status_code == 404, r.text
            t = lap("batch_and_freeze_s", t)

            # -- 6. register a candidate (the serving fish head's bytes, new id)
            serving = json.loads((registry_dir / "dnabert2_fish_v2.json").read_text())
            assert serving["status"] == "production"
            head = DATA_ROOT / serving["artifact_uri"][len("data:"):]
            model_id = f"loop_{BATCH_ROUTE}_{uuid.uuid4().hex[:8]}"
            r = await api.post("/models/register", headers=_auth(admin), json={
                "model_id": model_id, "route": BATCH_ROUTE, "base_model": serving["base_model"],
                "artifact_uri": serving["artifact_uri"], "checksum": _sha256(head),
                "metrics": serving["metrics"], "label_set_version": serving["label_set_version"],
                "label_set": serving["label_set"], "training_dataset_version": batch_id,
                "trusted_remote_code": serving.get("trusted_remote_code", False),
                "notes": f"t-1025-3 loop test: {serving['model_id']} weights re-registered against frozen batch {batch_id}; not retrained",
            })
            assert r.status_code == 201, r.text
            assert r.json()["serving_model_id"] == serving["model_id"]  # a candidate is never served

            # -- 7. promote: the Admin page's dry run, then the real one
            r = await api.post(f"/models/{model_id}/promote", headers=_auth(admin), json={"dry_run": True})
            assert r.status_code == 200 and r.json()["current_model_id"] == serving["model_id"], r.text
            r = await api.post(f"/models/{model_id}/promote", headers=_auth(admin), json={
                "expected_current_model_id": serving["model_id"], "notes": "t-1025-3 loop test"})
            assert r.status_code == 200, r.text
            promoted = r.json()
            assert promoted["serving_model_id"] == model_id and promoted["demoted_model_ids"] == [serving["model_id"]]

            mem = await db["model_eval_metrics"].find_one({"model_id": model_id})
            assert mem and mem["event"] == "promotion" and mem["training_dataset_version"] == batch_id
            assert mem["accuracy"] == serving["metrics"]["test_accuracy"] and mem["compared_to_model_id"] == serving["model_id"]
            assert await db["audit_logs"].count_documents({"action": {"$in": ["model_registered", "model_promoted"]},
                                                           "model_id": model_id}) == 2
            assert json.loads((registry_dir / f"{model_id}.json").read_text())["status"] == "production"
            assert json.loads((registry_dir / "dnabert2_fish_v2.json").read_text())["status"] == "staging"
            t = lap("register_and_promote_s", t)

            # -- 8. the worker's own registry code now selects the promoted model
            out, proc = _run_worker(_WORKER_SELECT, [str(registry_dir), BATCH_ROUTE], worker_env, 120)
            assert proc.returncode == 0, out[-3000:]
            assert _tagged(out, "LOOP_WORKER_SELECTS") == model_id, out[-3000:]
            t = lap("worker_selects_s", t)

        # Nothing leaked into the checked-in registry or the stack's database.
        assert _registry_digest(REGISTRY_SRC) == repo_registry_before
        live = probe["synthveda"]
        assert await live["uploads"].find_one({"upload_id": upload["upload_id"]}) is None
        assert await live["analysis_jobs"].find_one({"job_id": job_id}) is None

        timings["total_s"] = round(time.perf_counter() - t_start, 2)
        summary = {
            "db": db_name, "sequences": [(sid, label, results[sid]["route"], results[sid]["decision"]["result_class"],
                                          results[sid]["decision"].get("predicted_taxon")) for sid, _, label in seqs],
            "auto_reviews": [(rv["review_type"], rv["sequence_id"]) for rv in auto_reviews],
            "batch": {"batch_id": batch_id, "items": len(items)}, "promoted": model_id,
            "worker_log": worker_log, "timings": timings,
        }
        print("\nLOOP_SUMMARY " + json.dumps(summary, default=str, indent=1))
    finally:
        await api_queue.close_queue()
        await mongo_module.close_mongo()
        if not KEEP_DB:
            await probe.drop_database(db_name)
        probe.close()
        r_sync.delete(QUEUE_KEY)
        r_sync.close()
