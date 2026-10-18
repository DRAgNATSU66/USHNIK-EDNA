"""
B10: Field Log edits with an append-only history, and attachments stored
through app/storage.py (local backend and S3 via moto).

The conftest mock DB returns None for every find_one, which can't exercise
an edit; these tests patch in a small in-memory Mongo (_FakeDb) that
implements just the operators the router uses: equality filters (a None
filter value matches a missing field, as in Mongo), $set, $push, sort.
"""
from __future__ import annotations

import copy
import hashlib
from io import BytesIO
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

import app.db.mongo as _mongo_module
from app import storage
from app.auth.jwt import create_access_token
from app.config import get_settings
from app.models.user import UserRole

OWNER = "usr_test_001"  # researcher_token's user (conftest)
ANALYSIS = "ana_b10"
OTHER_ANALYSIS = "ana_someone_else"
BUCKET = "synthveda-test-uploads"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n%test\n" + b"0" * 100
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40


# ---------------------------------------------------------------------------
# In-memory Mongo
# ---------------------------------------------------------------------------

def _matches(doc: dict, flt: dict) -> bool:
    return all(doc.get(k) == v for k, v in flt.items())


class _Result:
    def __init__(self, matched: int):
        self.matched_count = matched
        self.modified_count = matched


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field, direction=1):
        self._docs.sort(key=lambda d: d.get(field), reverse=direction < 0)
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._docs:
            return copy.deepcopy(self._docs.pop(0))
        raise StopAsyncIteration


class _FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    async def find_one(self, flt):
        for d in self.docs:
            if _matches(d, flt):
                return copy.deepcopy(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(dict(doc)))

    async def update_one(self, flt, update):
        for d in self.docs:
            if _matches(d, flt):
                for k, v in update.get("$set", {}).items():
                    d[k] = copy.deepcopy(v)
                for k, v in update.get("$push", {}).items():
                    d.setdefault(k, []).append(copy.deepcopy(v))
                return _Result(1)
        return _Result(0)

    def find(self, flt):
        return _Cursor(d for d in self.docs if _matches(d, flt))


class _FakeDb:
    def __init__(self):
        self.collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _FakeCollection())


@pytest.fixture
def db():
    fake = _FakeDb()
    fake["analysis_results"].docs.extend([
        {"analysis_id": ANALYSIS, "user_id": OWNER},
        {"analysis_id": OTHER_ANALYSIS, "user_id": "usr_other"},
    ])
    with patch.object(_mongo_module, "_db", fake):
        yield fake


@pytest.fixture
def other_researcher_token():
    return create_access_token(
        "usr_other",
        {"email": "other@example.com", "role": UserRole.researcher, "name": "Other Researcher"},
    )


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _create(client, token, body="Rainfall runoff near sampling zone.", kind="note", analysis_id=ANALYSIS):
    resp = await client.post(
        "/field-log/entries",
        json={"analysis_id": analysis_id, "kind": kind, "body": body},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# PATCH + history
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_new_entry_has_empty_history(client, db, researcher_token):
    entry = await _create(client, researcher_token)
    assert entry["edits"] == []
    assert entry["updated_at"] is None


@pytest.mark.anyio
async def test_two_edits_are_recorded_in_order_with_old_and_new(client, db, researcher_token):
    entry = await _create(client, researcher_token, body="v1")
    eid = entry["entry_id"]

    r1 = await client.patch(f"/field-log/entries/{eid}", json={"body": "v2"}, headers=_auth(researcher_token))
    assert r1.status_code == 200, r1.text
    r2 = await client.patch(
        f"/field-log/entries/{eid}",
        json={"body": "  v3  ", "anchor_sequence_id": "seq_007"},
        headers=_auth(researcher_token),
    )
    assert r2.status_code == 200, r2.text

    got = (await client.get(f"/field-log/entries/{eid}", headers=_auth(researcher_token))).json()
    assert got["body"] == "v3"  # stripped, like POST
    assert got["anchor_sequence_id"] == "seq_007"
    assert got["updated_at"] is not None
    edits = got["edits"]
    assert len(edits) == 2
    assert edits[0]["changes"] == [{"field": "body", "old": "v1", "new": "v2"}]
    assert sorted(edits[1]["changes"], key=lambda c: c["field"]) == [
        {"field": "anchor_sequence_id", "old": None, "new": "seq_007"},
        {"field": "body", "old": "v2", "new": "v3"},
    ]
    for e in edits:
        assert e["editor_id"] == OWNER
        assert e["editor_name"] == "Test User"
        assert e["edit_id"].startswith("fle_edit_")
    assert edits[0]["edited_at"] <= edits[1]["edited_at"]
    # The PATCH response and GET agree, and the list route carries history too.
    assert r2.json()["edits"] == edits
    listed = (await client.get("/field-log/entries", params={"analysis_id": ANALYSIS},
                               headers=_auth(researcher_token))).json()
    assert listed[0]["edits"] == edits
    # Stored doc: original body is still recoverable from history alone.
    stored = db["field_log_entries"].docs[0]
    assert stored["edits"][0]["changes"][0]["old"] == "v1"


@pytest.mark.anyio
async def test_noop_patch_records_nothing(client, db, researcher_token):
    entry = await _create(client, researcher_token, body="same")
    r = await client.patch(f"/field-log/entries/{entry['entry_id']}", json={"body": "same "},
                           headers=_auth(researcher_token))
    assert r.status_code == 200
    assert r.json()["edits"] == []
    assert "edits" not in db["field_log_entries"].docs[0] or db["field_log_entries"].docs[0]["edits"] == []


@pytest.mark.anyio
async def test_patch_can_clear_anchor_with_null(client, db, researcher_token):
    entry = await _create(client, researcher_token, kind="comment")
    eid = entry["entry_id"]
    await client.patch(f"/field-log/entries/{eid}", json={"anchor_sequence_id": "seq_1"}, headers=_auth(researcher_token))
    r = await client.patch(f"/field-log/entries/{eid}", json={"anchor_sequence_id": None}, headers=_auth(researcher_token))
    assert r.status_code == 200
    assert r.json()["anchor_sequence_id"] is None
    assert r.json()["edits"][-1]["changes"] == [{"field": "anchor_sequence_id", "old": "seq_1", "new": None}]


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [{}, {"kind": "comment"}, {"body": "   "}, {"body": None}])
async def test_patch_rejects_empty_or_non_editable(client, db, researcher_token, payload):
    entry = await _create(client, researcher_token)
    r = await client.patch(f"/field-log/entries/{entry['entry_id']}", json=payload, headers=_auth(researcher_token))
    assert r.status_code == 422, r.text
    assert db["field_log_entries"].docs[0].get("edits", []) == []


@pytest.mark.anyio
async def test_patch_requires_auth(client, db):
    r = await client.patch("/field-log/entries/fle_x", json={"body": "x"})
    assert r.status_code == 401


@pytest.mark.anyio
async def test_patch_missing_entry_404(client, db, researcher_token):
    r = await client.patch("/field-log/entries/fle_nope", json={"body": "x"}, headers=_auth(researcher_token))
    assert r.status_code == 404
    r = await client.get("/field-log/entries/fle_nope", headers=_auth(researcher_token))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_no_access_to_analysis_is_403_for_get_and_patch(client, db, researcher_token, other_researcher_token):
    entry = await _create(client, other_researcher_token, analysis_id=OTHER_ANALYSIS)
    eid = entry["entry_id"]
    assert (await client.get(f"/field-log/entries/{eid}", headers=_auth(researcher_token))).status_code == 403
    r = await client.patch(f"/field-log/entries/{eid}", json={"body": "hijack"}, headers=_auth(researcher_token))
    assert r.status_code == 403
    assert db["field_log_entries"].docs[0]["body"] == "Rainfall runoff near sampling zone."


@pytest.mark.anyio
async def test_curator_can_edit_someone_elses_entry_and_is_recorded(client, db, researcher_token, curator_token):
    entry = await _create(client, researcher_token, body="typo in tihs note")
    r = await client.patch(f"/field-log/entries/{entry['entry_id']}", json={"body": "typo in this note"},
                           headers=_auth(curator_token))
    assert r.status_code == 200, r.text
    edit = r.json()["edits"][0]
    assert edit["editor_id"] == "usr_curator_001"
    assert edit["editor_name"] == "Curator User"
    assert r.json()["author_id"] == OWNER  # authorship unchanged


@pytest.mark.anyio
async def test_non_author_without_curator_role_cannot_edit(client, db, researcher_token, curator_token):
    # A curator posts on the researcher's analysis; the researcher owns the
    # analysis but didn't write that entry, so they can't rewrite it.
    entry = await _create(client, curator_token, body="curator note")
    r = await client.patch(f"/field-log/entries/{entry['entry_id']}", json={"body": "changed"},
                           headers=_auth(researcher_token))
    assert r.status_code == 403
    assert "author" in r.json()["detail"]


@pytest.mark.anyio
async def test_concurrent_edit_loses_with_409_and_history_stays_consistent(client, db, researcher_token):
    entry = await _create(client, researcher_token, body="v1")
    eid = entry["entry_id"]
    coll = db["field_log_entries"]
    real_find_one = coll.find_one

    async def stale_find_one(flt):
        # Simulate a second writer landing between our read and our update.
        doc = await real_find_one(flt)
        coll.docs[0]["body"] = "someone else's edit"
        return doc

    coll.find_one = stale_find_one
    r = await client.patch(f"/field-log/entries/{eid}", json={"body": "mine"}, headers=_auth(researcher_token))
    assert r.status_code == 409
    assert coll.docs[0]["body"] == "someone else's edit"
    assert coll.docs[0].get("edits", []) == []


@pytest.mark.anyio
async def test_pre_b10_entry_without_edits_field_loads_and_edits(client, db, researcher_token):
    db["field_log_entries"].docs.append({
        "entry_id": "fle_legacy", "analysis_id": ANALYSIS, "kind": "note",
        "author_id": OWNER, "author_name": "Test User", "body": "old",
        "anchor_sequence_id": None, "reply_to": None, "created_at": "2026-10-01T00:00:00",
    })
    got = (await client.get("/field-log/entries/fle_legacy", headers=_auth(researcher_token))).json()
    assert got["edits"] == [] and got["updated_at"] is None
    r = await client.patch("/field-log/entries/fle_legacy", json={"body": "new"}, headers=_auth(researcher_token))
    assert r.status_code == 200
    assert r.json()["edits"][0]["changes"] == [{"field": "body", "old": "old", "new": "new"}]


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

@pytest.fixture
def attach_storage(monkeypatch, tmp_path):
    settings = get_settings()
    for name, value in {
        "storage_backend": "local",
        "upload_storage_dir": str(tmp_path),
        "object_storage_url": "",
        "object_storage_bucket": BUCKET,
        "object_storage_access_key": "testing",
        "object_storage_secret_key": "testing",
        "object_storage_region": "us-east-1",
        "field_log_attachment_max_mb": 1,
    }.items():
        monkeypatch.setattr(settings, name, value)
    storage.clear_cache()
    yield settings
    storage.clear_cache()


@pytest.fixture
def s3(monkeypatch):
    for var, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(var, value)
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


async def _attach(client, token, data=PNG, name="site.png", ctype="image/png", analysis_id=ANALYSIS, entry_id=None):
    form = {"analysis_id": analysis_id}
    if entry_id:
        form["entry_id"] = entry_id
    return await client.post(
        "/field-log/attachments",
        data=form,
        files={"file": (name, BytesIO(data), ctype)},
        headers=_auth(token),
    )


@pytest.mark.anyio
async def test_attachment_local_round_trip(client, db, researcher_token, attach_storage, tmp_path):
    r = await _attach(client, researcher_token)
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["content_type"] == "image/png"
    assert meta["size_bytes"] == len(PNG)
    assert meta["checksum_sha256"] == hashlib.sha256(PNG).hexdigest()
    assert meta["uploader_name"] == "Test User"
    assert "storage_uri" not in meta and "storage_key" not in meta  # server-side only

    stored = db["field_log_attachments"].docs[0]
    key = f"field-log/{meta['attachment_id']}_site.png"
    assert stored["storage_uri"] == f"local://{key}"
    assert (tmp_path / key).read_bytes() == PNG

    listed = (await client.get("/field-log/attachments", params={"analysis_id": ANALYSIS},
                               headers=_auth(researcher_token))).json()
    assert [a["attachment_id"] for a in listed] == [meta["attachment_id"]]
    assert "storage_uri" not in listed[0]

    d = await client.get(f"/field-log/attachments/{meta['attachment_id']}/download", headers=_auth(researcher_token))
    assert d.status_code == 200
    assert d.content == PNG
    assert d.headers["content-type"] == "image/png"
    assert d.headers["content-disposition"].startswith('attachment; filename="site.png"')
    assert d.headers["x-content-type-options"] == "nosniff"


@pytest.mark.anyio
async def test_attachment_s3_round_trip(client, db, researcher_token, attach_storage, monkeypatch, s3, tmp_path):
    monkeypatch.setattr(attach_storage, "storage_backend", "s3")
    r = await _attach(client, researcher_token, data=PDF, name="survey.pdf", ctype="application/pdf")
    assert r.status_code == 201, r.text
    meta = r.json()
    key = f"field-log/{meta['attachment_id']}_survey.pdf"
    assert db["field_log_attachments"].docs[0]["storage_uri"] == f"s3://{BUCKET}/{key}"
    assert s3.get_object(Bucket=BUCKET, Key=key)["Body"].read() == PDF
    assert list(tmp_path.iterdir()) == []
    d = await client.get(f"/field-log/attachments/{meta['attachment_id']}/download", headers=_auth(researcher_token))
    assert d.status_code == 200 and d.content == PDF
    assert d.headers["content-type"] == "application/pdf"


@pytest.mark.anyio
async def test_attachment_type_comes_from_bytes_not_the_client(client, db, researcher_token, attach_storage):
    r = await _attach(client, researcher_token, data=JPEG, name="photo.png", ctype="image/png")
    assert r.status_code == 201
    assert r.json()["content_type"] == "image/jpeg"


@pytest.mark.anyio
@pytest.mark.parametrize("data,name,ctype", [
    (b"<html><script>alert(1)</script></html>", "evil.png", "image/png"),
    (b"GIF89a....", "anim.gif", "image/gif"),
    (b">seq\nACGT\n", "reads.fasta", "text/plain"),
])
async def test_attachment_rejects_types_outside_allowlist(client, db, researcher_token, attach_storage, tmp_path, data, name, ctype):
    r = await _attach(client, researcher_token, data=data, name=name, ctype=ctype)
    assert r.status_code == 415
    assert db["field_log_attachments"].docs == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.anyio
async def test_attachment_size_limit(client, db, researcher_token, attach_storage, tmp_path):
    big = b"%PDF-" + b"0" * (1024 * 1024)  # 1 MiB + 5 bytes, cap is 1 MiB
    r = await _attach(client, researcher_token, data=big, name="big.pdf", ctype="application/pdf")
    assert r.status_code == 413
    assert db["field_log_attachments"].docs == []
    assert list(tmp_path.iterdir()) == []
    exact = b"%PDF-" + b"0" * (1024 * 1024 - 5)
    assert (await _attach(client, researcher_token, data=exact, name="ok.pdf")).status_code == 201


@pytest.mark.anyio
async def test_attachment_empty_file_rejected(client, db, researcher_token, attach_storage):
    assert (await _attach(client, researcher_token, data=b"")).status_code == 422


@pytest.mark.anyio
async def test_attachment_filename_path_is_stripped(client, db, researcher_token, attach_storage, tmp_path):
    r = await _attach(client, researcher_token, name="C:\\fakepath\\..\\site photo.png")
    assert r.status_code == 201
    assert r.json()["original_filename"] == "site photo.png"
    key = db["field_log_attachments"].docs[0]["storage_key"]
    assert key == f"field-log/{r.json()['attachment_id']}_site_photo.png"


@pytest.mark.anyio
async def test_attachment_access_rules(client, db, researcher_token, other_researcher_token, curator_token, attach_storage):
    # Not the analysis owner: 403 on upload, list and download.
    assert (await _attach(client, other_researcher_token)).status_code == 403
    r = await _attach(client, researcher_token)
    aid = r.json()["attachment_id"]
    assert (await client.get("/field-log/attachments", params={"analysis_id": ANALYSIS},
                             headers=_auth(other_researcher_token))).status_code == 403
    assert (await client.get(f"/field-log/attachments/{aid}/download",
                             headers=_auth(other_researcher_token))).status_code == 403
    # Curator role sees it, like the entry routes.
    assert (await client.get(f"/field-log/attachments/{aid}/download",
                             headers=_auth(curator_token))).status_code == 200
    # No token: 401. Unknown analysis / attachment: 404.
    assert (await client.get("/field-log/attachments", params={"analysis_id": ANALYSIS})).status_code == 401
    assert (await _attach(client, researcher_token, analysis_id="ana_missing")).status_code == 404
    assert (await client.get("/field-log/attachments/fla_nope/download",
                             headers=_auth(researcher_token))).status_code == 404


@pytest.mark.anyio
async def test_attachment_entry_link_must_be_in_same_analysis(client, db, researcher_token, other_researcher_token, attach_storage):
    mine = await _create(client, researcher_token)
    theirs = await _create(client, other_researcher_token, analysis_id=OTHER_ANALYSIS)
    ok = await _attach(client, researcher_token, entry_id=mine["entry_id"])
    assert ok.status_code == 201 and ok.json()["entry_id"] == mine["entry_id"]
    bad = await _attach(client, researcher_token, entry_id=theirs["entry_id"])
    assert bad.status_code == 404


@pytest.mark.anyio
async def test_attachment_storage_down_is_503_and_saves_no_doc(client, db, researcher_token, attach_storage, monkeypatch, s3):
    monkeypatch.setattr(attach_storage, "storage_backend", "s3")
    monkeypatch.setattr(attach_storage, "object_storage_bucket", "bucket-that-does-not-exist")
    r = await _attach(client, researcher_token)
    assert r.status_code == 503
    assert "nothing was saved" in r.json()["detail"]
    assert db["field_log_attachments"].docs == []


@pytest.mark.anyio
async def test_attachment_download_detects_tampered_or_missing_bytes(client, db, researcher_token, attach_storage, tmp_path):
    r = await _attach(client, researcher_token)
    aid = r.json()["attachment_id"]
    key = db["field_log_attachments"].docs[0]["storage_key"]
    (tmp_path / key).write_bytes(PNG + b"tampered")
    d = await client.get(f"/field-log/attachments/{aid}/download", headers=_auth(researcher_token))
    assert d.status_code == 502
    (tmp_path / key).unlink()
    d = await client.get(f"/field-log/attachments/{aid}/download", headers=_auth(researcher_token))
    assert d.status_code == 502
