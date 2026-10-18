"""
B7: upload storage (app/storage.py), local and S3-compatible backends.

- The API's and the worker's copies of storage.py are byte-identical, and
  both services' settings define the storage fields with the same defaults
  (the services share no package, so this is the only thing keeping them
  in step).
- Both backends round-trip bytes, report size + sha256, and refuse keys
  that would escape their root/bucket. S3 runs against moto.
- local_copy_for_upload() reads local://, s3:// and legacy file_path docs,
  and fails loudly on a missing file or a checksum mismatch.
- POST /uploads writes through the configured backend and stores the URI.
"""
from __future__ import annotations

import ast
import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

import app.db.mongo as _mongo_module
from app import storage
from app.config import Settings, get_settings
from app.storage import (
    LocalStorage,
    S3Storage,
    StorageError,
    local_copy_for_upload,
    parse_uri,
    storage_for_uri,
    storage_from_settings,
    upload_key,
)

API_STORAGE = Path(__file__).resolve().parents[1] / "app" / "storage.py"
WORKER_ROOT = Path(__file__).resolve().parents[2] / "worker"
WORKER_STORAGE = WORKER_ROOT / "app" / "storage.py"
WORKER_CONFIG = WORKER_ROOT / "app" / "config.py"

STORAGE_FIELDS = (
    "storage_backend",
    "upload_storage_dir",
    "object_storage_url",
    "object_storage_bucket",
    "object_storage_access_key",
    "object_storage_secret_key",
    "object_storage_region",
)

BUCKET = "synthveda-test-uploads"
FASTA = b">seq_001\nATCGATCGATCGATCGATCG\n>seq_002\nGCATGCATGCATGCAT\n"
FASTA_SHA = hashlib.sha256(FASTA).hexdigest()


def _settings(tmp_path, backend="local", **overrides):
    values = dict(
        storage_backend=backend,
        upload_storage_dir=str(tmp_path),
        object_storage_url="",
        object_storage_bucket=BUCKET,
        object_storage_access_key="testing",
        object_storage_secret_key="testing",
        object_storage_region="us-east-1",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def _fresh_backends():
    storage.clear_cache()
    yield
    storage.clear_cache()


@pytest.fixture
def s3(monkeypatch):
    """A moto S3 with BUCKET created; yields a plain boto3 client to inspect it."""
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


# ---------------------------------------------------------------------------
# The two copies stay identical
# ---------------------------------------------------------------------------

def test_worker_copy_is_byte_identical():
    assert WORKER_STORAGE.is_file(), f"missing {WORKER_STORAGE}"
    assert API_STORAGE.read_bytes() == WORKER_STORAGE.read_bytes(), (
        "services/api/app/storage.py and services/worker/app/storage.py differ: "
        "edit one, then copy it over the other"
    )


def _class_field_defaults(path: Path, class_name: str) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                stmt.target.id: ast.literal_eval(stmt.value)
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.value is not None
                and stmt.target.id in STORAGE_FIELDS
            }
    raise AssertionError(f"class {class_name} not found in {path}")


def test_worker_settings_define_the_same_storage_fields():
    worker = _class_field_defaults(WORKER_CONFIG, "WorkerSettings")
    api = {name: Settings.model_fields[name].default for name in STORAGE_FIELDS}
    assert worker == api


def test_local_is_the_default_backend():
    assert Settings.model_fields["storage_backend"].default == "local"


def test_unknown_backend_is_rejected_at_settings_load(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "gcs")
    with pytest.raises(ValueError):
        Settings()


# ---------------------------------------------------------------------------
# Keys and URIs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "filename, expected",
    [
        ("sample.fasta", "upl_1_sample.fasta"),
        ("../../etc/passwd.fa", "upl_1_passwd.fa"),
        ("C:\\Users\\me\\run 1.fastq", "upl_1_run_1.fastq"),
        (".hidden.json", "upl_1_hidden.json"),
        ("über?.fa", "upl_1__ber_.fa"),
    ],
)
def test_upload_key_is_safe_and_keeps_the_extension(filename, expected):
    key = upload_key("upl_1", filename)
    assert key == expected
    assert "/" not in key and ".." not in key


def test_parse_uri():
    assert parse_uri("local://upl_1_a.fasta") == ("local", None, "upl_1_a.fasta")
    assert parse_uri("s3://bkt/dir/upl_1_a.fasta") == ("s3", "bkt", "dir/upl_1_a.fasta")


@pytest.mark.parametrize(
    "uri",
    ["/abs/path.fasta", "local://../escape.fa", "local:///etc/passwd", "s3:///key", "gs://b/k", "s3://bkt/"],
)
def test_parse_uri_rejects_bad_uris(uri):
    with pytest.raises(ValueError):
        parse_uri(uri)


# ---------------------------------------------------------------------------
# Local backend
# ---------------------------------------------------------------------------

def test_local_round_trip(tmp_path):
    store = LocalStorage(tmp_path)
    obj = store.put("upl_1_a.fasta", BytesIO(FASTA))
    assert obj.uri == "local://upl_1_a.fasta"
    assert (obj.size_bytes, obj.sha256) == (len(FASTA), FASTA_SHA)
    assert (tmp_path / "upl_1_a.fasta").read_bytes() == FASTA
    assert store.exists("upl_1_a.fasta")
    with store.open("upl_1_a.fasta") as f:
        assert f.read() == FASTA
    # The temp file was renamed into place, not left behind.
    assert [p.name for p in tmp_path.iterdir()] == ["upl_1_a.fasta"]
    store.delete("upl_1_a.fasta")
    assert not store.exists("upl_1_a.fasta")


def test_local_missing_file_names_the_storage_dir(tmp_path):
    with pytest.raises(StorageError, match="UPLOAD_STORAGE_DIR"):
        LocalStorage(tmp_path).open("nope.fasta")


def test_local_failed_write_leaves_nothing(tmp_path):
    class Exploding:
        def read(self, n=-1):
            raise OSError("disk full")

    with pytest.raises(OSError):
        LocalStorage(tmp_path).put("upl_1_a.fasta", Exploding())
    assert list(tmp_path.iterdir()) == []


def test_local_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).put("../outside.fasta", BytesIO(FASTA))


# ---------------------------------------------------------------------------
# S3 backend (moto)
# ---------------------------------------------------------------------------

def test_s3_round_trip(tmp_path, s3):
    store = storage_from_settings(_settings(tmp_path, "s3"))
    assert isinstance(store, S3Storage)
    obj = store.put("upl_1_a.fasta", BytesIO(FASTA))
    assert obj.uri == f"s3://{BUCKET}/upl_1_a.fasta"
    assert (obj.size_bytes, obj.sha256) == (len(FASTA), FASTA_SHA)
    assert s3.get_object(Bucket=BUCKET, Key="upl_1_a.fasta")["Body"].read() == FASTA
    assert store.exists("upl_1_a.fasta")
    assert store.open("upl_1_a.fasta").read() == FASTA
    store.delete("upl_1_a.fasta")
    assert not store.exists("upl_1_a.fasta")


def test_s3_missing_object_is_a_storage_error(tmp_path, s3):
    store = storage_from_settings(_settings(tmp_path, "s3"))
    with pytest.raises(StorageError, match="not found"):
        store.open("nope.fasta")


def test_s3_ensure_bucket_creates_once(tmp_path, s3):
    store = storage_from_settings(_settings(tmp_path, "s3", object_storage_bucket="fresh-bucket"))
    assert store.ensure_bucket() is True
    assert store.ensure_bucket() is False
    assert "fresh-bucket" in [b["Name"] for b in s3.list_buckets()["Buckets"]]


def test_s3_large_upload_goes_multipart_and_hashes_every_byte(tmp_path, s3):
    data = bytes(range(256)) * (4096 * 9)  # 9 MiB > boto3's 8 MiB multipart threshold
    obj = storage_from_settings(_settings(tmp_path, "s3")).put("upl_1_big.fasta", BytesIO(data))
    assert obj.size_bytes == len(data)
    assert obj.sha256 == hashlib.sha256(data).hexdigest()
    assert s3.head_object(Bucket=BUCKET, Key="upl_1_big.fasta")["ContentLength"] == len(data)


def test_storage_from_settings_rejects_unknown_backend(tmp_path):
    with pytest.raises(ValueError, match="STORAGE_BACKEND"):
        storage_from_settings(_settings(tmp_path, "gcs"))


def test_storage_for_uri_follows_the_uri_not_the_setting(tmp_path, s3):
    # Configured for local, but the doc says s3: read from s3, and from the
    # bucket the URI names.
    settings = _settings(tmp_path, "local")
    store, key = storage_for_uri("s3://other-bucket/upl_1_a.fasta", settings)
    assert isinstance(store, S3Storage) and store.bucket == "other-bucket"
    assert key == "upl_1_a.fasta"
    store, key = storage_for_uri("local://upl_1_a.fasta", _settings(tmp_path, "s3"))
    assert isinstance(store, LocalStorage) and store.root == tmp_path


# ---------------------------------------------------------------------------
# local_copy_for_upload (what the worker's parser calls)
# ---------------------------------------------------------------------------

def test_local_copy_reads_local_uri_in_place(tmp_path):
    settings = _settings(tmp_path)
    obj = storage_from_settings(settings).put("upl_1_a.fasta", BytesIO(FASTA))
    doc = {"upload_id": "upl_1", "storage_uri": obj.uri, "checksum_sha256": obj.sha256}
    with local_copy_for_upload(doc, settings) as path:
        assert path == tmp_path / "upl_1_a.fasta"
        assert path.read_bytes() == FASTA
    assert path.exists()  # the stored file itself is never deleted


def test_local_copy_streams_s3_to_a_temp_file_and_cleans_up(tmp_path, s3):
    settings = _settings(tmp_path, "s3")
    obj = storage_from_settings(settings).put("upl_1_a.fasta", BytesIO(FASTA))
    doc = {"upload_id": "upl_1", "storage_uri": obj.uri, "checksum_sha256": obj.sha256}
    with local_copy_for_upload(doc, settings) as path:
        # Same name as the local backend's file: the parser picks the format
        # by extension and records the name as source_file.
        assert path.name == "upl_1_a.fasta"
        assert path.read_bytes() == FASTA
    assert not path.exists() and not path.parent.exists()


def test_local_copy_reads_legacy_file_path(tmp_path):
    legacy = tmp_path / "old" / "upl_0_a.fasta"
    legacy.parent.mkdir()
    legacy.write_bytes(FASTA)
    doc = {"upload_id": "upl_0", "file_path": str(legacy)}
    with local_copy_for_upload(doc, _settings(tmp_path / "elsewhere", "s3")) as path:
        assert path == legacy


def test_local_copy_missing_legacy_file(tmp_path):
    doc = {"upload_id": "upl_0", "file_path": str(tmp_path / "gone.fasta")}
    with pytest.raises(StorageError, match="legacy file_path"):
        with local_copy_for_upload(doc, _settings(tmp_path)):
            pass


def test_local_copy_with_no_file_at_all(tmp_path):
    with pytest.raises(ValueError, match="no storage_uri or file_path"):
        with local_copy_for_upload({"upload_id": "upl_x"}, _settings(tmp_path)):
            pass


def test_local_copy_missing_local_object(tmp_path):
    doc = {"upload_id": "upl_1", "storage_uri": "local://upl_1_a.fasta"}
    with pytest.raises(StorageError, match="not found"):
        with local_copy_for_upload(doc, _settings(tmp_path)):
            pass


@pytest.mark.parametrize("backend", ["local", "s3"])
def test_local_copy_checksum_mismatch(tmp_path, s3, backend):
    settings = _settings(tmp_path, backend)
    obj = storage_from_settings(settings).put("upl_1_a.fasta", BytesIO(FASTA))
    doc = {"upload_id": "upl_1", "storage_uri": obj.uri, "checksum_sha256": "0" * 64}
    with pytest.raises(StorageError, match="checksum mismatch"):
        with local_copy_for_upload(doc, settings):
            pass


# ---------------------------------------------------------------------------
# POST /uploads writes through the backend
# ---------------------------------------------------------------------------

class _RecordingUploads:
    def __init__(self):
        self.docs: list[dict] = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))


class _RecordingDb:
    def __init__(self):
        self.uploads = _RecordingUploads()

    def __getitem__(self, name):
        assert name == "uploads", name
        return self.uploads


@pytest.fixture
def recording_db():
    db = _RecordingDb()
    with patch.object(_mongo_module, "_db", db):
        yield db


@pytest.fixture
def api_storage(monkeypatch, tmp_path):
    """Point the API's (cached) settings at tmp_path / the test bucket."""
    settings = get_settings()
    for name, value in vars(_settings(tmp_path)).items():
        monkeypatch.setattr(settings, name, value)
    return settings


async def _post(client, token, name="sample.fasta"):
    return await client.post(
        "/uploads",
        files={"file": (name, BytesIO(FASTA), "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.anyio
async def test_upload_route_local_backend(client, researcher_token, recording_db, api_storage, tmp_path):
    resp = await _post(client, researcher_token)
    assert resp.status_code == 201, resp.text
    doc = recording_db.uploads.docs[0]
    key = f"{doc['upload_id']}_sample.fasta"
    assert doc["storage_uri"] == f"local://{key}"
    assert doc["storage_key"] == key
    assert doc["checksum_sha256"] == FASTA_SHA
    assert doc["file_path"] is None  # no absolute API path in new docs
    assert (tmp_path / key).read_bytes() == FASTA
    assert resp.json()["storage_uri"] == doc["storage_uri"]


@pytest.mark.anyio
async def test_upload_route_s3_backend(client, researcher_token, recording_db, api_storage, monkeypatch, s3, tmp_path):
    monkeypatch.setattr(api_storage, "storage_backend", "s3")
    resp = await _post(client, researcher_token)
    assert resp.status_code == 201, resp.text
    doc = recording_db.uploads.docs[0]
    key = f"{doc['upload_id']}_sample.fasta"
    assert doc["storage_uri"] == f"s3://{BUCKET}/{key}"
    assert s3.get_object(Bucket=BUCKET, Key=key)["Body"].read() == FASTA
    assert list(tmp_path.iterdir()) == []  # nothing on the API's disk
    # And what the worker does with that doc:
    with local_copy_for_upload(doc, api_storage) as path:
        assert path.read_bytes() == FASTA


@pytest.mark.anyio
async def test_upload_route_storage_down_is_503_and_saves_no_doc(
    client, researcher_token, recording_db, api_storage, monkeypatch, s3
):
    monkeypatch.setattr(api_storage, "storage_backend", "s3")
    monkeypatch.setattr(api_storage, "object_storage_bucket", "bucket-that-does-not-exist")
    resp = await _post(client, researcher_token)
    assert resp.status_code == 503
    assert "nothing was saved" in resp.json()["detail"]
    assert recording_db.uploads.docs == []
