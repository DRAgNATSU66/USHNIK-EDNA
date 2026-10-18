"""
Upload storage: one small interface, two backends (roadmap B7).

The API writes uploaded files through this module and the worker reads them
back through it. The two services share no package, so this file exists
twice -- services/api/app/storage.py and services/worker/app/storage.py --
and the two copies must stay byte-identical so they behave identically
(services/api/tests/test_storage.py fails the suite otherwise). Edit one,
then copy it over the other.

Backends, chosen by the STORAGE_BACKEND setting:

  local  files under UPLOAD_STORAGE_DIR. The default, used by dev and tests.
  s3     an S3-compatible bucket: MinIO in docker-compose, or AWS S3.
         OBJECT_STORAGE_URL (endpoint; blank means AWS), OBJECT_STORAGE_BUCKET,
         OBJECT_STORAGE_ACCESS_KEY, OBJECT_STORAGE_SECRET_KEY,
         OBJECT_STORAGE_REGION.

The upload document in Mongo records where the bytes are as a storage URI,
never as a path on the API's disk:

  local://<key>         <key> is relative to the reader's UPLOAD_STORAGE_DIR
  s3://<bucket>/<key>

The URI names the backend, so a worker configured for a different backend
than the API that wrote the file still reads from the right place (or fails
loudly). Upload docs written before B7 carry only an absolute `file_path`;
local_copy_for_upload() still reads those.

Settings are read by attribute name (storage_backend, upload_storage_dir,
object_storage_*), which both services' settings classes define, so this
module imports neither config.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterator, Optional, Protocol

LOCAL_SCHEME = "local"
S3_SCHEME = "s3"
BACKENDS = (LOCAL_SCHEME, S3_SCHEME)

_CHUNK = 1024 * 1024
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")


class StorageError(RuntimeError):
    """A stored upload is missing, unreadable, or fails its checksum."""


@dataclass(frozen=True)
class StoredObject:
    key: str
    uri: str
    size_bytes: int
    sha256: str


class Storage(Protocol):
    scheme: str

    def uri(self, key: str) -> str: ...
    def put(self, key: str, stream: BinaryIO) -> StoredObject: ...
    def open(self, key: str) -> BinaryIO: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...


# ---------------------------------------------------------------------------
# Keys and URIs
# ---------------------------------------------------------------------------

def upload_key(upload_id: str, filename: str) -> str:
    """Key for an uploaded file: `<upload_id>_<filename>` with the filename
    stripped of directories and of characters unsafe in a path or S3 key.
    The extension is kept because the worker's parser picks the format by it."""
    name = PurePosixPath(filename.replace("\\", "/")).name
    name = _UNSAFE_NAME_CHARS.sub("_", name).lstrip(".") or "upload"
    return f"{upload_id}_{name}"


def _check_key(key: str) -> str:
    parts = PurePosixPath(key).parts
    if not key or key.startswith("/") or "\\" in key or ".." in parts:
        raise ValueError(f"invalid storage key: {key!r}")
    return key


def parse_uri(uri: str) -> tuple[str, Optional[str], str]:
    """Split a storage URI into (scheme, bucket, key); bucket is None for local."""
    scheme, sep, rest = uri.partition("://")
    if not sep:
        raise ValueError(f"not a storage URI: {uri!r}")
    if scheme == LOCAL_SCHEME:
        return scheme, None, _check_key(rest)
    if scheme == S3_SCHEME:
        bucket, _, key = rest.partition("/")
        if not bucket:
            raise ValueError(f"storage URI has no bucket: {uri!r}")
        return scheme, bucket, _check_key(key)
    raise ValueError(f"unknown storage scheme {scheme!r} in {uri!r}")


class _HashingReader:
    """File-like wrapper that hashes and counts the bytes read through it."""

    def __init__(self, stream: BinaryIO):
        self._stream = stream
        self._hash = hashlib.sha256()
        self.size = 0

    def read(self, n: int = -1) -> bytes:
        data = self._stream.read(n)
        self._hash.update(data)
        self.size += len(data)
        return data

    @property
    def sha256(self) -> str:
        return self._hash.hexdigest()


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class LocalStorage:
    """Files under one root directory. put() writes a temp file in the same
    directory and renames it into place, so a reader never sees half a file."""

    scheme = LOCAL_SCHEME

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)

    def path(self, key: str) -> Path:
        return self.root / _check_key(key)

    def uri(self, key: str) -> str:
        return f"{LOCAL_SCHEME}://{_check_key(key)}"

    def put(self, key: str, stream: BinaryIO) -> StoredObject:
        dest = self.path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        reader = _HashingReader(stream)
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".partial-")
        try:
            with os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(reader, out, _CHUNK)
            os.replace(tmp, dest)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return StoredObject(key, self.uri(key), reader.size, reader.sha256)

    def missing(self, key: str) -> StorageError:
        return StorageError(
            f"{self.uri(key)} not found under {self.root.resolve()} "
            "(UPLOAD_STORAGE_DIR must be the directory the API writes to)"
        )

    def open(self, key: str) -> BinaryIO:
        try:
            return self.path(key).open("rb")
        except FileNotFoundError as exc:
            raise self.missing(key) from exc

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


class S3Storage:
    """One bucket on an S3-compatible endpoint (MinIO, AWS S3)."""

    scheme = S3_SCHEME

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: Optional[str] = None,
        client: Any = None,
    ):
        if not bucket:
            raise ValueError("S3 storage needs a bucket (OBJECT_STORAGE_BUCKET)")
        self.bucket = bucket
        if client is None:
            import boto3  # only the s3 backend needs it
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url or None,
                aws_access_key_id=access_key or None,
                aws_secret_access_key=secret_key or None,
                region_name=region or None,
                # A custom endpoint (MinIO) gets path-style addressing: it
                # serves buckets at http://host:9000/<bucket>, not at
                # <bucket>.host. AWS (no endpoint) keeps boto3's default.
                config=Config(
                    s3={"addressing_style": "path" if endpoint_url else "auto"},
                    signature_version="s3v4",
                ),
            )
        self.client = client

    def uri(self, key: str) -> str:
        return f"{S3_SCHEME}://{self.bucket}/{_check_key(key)}"

    def ensure_bucket(self) -> bool:
        """Create the bucket if it is missing. Returns True if it was created."""
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
            return False
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket", "NotFound"):
                raise
        self.client.create_bucket(Bucket=self.bucket)
        return True

    def put(self, key: str, stream: BinaryIO) -> StoredObject:
        reader = _HashingReader(stream)
        self.client.upload_fileobj(reader, self.bucket, _check_key(key))
        return StoredObject(key, self.uri(key), reader.size, reader.sha256)

    def open(self, key: str) -> BinaryIO:
        from botocore.exceptions import ClientError

        try:
            return self.client.get_object(Bucket=self.bucket, Key=_check_key(key))["Body"]
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                raise StorageError(f"{self.uri(key)} not found") from exc
            raise

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=_check_key(key))
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_check_key(key))


# ---------------------------------------------------------------------------
# Construction from settings
# ---------------------------------------------------------------------------

_cache: dict[tuple, Storage] = {}


def _s3_params(settings: Any, bucket: Optional[str] = None) -> tuple:
    return (
        S3_SCHEME,
        bucket or settings.object_storage_bucket,
        settings.object_storage_url,
        settings.object_storage_access_key,
        settings.object_storage_secret_key,
        settings.object_storage_region,
    )


def _build(params: tuple) -> Storage:
    if params not in _cache:
        if params[0] == LOCAL_SCHEME:
            _cache[params] = LocalStorage(params[1])
        else:
            _, bucket, endpoint, access, secret, region = params
            _cache[params] = S3Storage(
                bucket, endpoint_url=endpoint, access_key=access,
                secret_key=secret, region=region,
            )
    return _cache[params]


def storage_from_settings(settings: Any) -> Storage:
    """The backend new uploads are written to (STORAGE_BACKEND)."""
    backend = settings.storage_backend
    if backend == LOCAL_SCHEME:
        return _build((LOCAL_SCHEME, settings.upload_storage_dir))
    if backend == S3_SCHEME:
        return _build(_s3_params(settings))
    raise ValueError(f"STORAGE_BACKEND must be one of {BACKENDS}, got {backend!r}")


def storage_for_uri(uri: str, settings: Any) -> tuple[Storage, str]:
    """The backend holding `uri`, whatever STORAGE_BACKEND says, plus its key."""
    scheme, bucket, key = parse_uri(uri)
    if scheme == LOCAL_SCHEME:
        return _build((LOCAL_SCHEME, settings.upload_storage_dir)), key
    return _build(_s3_params(settings, bucket)), key


def clear_cache() -> None:
    """Forget built backends (tests that change settings call this)."""
    _cache.clear()


# ---------------------------------------------------------------------------
# Reading an upload as a local file (the parser needs a path)
# ---------------------------------------------------------------------------

def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify(upload: dict, actual: str, where: str) -> None:
    expected = upload.get("checksum_sha256")
    if expected and expected != actual:
        raise StorageError(
            f"checksum mismatch for {where}: upload doc has sha256 {expected}, "
            f"stored bytes hash to {actual}"
        )


@contextmanager
def local_copy_for_upload(upload: dict, settings: Any) -> Iterator[Path]:
    """
    Yield a local path holding the bytes of an upload document's file.

    - storage_uri local://  -> the file under UPLOAD_STORAGE_DIR, read in place.
    - storage_uri s3://     -> streamed into a temp file (same extension, so
                               format detection still works), deleted on exit.
    - no storage_uri, but a legacy `file_path` (pre-B7 docs) -> that path.

    When the doc records checksum_sha256 the bytes are verified against it.
    Raises ValueError when the doc names no file at all, StorageError when
    the file is missing or fails the checksum.
    """
    uri = upload.get("storage_uri")
    upload_id = upload.get("upload_id", "?")

    if not uri:
        legacy = upload.get("file_path")
        if not legacy:
            raise ValueError(
                f"Upload {upload_id} has no storage_uri or file_path; nothing to parse"
            )
        path = Path(legacy)
        if not path.is_file():
            raise StorageError(f"Upload {upload_id}: legacy file_path {legacy} not found")
        yield path
        return

    storage, key = storage_for_uri(uri, settings)
    if isinstance(storage, LocalStorage):
        path = storage.path(key)
        if not path.is_file():
            raise storage.missing(key)
        _verify(upload, _file_sha256(path), uri)
        yield path
        return

    suffix = "".join(PurePosixPath(key).suffixes[-1:])
    fd, tmp = tempfile.mkstemp(prefix="synthveda-upload-", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as out:
            body = storage.open(key)
            try:
                reader = _HashingReader(body)
                shutil.copyfileobj(reader, out, _CHUNK)
            finally:
                body.close()
        _verify(upload, reader.sha256, uri)
        yield Path(tmp)
    finally:
        Path(tmp).unlink(missing_ok=True)
