"""
B9: review_evidence, curation_decisions and training_batch_items are written
(app/reviews/records.py) -- MongoDB first-class, Supabase as a best-effort
mirror whose rows must fit the tables the migrations create.

Supabase is faked at the postgrest-chain level (`_client.table(...)...execute()`)
so the real SupabaseClient methods run; every row it receives is checked
against the column list, not-null columns and enum/check values parsed from
supabase/migrations/*.sql.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import app.db.supabase_client as sc_module
import importlib

reviews_router = importlib.import_module("app.reviews.router")  # the package re-exports `router`

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"


# ---------------------------------------------------------------------------
# Schema, parsed from the migrations
# ---------------------------------------------------------------------------

def _schema() -> dict[str, dict]:
    sql = "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))
    tables: dict[str, dict] = {}
    for name, body in re.findall(r"create table if not exists (\w+) \((.*?)\n\);", sql, re.S):
        cols, required = set(), set()
        for line in body.splitlines():
            line = line.split("--")[0].strip().rstrip(",")
            if not line or line.split()[0] in ("unique", "primary", "constraint"):
                continue
            col = line.split()[0]
            cols.add(col)
            if "not null" in line and "default" not in line and "primary key" not in line:
                required.add(col)
        tables[name] = {"cols": cols, "required": required}
    for name, col in re.findall(r"alter table (\w+)\s+add column if not exists (\w+)", sql):
        tables[name]["cols"].add(col)
    for name, col in re.findall(r"alter table (\w+) alter column (\w+) drop not null", sql):
        tables[name]["required"].discard(col)
    return tables


SCHEMA = _schema()
_SQL = "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))
REVIEW_DECISIONS = set(re.findall(r"'(\w+)'", re.search(
    r"create type review_decision as enum \((.*?)\);", _SQL, re.S).group(1)))
EVIDENCE_TYPES = set(re.findall(r"'(\w+)'", re.findall(
    r"review_evidence_evidence_type_check\s+check \(evidence_type in \((.*?)\)\)", _SQL)[-1]))
CURATED_SOURCES = {"expert_correction", "reference_db", "manual_curation"}


def _assert_fits(table: str, row: dict) -> None:
    spec = SCHEMA[table]
    assert set(row) <= spec["cols"], f"{table}: unknown columns {set(row) - spec['cols']}"
    missing = {c for c in spec["required"] if row.get(c) is None}
    assert not missing, f"{table}: not-null columns missing {missing}"
    json.dumps(row, allow_nan=False)  # jsonb / PostgREST body must be strict JSON


# ---------------------------------------------------------------------------
# Fake Supabase (postgrest chain)
# ---------------------------------------------------------------------------

class _Query:
    def __init__(self, sb: "_FakeSupabase", table: str):
        self.sb, self.table, self.op, self.payload, self.filters = sb, table, "select", None, []

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.op, self.payload, self.on_conflict = "upsert", payload, on_conflict
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    async def execute(self):
        if self.table in self.sb.fail_tables:
            raise httpx.ConnectError("[Errno -2] Name or service not known")
        rows = self.sb.rows.setdefault(self.table, [])
        match = lambda r: all(r.get(c) == v for c, v in self.filters)  # noqa: E731
        if self.op == "select":
            return SimpleNamespace(data=[r for r in rows if match(r)])
        if self.op == "update":
            self.sb.updates.append((self.table, self.payload, list(self.filters)))
            return SimpleNamespace(data=[])
        payloads = self.payload if isinstance(self.payload, list) else [self.payload]
        out = []
        for p in payloads:
            _assert_fits(self.table, p)
            if self.op == "upsert":
                key = self.on_conflict
                existing = next((r for r in rows if r.get(key) == p[key]), None)
                if existing is not None:
                    existing.update(p)
                    out.append(existing)
                    continue
            row = {"id": str(uuid.uuid4()), **p}
            rows.append(row)
            out.append(row)
        return SimpleNamespace(data=out)


class _FakeSupabase:
    def __init__(self, fail_tables=()):
        self.rows: dict[str, list[dict]] = {}
        self.updates: list = []
        self.fail_tables = set(fail_tables)

    def table(self, name):
        return _Query(self, name)


@pytest.fixture
def supabase(monkeypatch):
    fake = _FakeSupabase()
    monkeypatch.setattr(sc_module, "_client", fake)

    async def _no_sleep(_):
        return None
    monkeypatch.setattr(sc_module.asyncio, "sleep", _no_sleep)  # _with_retry backoff
    return fake


# ---------------------------------------------------------------------------
# Fake MongoDB
# ---------------------------------------------------------------------------

def _matches(doc: dict, query: dict) -> bool:
    for k, v in query.items():
        if k == "$or":
            if not any(_matches(doc, q) for q in v):
                return False
        elif isinstance(v, dict) and "$regex" in v:
            if not re.search(v["$regex"], doc.get(k) or "", re.I if "i" in v.get("$options", "") else 0):
                return False
        elif isinstance(v, dict) and "$in" in v:
            if doc.get(k) not in v["$in"]:
                return False
        elif doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._docs:
            return self._docs.pop(0)
        raise StopAsyncIteration


class _Coll:
    def __init__(self):
        self.docs: list[dict] = []

    async def find_one(self, query, projection=None):
        doc = next((d for d in self.docs if _matches(d, query)), None)
        if doc is None:
            return None
        elem = (projection or {}).get("results", {})
        if isinstance(elem, dict) and "$elemMatch" in elem:
            want = elem["$elemMatch"]
            hit = [r for r in doc.get("results", []) if _matches(r, want)][:1]
            return {"analysis_id": doc.get("analysis_id"), **({"results": hit} if hit else {})}
        return dict(doc)

    def find(self, query=None, projection=None):
        return _Cursor([dict(d) for d in self.docs if _matches(d, query or {})])

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=len(self.docs))

    async def insert_many(self, docs):
        self.docs.extend(dict(d) for d in docs)

    async def update_one(self, query, update):
        for d in self.docs:
            if _matches(d, query):
                d.update(update.get("$set", {}))
                for k, v in update.get("$push", {}).items():
                    d.setdefault(k, []).extend(v["$each"])
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    async def update_many(self, query, update):
        for d in self.docs:
            if _matches(d, query):
                d.update(update.get("$set", {}))


class _Db:
    def __init__(self):
        self.colls: dict[str, _Coll] = {}

    def __getitem__(self, name):
        return self.colls.setdefault(name, _Coll())


@pytest.fixture
def db(monkeypatch):
    fake = _Db()
    monkeypatch.setattr(reviews_router, "get_db", lambda: fake)
    return fake


ANALYSIS = {
    "analysis_id": "ana_b9",
    "user_id": "usr_test_001",
    "results": [
        {
            "sequence_id": "seq_1",
            "sequence": "ACGT" * 40,
            "sha256": "abc",
            "length": 160,
            "embedding": [0.1] * 768,
            "route": "fish",
            "result_class": "known_species",
            "predicted_taxon": "Gadus morhua",
            "confidence": 0.91,
            "novelty_score": 0.12,
            # task A's orchestrator contract (read-only here)
            "decision": {"final_route": "fish", "result_class": "known_species",
                         "predicted_taxon": "Gadus morhua", "rule": "head_confident"},
            "decision_trace": {"orchestrator_version": "1", "plan": {}, "evidence": [], "combine": []},
        },
        {"sequence_id": "seq_2", "sequence": "TTGA" * 40, "route": "fish",
         "result_class": "possible_novelty", "novelty_score": 0.8},
    ],
}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _submit(client, token, **overrides):
    body = {"analysis_id": "ana_b9", "sequence_id": "seq_1", "correction_type": "species_correction",
            "proposed_taxon": "Gadus macrocephalus", "evidence_notes": "COI 99.4% to MN123456"}
    body.update(overrides)
    r = await client.post("/reviews", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# review_evidence
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_submit_writes_snapshot_and_notes_evidence(client, researcher_token, db, supabase):
    db["analysis_results"].docs.append(ANALYSIS)
    review = await _submit(client, researcher_token)

    ev = db["review_evidence"].docs
    assert sorted(d["evidence_type"] for d in ev) == ["result_snapshot", "text"]
    assert all(d["review_id"] == review["review_id"] and d["supabase_mirrored"] for d in ev)
    snap = next(d for d in ev if d["evidence_type"] == "result_snapshot")["payload"]
    assert snap["result"]["decision"]["rule"] == "head_confident"
    assert snap["result"]["decision_trace"]["orchestrator_version"] == "1"
    assert "embedding" not in snap["result"] and "sequence" not in snap["result"]
    assert snap["result"]["sha256"] == "abc"

    [er] = supabase.rows["expert_reviews"]
    assert er["review_id"] == review["review_id"] and er["submitted_by"] == "usr_test_001"
    rows = supabase.rows["review_evidence"]
    assert len(rows) == 2
    assert {r["review_id"] for r in rows} == {er["id"]}
    assert {r["evidence_type"] for r in rows} <= EVIDENCE_TYPES
    text = next(r for r in rows if r["evidence_type"] == "text")
    assert text["content"] == "COI 99.4% to MN123456" and text["payload"] is None
    snap_row = next(r for r in rows if r["evidence_type"] == "result_snapshot")
    assert snap_row["payload"]["result"]["decision"]["final_route"] == "fish"
    assert isinstance(snap_row["payload"]["captured_at"], str)


@pytest.mark.anyio
async def test_snapshot_with_nan_mirrors_as_null_and_mongo_keeps_it(client, researcher_token, db, supabase):
    analysis = json.loads(json.dumps(ANALYSIS))
    analysis["results"][0]["decision"]["percent_identity"] = float("nan")
    db["analysis_results"].docs.append(analysis)
    await _submit(client, researcher_token)
    snap = next(d for d in db["review_evidence"].docs if d["evidence_type"] == "result_snapshot")
    assert snap["supabase_mirrored"]
    assert snap["payload"]["result"]["decision"]["percent_identity"] != snap["payload"]["result"]["decision"]["percent_identity"]  # NaN
    row = next(r for r in supabase.rows["review_evidence"] if r["evidence_type"] == "result_snapshot")
    assert row["payload"]["result"]["decision"]["percent_identity"] is None


@pytest.mark.anyio
async def test_submit_without_analysis_or_notes_still_mirrors_review(client, researcher_token, db, supabase):
    await _submit(client, researcher_token, analysis_id="ana_missing", evidence_notes=None)
    assert db["review_evidence"].docs == []
    assert len(supabase.rows["expert_reviews"]) == 1
    assert "review_evidence" not in supabase.rows


@pytest.mark.anyio
async def test_submit_with_supabase_unconfigured_keeps_mongo_records(client, researcher_token, db, monkeypatch):
    monkeypatch.setattr(sc_module, "_client", None)
    db["analysis_results"].docs.append(ANALYSIS)
    await _submit(client, researcher_token)
    ev = db["review_evidence"].docs
    assert len(ev) == 2 and not any(d["supabase_mirrored"] for d in ev)


@pytest.mark.anyio
async def test_submit_with_supabase_unreachable_is_logged_not_fatal(
    client, researcher_token, db, supabase, caplog
):
    supabase.fail_tables = {"expert_reviews", "review_evidence"}
    db["analysis_results"].docs.append(ANALYSIS)
    with caplog.at_level(logging.WARNING, logger="app.reviews.records"):
        await _submit(client, researcher_token)
    ev = db["review_evidence"].docs
    assert len(ev) == 2 and not any(d["supabase_mirrored"] for d in ev)
    [rec] = [r for r in caplog.records if "Supabase mirror of review_evidence" in r.getMessage()]
    assert rec.exc_info is not None  # traceback kept, not silent


@pytest.mark.anyio
async def test_add_evidence_classifies_attachments(client, researcher_token, db, supabase):
    review = await _submit(client, researcher_token, analysis_id="ana_missing", evidence_notes=None)
    r = await client.post(
        f"/reviews/{review['review_id']}/evidence",
        json={"evidence_text": "voucher photo attached",
              "evidence_attachments": ["https://www.ncbi.nlm.nih.gov/nuccore/MN123456", "BOLD:AAA1234"]},
        headers=_auth(researcher_token),
    )
    assert r.status_code == 200, r.text
    types = {d["evidence_type"]: d["content"] for d in db["review_evidence"].docs}
    assert types == {"text": "voucher photo attached",
                     "url": "https://www.ncbi.nlm.nih.gov/nuccore/MN123456",
                     "reference": "BOLD:AAA1234"}
    assert len(supabase.rows["review_evidence"]) == 3


# ---------------------------------------------------------------------------
# curation_decisions
# ---------------------------------------------------------------------------

def _auto_review(**overrides):
    doc = {"review_id": "rev_auto1", "analysis_id": "ana_b9", "sequence_id": "seq_2",
           "submitted_by": "system", "state": "submitted", "review_type": "auto_novelty",
           "triage_priority": "urgent", "correction_type": "auto_novelty_flag",
           "is_novelty": True, "evidence_attachments": [], "training_batch_id": None}
    doc.update(overrides)
    return doc


@pytest.mark.anyio
async def test_decision_on_auto_review_writes_decision_and_snapshot(client, curator_token, db, supabase):
    db["analysis_results"].docs.append(ANALYSIS)
    db["reviews"].docs.append(_auto_review())

    r = await client.post("/reviews/rev_auto1/decision", json={"decision": "needs_evidence", "notes": "need COI"},
                          headers=_auth(curator_token))
    assert r.status_code == 200, r.text
    assert r.json()["supabase_mirror"] == "written"
    r = await client.post("/reviews/rev_auto1/decision", json={"decision": "accept"},
                          headers=_auth(curator_token))
    assert r.json()["new_state"] == "accepted"

    decisions = db["curation_decisions"].docs
    assert [(d["decision"], d["previous_state"], d["new_state"]) for d in decisions] == [
        ("needs_evidence", "submitted", "needs_evidence"), ("accept", "needs_evidence", "accepted")]
    assert all(d["curator_id"] == "usr_curator_001" and d["supabase_mirrored"] for d in decisions)

    # Snapshot captured once, by the curator, at the first decision.
    [snap] = db["review_evidence"].docs
    assert snap["evidence_type"] == "result_snapshot" and snap["submitted_by"] == "usr_curator_001"
    assert snap["payload"]["result"]["sequence_id"] == "seq_2"

    [er] = supabase.rows["expert_reviews"]
    assert er["submitted_by"] is None  # "system" has no user_profiles row
    assert er["state"] == "accepted" and er["decided_by"] == "usr_curator_001"
    rows = supabase.rows["curation_decisions"]
    assert [x["decision"] for x in rows] == ["needs_evidence", "accept"]
    assert {x["decision"] for x in rows} <= REVIEW_DECISIONS
    assert {x["review_id"] for x in rows} == {er["id"]}
    assert rows[0]["notes"] == "need COI"


@pytest.mark.anyio
async def test_decision_with_supabase_unreachable_is_logged_not_fatal(
    client, curator_token, db, supabase, caplog
):
    supabase.fail_tables = {"expert_reviews"}
    db["reviews"].docs.append(_auto_review())
    with caplog.at_level(logging.WARNING, logger="app.reviews.records"):
        r = await client.post("/reviews/rev_auto1/decision", json={"decision": "reject"},
                              headers=_auth(curator_token))
    assert r.status_code == 200, r.text
    assert r.json()["supabase_mirror"] == "failed"
    [d] = db["curation_decisions"].docs
    assert d["decision"] == "reject" and d["supabase_mirrored"] is False
    assert db["reviews"].docs[0]["state"] == "rejected"
    assert any("Supabase mirror of curation decision on rev_auto1" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# training_batch_items
# ---------------------------------------------------------------------------

def _accepted(review_id, sequence_id, **overrides):
    doc = {"review_id": review_id, "analysis_id": "ana_b9", "sequence_id": sequence_id,
           "submitted_by": "usr_test_001", "state": "accepted", "review_type": "manual_correction",
           "correction_type": "fish_species_correction", "decided_by": "usr_curator_001",
           "training_batch_id": None}
    doc.update(overrides)
    return doc


@pytest.mark.anyio
async def test_batch_writes_items_and_schema_valid_curated_sequences(client, admin_token, db, supabase):
    db["analysis_results"].docs.append(ANALYSIS)
    db["reviews"].docs += [
        _accepted("rev_a", "seq_1", proposed_taxon="Gadus macrocephalus"),
        _accepted("rev_b", "seq_2"),  # no proposed_taxon: curated_sequences.taxon is not null
    ]
    r = await client.post("/reviews/batch/create", json={"route": "fish", "month_year": "2026-10"},
                          headers=_auth(admin_token))
    body = r.json()
    assert r.status_code == 200, r.text
    assert (body["status"], body["sequence_count"]) == ("assembled", 2)
    assert (body["supabase_items_mirrored"], body["supabase_items_skipped"]) == (1, 1)

    items = {d["review_id"]: d for d in db["training_batch_items"].docs}
    assert set(items) == {"rev_a", "rev_b"}
    assert all(d["batch_id"] == body["batch_id"] and d["split"] is None for d in items.values())
    assert items["rev_a"]["supabase_mirrored"] and items["rev_a"]["supabase_skip_reason"] is None
    assert not items["rev_b"]["supabase_mirrored"]
    assert items["rev_b"]["supabase_skip_reason"] == "review has no proposed_taxon"

    [batch] = supabase.rows["training_batches"]
    [cs] = supabase.rows["curated_sequences"]
    assert cs["sequence"] == "ACGT" * 40 and cs["taxon"] == "Gadus macrocephalus"
    assert cs["source"] in CURATED_SOURCES and cs["source"] == "expert_correction"
    assert cs["training_batch_id"] == batch["id"] and cs["curated_by"] == "usr_curator_001"
    [item] = supabase.rows["training_batch_items"]
    assert item == {"id": item["id"], "batch_id": batch["id"], "curated_sequence_id": cs["id"], "split": None}
    assert ("training_batches", {"sequence_count": 1}, [("batch_id", body["batch_id"])]) in supabase.updates
    # Every review is stamped regardless of the mirror.
    assert {d["state"] for d in db["reviews"].docs} == {"included_in_training_batch"}


@pytest.mark.anyio
async def test_batch_mirror_failure_midway_keeps_accurate_flags(client, admin_token, db, supabase, caplog):
    supabase.fail_tables = {"training_batch_items"}
    db["analysis_results"].docs.append(ANALYSIS)
    db["reviews"].docs.append(_accepted("rev_a", "seq_1", proposed_taxon="Gadus macrocephalus"))
    with caplog.at_level(logging.WARNING, logger="app.reviews.records"):
        r = await client.post("/reviews/batch/create", json={"route": "fish", "month_year": "2026-10"},
                              headers=_auth(admin_token))
    body = r.json()
    assert (body["status"], body["supabase_mirror"], body["supabase_items_mirrored"]) == (
        "assembled_local_only", "failed", 0)
    [item] = db["training_batch_items"].docs
    assert item["supabase_mirrored"] is False
    assert any("Supabase mirror of training batch" in r.getMessage() for r in caplog.records)


@pytest.mark.anyio
async def test_mongo_records_exist_before_supabase_is_called(client, researcher_token, curator_token,
                                                             admin_token, db, supabase, monkeypatch):
    """MongoDB is written first, so a Supabase call that hangs or dies cannot cost the record."""
    seen: dict[str, int] = {}

    def spy(name, coll):
        real = getattr(sc_module.SupabaseClient, name)

        async def wrapped(*a, **kw):
            seen[name] = len(db[coll].docs)
            return await real(*a, **kw)
        monkeypatch.setattr(sc_module.SupabaseClient, name, staticmethod(wrapped))

    spy("insert_review_evidence", "review_evidence")
    spy("insert_curation_decision", "curation_decisions")
    spy("get_or_create_training_batch", "training_batch_items")
    db["analysis_results"].docs.append(ANALYSIS)

    review = await _submit(client, researcher_token, correction_type="fish_species_correction")
    r = await client.post(f"/reviews/{review['review_id']}/decision", json={"decision": "accept"},
                          headers=_auth(curator_token))
    assert r.status_code == 200, r.text
    r = await client.post("/reviews/batch/create", json={"route": "fish", "month_year": "2026-10"},
                          headers=_auth(admin_token))
    assert r.json()["status"] == "assembled", r.text

    assert seen == {"insert_review_evidence": 2, "insert_curation_decision": 1,
                    "get_or_create_training_batch": 1}
    # ...and flipped to mirrored once Supabase accepted the rows.
    assert all(d["supabase_mirrored"] for c in ("review_evidence", "curation_decisions", "training_batch_items")
               for d in db[c].docs)


@pytest.mark.anyio
async def test_unconfigured_supabase_still_records_skip_reasons(client, admin_token, db, monkeypatch):
    monkeypatch.setattr(sc_module, "_client", None)
    db["reviews"].docs.append(_accepted("rev_x", "seq_missing", proposed_taxon="Gadus morhua"))
    r = await client.post("/reviews/batch/create", json={"route": "fish", "month_year": "2026-10"},
                          headers=_auth(admin_token))
    body = r.json()
    assert (body["status"], body["supabase_mirror"], body["supabase_items_skipped"]) == (
        "assembled_local_only", "not_configured", 1)
    [item] = db["training_batch_items"].docs
    assert item["supabase_skip_reason"] == "sequence not found in analysis_results"
    assert item["supabase_mirrored"] is False


# ---------------------------------------------------------------------------
# B9 audit: no migration table is left unread/unwritten by the API
# ---------------------------------------------------------------------------

def test_every_migration_table_is_read_or_written_by_the_api():
    """
    Every table the migrations create is touched by a SupabaseClient method
    that some API module outside db/ actually calls -- not merely present in
    the client.
    """
    app_dir = Path(sc_module.__file__).resolve().parents[1]
    src = Path(sc_module.__file__).read_text()
    callers = "\n".join(p.read_text() for p in app_dir.rglob("*.py") if p.parent.name != "db")
    methods = re.split(r"\n    @staticmethod\n", src)
    used: set[str] = set()
    for body in methods:
        m = re.match(r"\s*async def (\w+)", body)
        if m and re.search(rf"\.{m.group(1)}\(", callers):
            used |= set(re.findall(r'table\("(\w+)"\)', body))
    assert set(SCHEMA) - used == set()
