"""
B7: the worker's parse stage reads uploads through app/storage.py.

The storage module itself is tested in services/api/tests/test_storage.py
(which also checks this service's copy is byte-identical). These tests
cover the worker's side: _stage_parse() parses a local:// upload, an s3://
upload (moto), a pre-B7 doc with only a file_path, and fails the job --
never fabricates sequences -- when the bytes are missing or corrupted.
"""
from __future__ import annotations

import hashlib
from io import BytesIO

import boto3
import pytest
from moto import mock_aws

from app import storage
from app.config import get_worker_settings
from app.job_runner import _stage_parse
from app.storage import StorageError, storage_from_settings

BUCKET = "synthveda-test-uploads"
FASTA = b">seq_001\nATCGATCGATCGATCGATCG\n>seq_002\nGCATGCATGCATGCATGCAT\n"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    s = get_worker_settings()
    for name, value in {
        "storage_backend": "local",
        "upload_storage_dir": str(tmp_path),
        "object_storage_url": "",
        "object_storage_bucket": BUCKET,
        "object_storage_access_key": "testing",
        "object_storage_secret_key": "testing",
        "object_storage_region": "us-east-1",
    }.items():
        monkeypatch.setattr(s, name, value)
    storage.clear_cache()
    yield s
    storage.clear_cache()


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def _doc(obj):
    return {
        "upload_id": "upl_1",
        "original_filename": "sample.fasta",
        "storage_uri": obj.uri,
        "checksum_sha256": obj.sha256,
    }


def _ids(records):
    return [r["sequence_id"] for r in records]


async def test_parses_a_local_upload(settings):
    obj = storage_from_settings(settings).put("upl_1_sample.fasta", BytesIO(FASTA))
    assert obj.uri == "local://upl_1_sample.fasta"
    assert _ids(await _stage_parse(_doc(obj))) == ["seq_001", "seq_002"]


async def test_parses_an_s3_upload(settings, s3, monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    obj = storage_from_settings(settings).put("upl_1_sample.fasta", BytesIO(FASTA))
    assert obj.uri == f"s3://{BUCKET}/upl_1_sample.fasta"
    assert _ids(await _stage_parse(_doc(obj))) == ["seq_001", "seq_002"]


async def test_s3_upload_is_read_even_if_worker_backend_is_local(settings, s3, monkeypatch):
    # The URI, not STORAGE_BACKEND, decides where the worker reads from.
    s3.put_object(Bucket=BUCKET, Key="upl_1_sample.fasta", Body=FASTA)
    doc = {"upload_id": "upl_1", "storage_uri": f"s3://{BUCKET}/upl_1_sample.fasta"}
    assert settings.storage_backend == "local"
    assert _ids(await _stage_parse(doc)) == ["seq_001", "seq_002"]


async def test_parses_a_legacy_file_path_upload(settings, tmp_path):
    legacy = tmp_path / "legacy_upl_0_sample.fasta"
    legacy.write_bytes(FASTA)
    doc = {"upload_id": "upl_0", "file_path": str(legacy)}
    assert _ids(await _stage_parse(doc)) == ["seq_001", "seq_002"]


async def test_no_file_fails_instead_of_inventing_sequences(settings):
    with pytest.raises(ValueError, match="nothing to parse"):
        await _stage_parse({"upload_id": "upl_x"})


async def test_missing_local_object_names_upload_storage_dir(settings):
    with pytest.raises(StorageError, match="UPLOAD_STORAGE_DIR"):
        await _stage_parse({"upload_id": "upl_1", "storage_uri": "local://upl_1_gone.fasta"})


async def test_missing_s3_object(settings, s3):
    with pytest.raises(StorageError, match="not found"):
        await _stage_parse({"upload_id": "upl_1", "storage_uri": f"s3://{BUCKET}/upl_1_gone.fasta"})


async def test_corrupted_bytes_fail_the_checksum(settings, s3):
    s3.put_object(Bucket=BUCKET, Key="upl_1_sample.fasta", Body=FASTA)
    doc = {
        "upload_id": "upl_1",
        "storage_uri": f"s3://{BUCKET}/upl_1_sample.fasta",
        "checksum_sha256": hashlib.sha256(b"something else").hexdigest(),
    }
    with pytest.raises(StorageError, match="checksum mismatch"):
        await _stage_parse(doc)
