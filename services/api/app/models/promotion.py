"""
Helpers for POST /models/register and POST /models/{model_id}/promote (B8).

How a promotion is represented
------------------------------
The registry JSON file *is* the promotion. The worker picks models from
models/registry/*.json (services/worker/app/inference/registry.py,
best_available): production > staging > experimental, newest created_at within
a tier. So promoting means writing "status": "production" into the entry's
file, and demoting any other production entry on the same route to "staging".
There is no second store the worker would have to consult, so the API and the
worker cannot disagree about what is promoted.

Registration writes "status": "candidate". Both services rank that below every
serving tier, so registering a model never changes what is served; only a
promotion does.

Who/when/metrics go to MongoDB: one model_eval_metrics document and one
audit_logs document per promotion (the same audit_logs collection the review
and curation endpoints write). The registry file also carries promoted_by /
promoted_at, so a reviewer reading the git diff sees who promoted it.

Everything in this module is plain file and dict logic; the endpoints, auth
and Mongo writes are in router.py.
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path, PurePosixPath

DATA_URI_PREFIX = "data:"
ROUTER_ROUTE = "router"
CANDIDATE_STATUS = "candidate"

# Metrics a registered model must report. Every checked-in entry already has
# these three (models/registry/*.json); the promote confirmation compares them.
REQUIRED_METRICS = ("test_accuracy", "test_macro_f1", "test_size")
_UNIT_INTERVAL_METRICS = ("test_accuracy", "test_macro_f1")

MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The worker only loads route-model heads from .pt/.bin (predictor._run_model)
# and the router from .npz (model_router/learned.py).
_ARTIFACT_SUFFIXES = {"route": (".pt", ".bin"), ROUTER_ROUTE: (".npz",)}


class RegistryError(Exception):
    """A request the registry cannot satisfy. status_code maps onto HTTP."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# Paths and checksums
# ---------------------------------------------------------------------------

def resolve_data_path(uri: str, data_root: Path) -> Path:
    """
    Turn "data:<relative path>" into a path under the data root.

    Only data: URIs are accepted: the checksum has to be computed on a file
    the API can read, and the worker only loads heads from local files. The
    relative part may not be absolute or climb out with "..".
    """
    if not isinstance(uri, str) or not uri.startswith(DATA_URI_PREFIX):
        raise RegistryError(422, f"{uri!r} must be a data:<relative path> URI under the data root")
    rel = uri[len(DATA_URI_PREFIX):]
    parts = PurePosixPath(rel).parts
    if not rel or rel.startswith("/") or "\\" in rel or ".." in parts:
        raise RegistryError(422, f"{uri!r} must be a relative path inside the data root")
    return data_root / rel


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def verify_artifact(entry: dict, data_root: Path) -> str:
    """
    Check the entry's head/router artifact exists under the data root and its
    SHA-256 equals the entry's checksum. Returns the verified checksum.
    """
    route = entry.get("route")
    uri = entry.get("artifact_uri")
    if not uri:
        raise RegistryError(422, "artifact_uri is required: an entry without weights cannot serve")
    path = resolve_data_path(uri, data_root)
    suffixes = _ARTIFACT_SUFFIXES[ROUTER_ROUTE if route == ROUTER_ROUTE else "route"]
    if not path.name.endswith(suffixes):
        raise RegistryError(
            422, f"artifact_uri for route {route!r} must end in {' or '.join(suffixes)}; the worker cannot load {path.name!r}"
        )
    if not data_root.is_dir():
        raise RegistryError(503, "data root not found on the API host; cannot verify the artifact checksum")
    if not path.is_file():
        raise RegistryError(422, f"artifact not found under the data root: {uri}")
    expected = (entry.get("checksum") or "").lower()
    if not SHA256_RE.match(expected):
        raise RegistryError(422, "checksum must be the 64-hex SHA-256 of the artifact file")
    actual = await asyncio.to_thread(sha256_file, path)
    if actual != expected:
        raise RegistryError(
            422, f"checksum mismatch for {uri}: registry says {expected[:12]}..., file is {actual[:12]}..."
        )
    return actual


def check_base_model(entry: dict, data_root: Path) -> None:
    """A data: backbone must exist. Hub ids and the router's descriptor pass."""
    base = entry.get("base_model") or ""
    if base.startswith(DATA_URI_PREFIX) and not resolve_data_path(base, data_root).exists():
        raise RegistryError(422, f"base_model not found under the data root: {base}")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def metric_problems(metrics) -> list[str]:
    """Why these metrics cannot back a promotion; empty when they can."""
    if not isinstance(metrics, dict):
        return ["metrics must be an object"]
    problems = []
    for key in REQUIRED_METRICS:
        if key not in metrics:
            problems.append(f"missing metric {key}")
        elif not _is_number(metrics[key]):
            problems.append(f"metric {key} must be a finite number")
    for key in _UNIT_INTERVAL_METRICS:
        v = metrics.get(key)
        if _is_number(v) and not 0.0 <= v <= 1.0:
            problems.append(f"metric {key} must be in [0, 1], got {v}")
    n = metrics.get("test_size")
    if _is_number(n) and (n <= 0 or int(n) != n):
        problems.append(f"metric test_size must be a positive integer, got {n}")
    return problems


def metric_deltas(candidate: dict, current: dict | None) -> list[dict]:
    """
    Numeric metrics of the candidate next to the current model's, required
    metrics first. delta is candidate - current, or None when either is absent.
    """
    cm = candidate.get("metrics") or {}
    pm = (current or {}).get("metrics") or {}
    keys = [k for k in REQUIRED_METRICS if k in cm or k in pm]
    keys += sorted(k for k in set(cm) | set(pm) if k not in REQUIRED_METRICS and (_is_number(cm.get(k)) or _is_number(pm.get(k))))
    rows = []
    for k in keys:
        a, b = cm.get(k), pm.get(k)
        a = a if _is_number(a) else None
        b = b if _is_number(b) else None
        rows.append({
            "metric": k,
            "candidate": a,
            "current": b,
            "delta": round(a - b, 6) if a is not None and b is not None else None,
        })
    return rows


def comparability_warnings(candidate: dict, current: dict | None) -> list[str]:
    """Reasons the deltas are not a like-for-like comparison."""
    if current is None:
        return ["no model currently serves this route; there is nothing to compare against"]
    out = []
    if candidate.get("label_set_version") != current.get("label_set_version"):
        out.append(
            f"label sets differ ({current.get('label_set_version')} -> {candidate.get('label_set_version')}); "
            "metrics are over different classes"
        )
    if candidate.get("training_dataset_version") != current.get("training_dataset_version"):
        out.append(
            f"dataset versions differ ({current.get('training_dataset_version')} -> "
            f"{candidate.get('training_dataset_version')}); test splits are not the same, so deltas are indicative only"
        )
    return out


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def write_json_atomic(path: Path, data: dict) -> None:
    """Write via a temp file in the same dir + os.replace, so a reader (the
    worker) sees the old file or the new one, never a half-written one."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def restore_text(path: Path, original: str | None) -> None:
    """Undo a write: put the original text back, or remove a file that was new."""
    if original is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(original)
    os.replace(tmp, path)


_PROCESS_LOCK = asyncio.Lock()


@contextlib.asynccontextmanager
async def registry_lock(registry_dir: Path, timeout_s: float = 10.0):
    """
    Serialise registry writes: an asyncio lock within this process, plus an
    flock on the registry directory against other API processes. Held across
    the file writes and the Mongo audit writes, so a rollback never clobbers a
    concurrent change.
    """
    async with _PROCESS_LOCK:
        fd = os.open(registry_dir, os.O_RDONLY)
        try:
            deadline = time.monotonic() + timeout_s
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise RegistryError(503, "model registry is locked by another writer; retry")
                    await asyncio.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
