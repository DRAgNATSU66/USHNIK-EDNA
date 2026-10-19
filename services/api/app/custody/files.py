"""
Re-hash an upload's stored bytes (custody file check, FAIR raw-file copy).

The upload doc records checksum_sha256 of the bytes as written (B7,
app/storage.py). Reading them back through the same storage URI and
re-hashing is the "file unaltered since upload" check. Synchronous (boto3
and file reads block); callers run it in the threadpool.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, BinaryIO, Optional

from ..storage import storage_for_uri

_CHUNK = 1024 * 1024


def check_stored_file(
    upload: dict[str, Any],
    settings: Any,
    copy_to: Optional[BinaryIO] = None,
) -> dict[str, Any]:
    """
    Stream the stored bytes, hash them, optionally copy them to `copy_to`.

    Returns {status, expected_sha256, actual_sha256, bytes, source, reason}
    with status one of:
      verified       bytes hash to the recorded checksum_sha256
      mismatch       bytes differ from what was uploaded
      unverifiable   bytes read, but the upload doc has no checksum (pre-B7)
      unavailable    no stored file named, or storage could not be read
    """
    expected = upload.get("checksum_sha256")
    uri = upload.get("storage_uri")
    legacy = upload.get("file_path")
    out: dict[str, Any] = {
        "status": "unavailable",
        "expected_sha256": expected,
        "actual_sha256": None,
        "bytes": None,
        "source": uri or ("legacy file_path" if legacy else None),
        "reason": None,
    }
    if not uri and not legacy:
        out["reason"] = "the upload record names no stored file"
        return out

    stream: Optional[BinaryIO] = None
    try:
        if uri:
            storage, key = storage_for_uri(uri, settings)
            stream = storage.open(key)
        else:
            stream = Path(legacy).open("rb")
        h = hashlib.sha256()
        size = 0
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            h.update(chunk)
            size += len(chunk)
            if copy_to is not None:
                copy_to.write(chunk)
    except Exception as exc:  # missing file, storage down, bad credentials
        out["reason"] = f"stored file could not be read ({type(exc).__name__}: {exc})"
        return out
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

    actual = h.hexdigest()
    out.update(actual_sha256=actual, bytes=size)
    if not expected:
        out["status"] = "unverifiable"
        out["reason"] = "the upload record has no checksum_sha256 (uploaded before B7)"
    elif actual == expected:
        out["status"] = "verified"
    else:
        out["status"] = "mismatch"
        out["reason"] = "stored bytes do not hash to the checksum recorded at upload"
    return out
