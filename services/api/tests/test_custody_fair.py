"""
t-1027-2 tests: hash-chained chain of custody (app/custody/) and the FAIR ZIP
export (app/reports/fair.py, GET /reports/{id}/export/fair).

The shared conftest mock DB returns a fresh empty collection per access, so
these tests use a small stateful in-memory stand-in (_FakeDb) that keeps
documents and enforces the same unique constraints db/indexes.py creates on
custody_events: (chain_id, seq) and the partial (chain_id, event_key). With
`interleave=True` every find/insert yields to the event loop, so concurrent
appends really do race on the head.
"""
from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import io
import itertools
import json
import zipfile
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pymongo.errors import DuplicateKeyError

import app.db.mongo as _mongo_module
from app.auth.jwt import create_access_token
from app.custody import (
    GENESIS_HASH,
    append_event,
    canonical_json,
    ensure_analysis_events,
    event_hash,
    load_chain,
    record_upload_created,
    results_sha256,
    verify_chain,
)
from app.custody.chain import CUSTODY_COLLECTION, chain_id_for_upload
from app.models.upload import OPTIONAL_METADATA_FIELDS
from app.models.user import UserRole
from app.reports import fair


# ---------------------------------------------------------------------------
# Stateful in-memory Mongo stand-in
# ---------------------------------------------------------------------------

def _get_path(doc: dict, dotted: str):
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction=1):
        if isinstance(key, list):
            key, direction = key[0]
        self._docs.sort(key=lambda d: _get_path(d, key), reverse=direction < 0)
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    def limit(self, n):
        if n:
            self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._docs:
            return self._docs.pop(0)
        raise StopAsyncIteration


class _FakeColl:
    _ids = itertools.count(1)

    def __init__(self, unique=(), interleave=False):
        # unique: [(fields, partial_field_or_None)]; partial = only docs where
        # that field is a string participate (mirrors partialFilterExpression).
        self.docs: list[dict] = []
        self.unique = unique
        self.interleave = interleave
        self.fail_inserts = False

    def _matches(self, doc, flt):
        return all(_get_path(doc, k) == v for k, v in (flt or {}).items())

    async def find_one(self, flt=None, sort=None, **_):
        if self.interleave:
            await asyncio.sleep(0)
        found = [d for d in self.docs if self._matches(d, flt)]
        if sort:
            key, direction = sort[0]
            found.sort(key=lambda d: _get_path(d, key), reverse=direction < 0)
        return copy.deepcopy(found[0]) if found else None

    def find(self, flt=None, *_a, **_k):
        return _Cursor(copy.deepcopy(d) for d in self.docs if self._matches(d, flt))

    async def insert_one(self, doc):
        if self.interleave:
            await asyncio.sleep(0)
        if self.fail_inserts:
            raise RuntimeError("simulated database outage")
        for fields, partial in self.unique:
            if partial and not isinstance(doc.get(partial), str):
                continue
            for d in self.docs:
                if partial and not isinstance(d.get(partial), str):
                    continue
                if all(d.get(f) == doc.get(f) for f in fields):
                    raise DuplicateKeyError(f"duplicate key on {fields}")
        stored = copy.deepcopy(doc)
        stored["_id"] = next(self._ids)
        self.docs.append(stored)
        return MagicMock(inserted_id=stored["_id"])

    async def update_one(self, flt, update, **_):
        for d in self.docs:
            if self._matches(d, flt):
                d.update(copy.deepcopy(update.get("$set", {})))
                return MagicMock(matched_count=1, modified_count=1)
        return MagicMock(matched_count=0, modified_count=0)


class _FakeDb:
    def __init__(self, interleave=False, custody_unique=True):
        unique = [(("chain_id", "seq"), None), (("chain_id", "event_key"), "event_key")] if custody_unique else []
        self._colls = {CUSTODY_COLLECTION: _FakeColl(unique, interleave)}

    def __getitem__(self, name):
        if name not in self._colls:
            self._colls[name] = _FakeColl()
        return self._colls[name]


# ---------------------------------------------------------------------------
# Fixtures and data
# ---------------------------------------------------------------------------

OWNER = "usr_test_001"  # researcher_token's user
RAW_FASTA = b">seq_001\nATCGATCGATCGATCGATCG\n>seq_002\nGCATGCATGCATGCAT\n"


def _upload_doc(storage_uri=None, checksum=None, **metadata):
    doc = {
        "upload_id": "upl_cust_001",
        "user_id": OWNER,
        "original_filename": "stn14 sample.fasta",
        "file_size_bytes": len(RAW_FASTA),
        "status": "stored",
        "storage_uri": storage_uri,
        "checksum_sha256": checksum,
        "created_at": datetime(2026, 10, 18, 9, 30, 0),
    }
    doc.update({f: None for f in OPTIONAL_METADATA_FIELDS})
    doc.update(metadata)
    return doc


def _result(seq_id, route="fish", **extra):
    r = {
        "sequence_id": seq_id,
        "sequence": "ATCGATCGATCGATCGATCG",
        "sha256": hashlib.sha256(seq_id.encode()).hexdigest(),
        "length": 20,
        "gc_ratio": 0.5,
        "n_ratio": 0.0,
        "route": route,
        "route_confidence": 0.91,
        "router_method": "learned",
        "router_version": "router-v2",
        "result_class": "known_species",
        "predicted_taxon": "Sardinella longiceps",
        "confidence": 0.88,
        "inference_mode": "local",
        "model_version_used": f"{route}-v2",
        "novelty_score": 0.1,
        "contamination_flagged": False,
        "reason_codes": ["high_confidence"],
    }
    r.update(extra)
    return r


def _analysis_doc(results=None, upload_id="upl_cust_001", analysis_id="ana_cust_001"):
    return {
        "analysis_id": analysis_id,
        "job_id": "job_cust_001",
        "upload_id": upload_id,
        "user_id": OWNER,
        "mode": "local",
        "created_at": datetime(2026, 10, 18, 10, 0, 0),
        "results": results if results is not None else [_result("seq_001"), _result("seq_002", route="human_domestic_contamination")],
    }


@pytest.fixture
def fake_db():
    return _FakeDb()


@pytest.fixture
async def fclient(app_instance, fake_db):
    with patch.object(_mongo_module, "_db", fake_db), patch.object(_mongo_module, "_client", MagicMock()):
        async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
            yield ac


@pytest.fixture
def other_researcher_token():
    return create_access_token(
        "usr_other_002", {"email": "other@example.com", "role": UserRole.researcher, "name": "Other"},
    )


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    """Point local upload storage at tmp_path and store RAW_FASTA there."""
    from app import storage as storage_mod
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_backend", "local")
    monkeypatch.setattr(get_settings(), "upload_storage_dir", str(tmp_path / "uploads"))
    storage_mod.clear_cache()
    store = storage_mod.storage_from_settings(get_settings())
    stored = store.put(storage_mod.upload_key("upl_cust_001", "stn14 sample.fasta"), BytesIO(RAW_FASTA))
    yield stored
    storage_mod.clear_cache()


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """A data root with one reference manifest (v2) carrying licence notes."""
    root = tmp_path / "synthveda-data"
    (root / "reference" / "v2").mkdir(parents=True)
    (root / "reference" / "v2" / "manifest.json").write_text(json.dumps({
        "version": "v2",
        "created": "2026-10-18T12:55:35+00:00",
        "builder": "services/worker/training/build_reference_db.py",
        "licences": {"midori2": "CC BY 4.0", "unite": "CC BY-SA 4.0"},
        "sources": [{"source": "midori2", "name": "MIDORI2_GB273_RAW.zip", "licence": "CC BY 4.0"}],
        "sources_absent": ["bold"],
    }))
    monkeypatch.setenv("SYNTHVEDA_DATA_ROOT", str(root))
    return root


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _custody_docs(db):
    return db[CUSTODY_COLLECTION].docs


# ---------------------------------------------------------------------------
# Pure hashing
# ---------------------------------------------------------------------------

def test_canonical_json_is_key_order_independent():
    a = {"b": 1, "a": {"y": [1, 2], "x": "é"}}
    b = {"a": {"x": "é", "y": [1, 2]}, "b": 1}
    assert canonical_json(a) == canonical_json(b) == '{"a":{"x":"é","y":[1,2]},"b":1}'


def test_event_hash_is_sha256_of_prev_hash_concat_canonical_body():
    ev = {"seq": 0, "chain_id": "c", "payload": {"k": 1}, "prev_hash": GENESIS_HASH, "hash": "ignored", "_id": 7}
    body = '{"chain_id":"c","payload":{"k":1},"seq":0}'
    assert event_hash(GENESIS_HASH, ev) == hashlib.sha256((GENESIS_HASH + body).encode()).hexdigest()


def test_results_sha256_changes_with_any_result_field():
    results = [_result("seq_001")]
    edited = copy.deepcopy(results)
    edited[0]["predicted_taxon"] = "Something else"
    assert results_sha256(results) == results_sha256(copy.deepcopy(results))
    assert results_sha256(results) != results_sha256(edited)


# ---------------------------------------------------------------------------
# Append + verify
# ---------------------------------------------------------------------------

async def _append_n(db, n, chain="upload:upl_x"):
    for i in range(n):
        await append_event(db, chain, "test_event", actor={"type": "system", "id": "t"},
                           subject={"upload_id": "upl_x"}, payload={"i": i})


async def test_append_builds_linked_chain_that_verifies(fake_db):
    await _append_n(fake_db, 4)
    events = await load_chain(fake_db, "upload:upl_x")
    assert [e["seq"] for e in events] == [0, 1, 2, 3]
    assert events[0]["prev_hash"] == GENESIS_HASH
    for prev, cur in zip(events, events[1:]):
        assert cur["prev_hash"] == prev["hash"]
    v = verify_chain(events, "upload:upl_x")
    assert v["valid"] is True and v["first_break"] is None
    assert v["length"] == 4 and v["head_hash"] == events[-1]["hash"]


async def test_tampered_event_content_is_reported_as_first_break(fake_db):
    await _append_n(fake_db, 4)
    # Edit one stored event in place (what a direct DB write would do).
    _custody_docs(fake_db)[1]["payload"]["i"] = 99
    v = verify_chain(await load_chain(fake_db, "upload:upl_x"))
    assert v["valid"] is False
    assert v["first_break"]["seq"] == 1
    assert "altered" in v["first_break"]["reason"]


async def test_tamper_with_recomputed_hash_breaks_the_next_link(fake_db):
    await _append_n(fake_db, 4)
    ev = _custody_docs(fake_db)[1]
    ev["payload"]["i"] = 99
    ev["hash"] = event_hash(ev["prev_hash"], ev)  # forger re-hashes the edited event
    v = verify_chain(await load_chain(fake_db, "upload:upl_x"))
    assert v["valid"] is False
    assert v["first_break"]["seq"] == 2
    assert "prev_hash" in v["first_break"]["reason"]


async def test_deleted_middle_event_is_reported(fake_db):
    await _append_n(fake_db, 4)
    del _custody_docs(fake_db)[2]
    v = verify_chain(await load_chain(fake_db, "upload:upl_x"))
    assert v["valid"] is False
    assert v["first_break"]["index"] == 2 and v["first_break"]["seq"] == 3


async def test_concurrent_appends_do_not_fork_the_chain():
    db = _FakeDb(interleave=True)
    await asyncio.gather(*[
        append_event(db, "upload:upl_x", "test_event", actor={"type": "system", "id": str(i)},
                     subject={}, payload={"i": i})
        for i in range(20)
    ])
    events = await load_chain(db, "upload:upl_x")
    assert [e["seq"] for e in events] == list(range(20))
    assert sorted(e["payload"]["i"] for e in events) == list(range(20))
    assert verify_chain(events)["valid"] is True


async def test_without_the_unique_index_concurrent_appends_would_fork():
    # Control for the test above: the same race with no (chain_id, seq)
    # uniqueness produces duplicate seqs, which verify_chain rejects.
    db = _FakeDb(interleave=True, custody_unique=False)
    await asyncio.gather(*[
        append_event(db, "upload:upl_x", "test_event", actor={"type": "system", "id": str(i)},
                     subject={}, payload={"i": i})
        for i in range(5)
    ])
    events = await load_chain(db, "upload:upl_x")
    assert len({e["seq"] for e in events}) < len(events)
    assert verify_chain(events)["valid"] is False


async def test_analysis_completed_is_idempotent_even_under_concurrency():
    db = _FakeDb(interleave=True)
    doc, upload = _analysis_doc(), _upload_doc()
    await asyncio.gather(*[ensure_analysis_events(db, doc, upload) for _ in range(6)])
    await ensure_analysis_events(db, doc, upload)
    events = await load_chain(db, chain_id_for_upload("upl_cust_001"))
    types = [e["event_type"] for e in events]
    assert types.count("analysis_completed") == 1
    assert types.count("upload_created") == 1
    completed = next(e for e in events if e["event_type"] == "analysis_completed")
    assert completed["payload"]["results_sha256"] == results_sha256(doc["results"])
    assert completed["payload"]["result_count"] == 2
    backfilled = next(e for e in events if e["event_type"] == "upload_created")
    assert backfilled["payload"]["derived"] is True
    assert verify_chain(events)["valid"] is True


async def test_upload_created_recorded_live_is_not_duplicated_by_backfill(fake_db):
    upload = _upload_doc(collector="M. Fernandes", ph=8.1)
    await record_upload_created(fake_db, upload, actor={"type": "user", "user_id": OWNER, "role": "researcher"})
    await ensure_analysis_events(fake_db, _analysis_doc(), upload)
    events = await load_chain(fake_db, chain_id_for_upload("upl_cust_001"))
    ups = [e for e in events if e["event_type"] == "upload_created"]
    assert len(ups) == 1 and ups[0]["payload"]["derived"] is False
    # The collector's name never enters the immutable chain; only field names.
    assert "M. Fernandes" not in canonical_json(events)
    assert ups[0]["payload"]["metadata_fields_provided"] == ["ph", "collector"]


# ---------------------------------------------------------------------------
# API hooks: upload and review actions append events
# ---------------------------------------------------------------------------

async def test_post_upload_appends_upload_created(fclient, fake_db, researcher_token, tmp_path, monkeypatch):
    from app import storage as storage_mod
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "upload_storage_dir", str(tmp_path / "uploads"))
    storage_mod.clear_cache()
    try:
        resp = await fclient.post(
            "/uploads",
            files={"file": ("sample.fasta", BytesIO(RAW_FASTA), "text/plain")},
            headers=_auth(researcher_token),
        )
    finally:
        storage_mod.clear_cache()
    assert resp.status_code == 201
    upload_id = resp.json()["upload_id"]
    events = await load_chain(fake_db, chain_id_for_upload(upload_id))
    assert [e["event_type"] for e in events] == ["upload_created"]
    payload = events[0]["payload"]
    assert payload["checksum_sha256"] == hashlib.sha256(RAW_FASTA).hexdigest()
    assert payload["derived"] is False
    assert events[0]["actor"] == {"type": "user", "user_id": OWNER, "role": "researcher"}


async def test_review_decision_appends_review_event(fclient, fake_db, curator_token):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    await fake_db["uploads"].insert_one(_upload_doc())
    await fake_db["reviews"].insert_one({
        "review_id": "rev_cust_001", "analysis_id": "ana_cust_001", "sequence_id": "seq_001",
        "submitted_by": OWNER, "state": "triaged", "correction_type": "species_correction",
    })
    resp = await fclient.post(
        "/reviews/rev_cust_001/decision", json={"decision": "accept", "notes": "matches voucher"},
        headers=_auth(curator_token),
    )
    assert resp.status_code == 200, resp.text
    events = await load_chain(fake_db, chain_id_for_upload("upl_cust_001"))
    decision = [e for e in events if e["event_type"] == "review_decision"]
    assert len(decision) == 1
    assert decision[0]["subject"]["review_id"] == "rev_cust_001"
    assert decision[0]["payload"]["decision"] == "accept"
    assert decision[0]["actor"]["user_id"] == "usr_curator_001"
    assert verify_chain(events)["valid"] is True


# ---------------------------------------------------------------------------
# GET /reports/{id}/custody
# ---------------------------------------------------------------------------

async def test_custody_requires_auth(fclient):
    assert (await fclient.get("/reports/ana_cust_001/custody")).status_code == 401


async def test_custody_not_found(fclient, researcher_token):
    resp = await fclient.get("/reports/ana_missing/custody", headers=_auth(researcher_token))
    assert resp.status_code == 404


async def test_custody_forbidden_for_other_researcher(fclient, fake_db, other_researcher_token):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    resp = await fclient.get("/reports/ana_cust_001/custody", headers=_auth(other_researcher_token))
    assert resp.status_code == 403
    assert _custody_docs(fake_db) == []  # nothing appended for a refused caller


async def test_custody_returns_verified_chain_and_is_idempotent(fclient, fake_db, researcher_token, local_storage):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    await fake_db["uploads"].insert_one(_upload_doc(storage_uri=local_storage.uri, checksum=local_storage.sha256))

    first = (await fclient.get("/reports/ana_cust_001/custody", headers=_auth(researcher_token))).json()
    second = (await fclient.get("/reports/ana_cust_001/custody", headers=_auth(researcher_token))).json()

    assert [e["event_type"] for e in first["events"]] == ["upload_created", "analysis_completed"]
    assert second["events"] == first["events"]  # derived events appended once
    assert first["verification"]["valid"] is True
    assert first["verification"]["length"] == 2
    assert first["results_integrity"]["status"] == "match"
    assert first["metadata_integrity"]["status"] == "unchanged"
    assert first["file_integrity"]["status"] == "verified"
    assert first["file_integrity"]["actual_sha256"] == hashlib.sha256(RAW_FASTA).hexdigest()


async def test_custody_reports_tampered_event(fclient, fake_db, researcher_token):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    await fake_db["uploads"].insert_one(_upload_doc())
    await fclient.get("/reports/ana_cust_001/custody?verify_file=false", headers=_auth(researcher_token))

    _custody_docs(fake_db)[1]["payload"]["result_count"] = 3  # edit the stored analysis_completed event
    data = (await fclient.get("/reports/ana_cust_001/custody?verify_file=false", headers=_auth(researcher_token))).json()
    assert data["verification"]["valid"] is False
    assert data["verification"]["first_break"]["seq"] == 1
    assert data["file_integrity"]["status"] == "not_checked"


async def test_custody_reports_results_changed_after_completion(fclient, fake_db, researcher_token):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    await fake_db["uploads"].insert_one(_upload_doc())
    await fclient.get("/reports/ana_cust_001/custody?verify_file=false", headers=_auth(researcher_token))

    fake_db["analysis_results"].docs[0]["results"][0]["predicted_taxon"] = "Edited after the fact"
    data = (await fclient.get("/reports/ana_cust_001/custody?verify_file=false", headers=_auth(researcher_token))).json()
    assert data["verification"]["valid"] is True  # the chain itself is intact
    assert data["results_integrity"]["status"] == "mismatch"


async def test_custody_reports_altered_stored_file(fclient, fake_db, researcher_token, local_storage, tmp_path):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    await fake_db["uploads"].insert_one(_upload_doc(storage_uri=local_storage.uri, checksum=local_storage.sha256))
    (tmp_path / "uploads" / local_storage.key).write_bytes(RAW_FASTA + b">seq_003\nAAAA\n")
    data = (await fclient.get("/reports/ana_cust_001/custody", headers=_auth(researcher_token))).json()
    assert data["file_integrity"]["status"] == "mismatch"


# ---------------------------------------------------------------------------
# GET /reports/{id}/export/fair
# ---------------------------------------------------------------------------

def test_term_map_covers_every_optional_metadata_field():
    assert set(fair.TERM_MAP) == set(OPTIONAL_METADATA_FIELDS)


async def test_fair_export_requires_auth(fclient):
    assert (await fclient.get("/reports/ana_cust_001/export/fair")).status_code == 401


async def test_fair_export_forbidden_for_other_researcher(fclient, fake_db, other_researcher_token):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    resp = await fclient.get("/reports/ana_cust_001/export/fair", headers=_auth(other_researcher_token))
    assert resp.status_code == 403


def _read_zip(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return {name.split("/", 1)[1]: zf.read(name) for name in zf.namelist()}


async def test_fair_zip_contents_and_manifest_hashes(fclient, fake_db, researcher_token, local_storage, data_root):
    decision = {
        "final_route": "fish", "result_class": "known_species", "predicted_taxon": "Sardinella longiceps",
        "taxon_rank": "species", "percent_identity": 99.4, "reference_db": "synthveda-ref",
        "reference_db_version": "v2", "confidence": 0.93, "rule": "blast_agrees_with_classifier",
    }
    trace = {"orchestrator_version": "orch-1", "plan": {"route": "fish"},
             "evidence": [{"provider": "blast", "reference_db": "synthveda-ref", "reference_db_version": "v2"}],
             "combine": []}
    results = [_result("seq_001", decision=decision, decision_trace=trace), _result("seq_002")]
    await fake_db["analysis_results"].insert_one(_analysis_doc(results))
    await fake_db["uploads"].insert_one(_upload_doc(
        storage_uri=local_storage.uri, checksum=local_storage.sha256,
        collected_at=datetime(2026, 8, 12, 6, 0), latitude=15.5, longitude=73.8, ph=8.1,
    ))

    resp = await fclient.get("/reports/ana_cust_001/export/fair", headers=_auth(researcher_token))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    files = _read_zip(resp.content)

    raw_name = "raw/stn14_sample.fasta"
    assert set(files) == {
        "README.md", "results.csv", "sample_metadata.json", "provenance.json", "decision_traces.json",
        "custody.json", raw_name, "manifest.json", "manifest-sha256.txt",
    }
    assert files[raw_name] == RAW_FASTA

    # Every listed file's sha256 and size match the bytes in the ZIP.
    manifest = json.loads(files["manifest.json"])
    listed = {f["path"]: f for f in manifest["files"]}
    assert set(listed) == set(files) - {"manifest.json", "manifest-sha256.txt"}
    for path, entry in listed.items():
        assert entry["sha256"] == hashlib.sha256(files[path]).hexdigest(), path
        assert entry["bytes"] == len(files[path])
    sums = dict(line.split("  ", 1)[::-1] for line in files["manifest-sha256.txt"].decode().splitlines())
    assert sums == {p: e["sha256"] for p, e in listed.items()}
    assert resp.headers["x-manifest-sha256"] == hashlib.sha256(files["manifest.json"]).hexdigest()

    rows = list(csv.DictReader(io.StringIO(files["results.csv"].decode())))
    assert [r["sequence_id"] for r in rows] == ["seq_001", "seq_002"]
    assert rows[0]["decision_rule"] == "blast_agrees_with_classifier"
    assert rows[1]["decision_rule"] == ""  # not recorded, not invented
    assert rows[0]["router_version"] == "router-v2"

    meta = json.loads(files["sample_metadata.json"])
    assert meta["darwin_core"]["dwc:eventDate"] == "2026-08-12T06:00:00"
    assert meta["darwin_core"]["dwc:decimalLatitude"] == 15.5
    assert meta["mixs"]["lat_lon"] == "15.5 73.8"
    assert meta["fields"]["collector"]["status"] == "missing"
    assert "collector" in meta["missing_fields"]
    assert set(meta["unmapped_fields"]) == {"methodology", "negative_control_included"}

    prov = json.loads(files["provenance.json"])
    assert prov["router"]["versions"] == {"router-v2": 2}
    assert prov["orchestrator"]["present"] is True and prov["orchestrator"]["sequences_with_decision"] == 1
    assert prov["reference_db"]["used"] == [
        {"reference_db": "synthveda-ref", "reference_db_version": "v2", "sequence_count": 1}]
    assert prov["reference_db"]["manifests"]["v2"]["licences"]["unite"] == "CC BY-SA 4.0"

    traces = json.loads(files["decision_traces.json"])
    assert [t["sequence_id"] for t in traces] == ["seq_001"]

    readme = files["README.md"].decode()
    assert "unite: CC BY-SA 4.0" in readme and "Collector" in readme

    # The export is the newest custody event, carrying the manifest hash; the
    # custody.json inside the ZIP is the chain as it stood just before it.
    custody_in_zip = json.loads(files["custody.json"])
    events = await load_chain(fake_db, chain_id_for_upload("upl_cust_001"))
    assert [e["event_type"] for e in events] == ["upload_created", "analysis_completed", "report_exported"]
    exported = events[-1]["payload"]
    assert exported["format"] == "fair_zip"
    assert exported["manifest_sha256"] == resp.headers["x-manifest-sha256"]
    assert exported["sha256"] == hashlib.sha256(resp.content).hexdigest()
    assert exported["custody_head_hash_in_zip"] == custody_in_zip["verification"]["head_hash"] == events[1]["hash"]
    assert verify_chain(events)["valid"] is True


async def test_fair_zip_without_orchestrator_or_raw_file_says_so(fclient, fake_db, researcher_token, data_root):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    await fake_db["uploads"].insert_one(_upload_doc(storage_uri="local://uploads/upl_cust_001/gone.fasta",
                                                    checksum="0" * 64))
    resp = await fclient.get("/reports/ana_cust_001/export/fair", headers=_auth(researcher_token))
    assert resp.status_code == 200
    files = _read_zip(resp.content)
    assert "decision_traces.json" not in files
    assert not any(p.startswith("raw/") for p in files)
    assert "decision_rule" not in files["results.csv"].decode().splitlines()[0]
    prov = json.loads(files["provenance.json"])
    assert prov["orchestrator"]["present"] is False
    assert prov["reference_db"]["used"] == [] and prov["reference_db"]["manifests"] == {}
    readme = files["README.md"].decode()
    assert "The uploaded file is not included" in readme
    assert "No orchestrator decision" in readme


async def test_fair_export_refused_when_custody_cannot_be_recorded(fclient, fake_db, researcher_token, data_root):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    fake_db[CUSTODY_COLLECTION].fail_inserts = True
    resp = await fclient.get("/reports/ana_cust_001/export/fair", headers=_auth(researcher_token))
    assert resp.status_code == 503


async def test_csv_export_is_recorded_on_custody_chain(fclient, fake_db, researcher_token):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    resp = await fclient.get("/reports/ana_cust_001/export/csv", headers=_auth(researcher_token))
    assert resp.status_code == 200
    events = await load_chain(fake_db, chain_id_for_upload("upl_cust_001"))
    assert events[-1]["event_type"] == "report_exported"
    assert events[-1]["payload"]["format"] == "csv"
    assert events[-1]["payload"]["sha256"] == hashlib.sha256(resp.content).hexdigest()


# ---------------------------------------------------------------------------
# Review findings (round 1): raw-file access policy, review text on the chain
# ---------------------------------------------------------------------------

async def _store_owner_sample_with_file(fake_db, local_storage):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    await fake_db["uploads"].insert_one(_upload_doc(storage_uri=local_storage.uri, checksum=local_storage.sha256))


async def test_fair_export_omits_raw_file_for_a_curator(fclient, fake_db, curator_token, local_storage, data_root):
    """A curator may read the report but not the upload (uploads/access.py), so not its bytes either."""
    await _store_owner_sample_with_file(fake_db, local_storage)
    assert (await fclient.get("/uploads/upl_cust_001", headers=_auth(curator_token))).status_code == 403

    resp = await fclient.get("/reports/ana_cust_001/export/fair", headers=_auth(curator_token))
    assert resp.status_code == 200, resp.text
    files = _read_zip(resp.content)
    assert not any(p.startswith("raw/") for p in files)
    assert RAW_FASTA not in resp.content
    readme = files["README.md"].decode()
    assert "The uploaded file is not included" in readme and "upload access policy" in readme
    events = await load_chain(fake_db, chain_id_for_upload("upl_cust_001"))
    assert events[-1]["payload"]["raw_file_included"] is False


async def test_fair_export_includes_raw_file_for_an_admin(fclient, fake_db, admin_token, local_storage, data_root):
    await _store_owner_sample_with_file(fake_db, local_storage)
    resp = await fclient.get("/reports/ana_cust_001/export/fair", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert _read_zip(resp.content)["raw/stn14_sample.fasta"] == RAW_FASTA


async def test_review_by_a_user_without_access_appends_nothing_to_the_chain(
    fclient, fake_db, other_researcher_token,
):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    await fake_db["uploads"].insert_one(_upload_doc())
    resp = await fclient.post("/reviews", json={
        "analysis_id": "ana_cust_001", "sequence_id": "seq_001", "correction_type": "species_correction",
        "proposed_taxon": "Jane Doe, +1-555-0100, jane@example.com",
    }, headers=_auth(other_researcher_token))
    assert resp.status_code == 201  # POST /reviews' own access rule is unchanged (open issue)
    # Not a review event, and not the first observation that derives analysis_completed either.
    assert _custody_docs(fake_db) == []


async def test_review_submitted_event_hashes_free_text(fclient, fake_db, researcher_token):
    await fake_db["analysis_results"].insert_one(_analysis_doc())
    await fake_db["uploads"].insert_one(_upload_doc())
    text = "Jane Doe, +1-555-0100, jane@example.com"
    resp = await fclient.post("/reviews", json={
        "analysis_id": "ana_cust_001", "sequence_id": "seq_001", "correction_type": "species_correction",
        "proposed_taxon": text,
    }, headers=_auth(researcher_token))
    assert resp.status_code == 201, resp.text
    events = await load_chain(fake_db, chain_id_for_upload("upl_cust_001"))
    submitted = [e for e in events if e["event_type"] == "review_submitted"]
    assert len(submitted) == 1
    payload = submitted[0]["payload"]
    assert payload["review_id"] == resp.json()["review_id"]
    assert payload["proposed_taxon_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert payload["correction_type_sha256"] == hashlib.sha256(b"species_correction").hexdigest()
    assert payload["sequence_id_sha256"] == hashlib.sha256(b"seq_001").hexdigest()
    assert "Jane Doe" not in json.dumps(events, default=str)
    assert "species_correction" not in json.dumps(submitted, default=str)
    assert verify_chain(events)["valid"] is True
