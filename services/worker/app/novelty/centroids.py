"""
Per-route class centroids for the novelty scorer's embedding-isolation term
(B5, tracker t-1024-1).

The artifact is built by training/novelty_centroids.py from the TRAIN split's
known rows of one served head, embedded exactly as that head embeds at
inference ([CLS] = last_hidden_state[:, 0] of the head's own backbone, at the
head's own max_length; app/inference/heads.get_cls_embedding). It lives next
to the head weights:

    <dirname(artifact_uri)>/novelty_centroids_v1.json   manifest
    <dirname(artifact_uri)>/novelty_centroids_v1.npz    arrays

npz arrays:
  centroids        (K, D) float32, L2-normalised (spherical k-means per known
                   class: known_species, likely_taxonomic_group and, on misc,
                   unknown_needs_online_confirmation)
  centroid_class   (K,) str, the known class each centroid was fitted on
  calib_quantiles  (Q,) float32, sorted quantiles of the nearest-centroid
                   cosine distance of a held-out calibration fold of the same
                   train-known rows (rows not used to fit the centroids)

The signal for a read is the empirical CDF of its nearest-centroid cosine
distance under calib_quantiles: the fraction of known training reads that sit
closer to a known centroid than this read does. 0 = as close as the closest
known reads, 1 = farther than every calibration read.

The artifact is found by convention from the registry entry of the model
that produced the embedding (the head's model_version_used), and is only
used when its manifest names the same model_id and head checksum and its
npz hashes to the manifest's sha256. Anything else -> no centroids, with a
reason; the scorer then falls back to the old L2-norm proxy and says so in
the reason codes (never raises).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

CENTROIDS_VERSION = "v1"
CENTROIDS_STEM = f"novelty_centroids_{CENTROIDS_VERSION}"
MANIFEST_NAME = f"{CENTROIDS_STEM}.json"
ARRAYS_NAME = f"{CENTROIDS_STEM}.npz"
FORMAT_VERSION = 1

# Fallback reasons (also reason codes on the novelty record).
NO_MODEL_ID = "no_model_id"
NOT_IN_REGISTRY = "model_not_in_registry"
NO_HEAD_PATH = "no_head_path"
FILE_MISSING = "centroids_missing"
MODEL_MISMATCH = "centroids_model_mismatch"
CHECKSUM_MISMATCH = "centroids_checksum_mismatch"
LOAD_FAILED = "centroids_load_failed"
DIM_MISMATCH = "centroids_dim_mismatch"
NUMPY_MISSING = "numpy_unavailable"


@dataclass
class CentroidSet:
    model_id: str
    route: str
    centroids: Any                 # np.ndarray (K, D), unit rows
    centroid_class: list[str]
    calib_quantiles: Any           # np.ndarray (Q,), sorted
    manifest: dict = field(default_factory=dict)
    sha256: str = ""
    path: str = ""

    @property
    def dim(self) -> int:
        return int(self.centroids.shape[1])

    def nearest(self, embedding: Any) -> tuple[float, int]:
        """(cosine distance to the nearest centroid, its index)."""
        import numpy as np
        e = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if e.shape[0] != self.dim:
            raise ValueError(f"embedding dim {e.shape[0]} != centroid dim {self.dim}")
        n = float(np.linalg.norm(e))
        if n == 0.0 or not np.isfinite(n):
            raise ValueError("embedding has zero or non-finite norm")
        sims = self.centroids @ (e / n)
        j = int(np.argmax(sims))
        return float(1.0 - sims[j]), j

    def ecdf(self, distance: float) -> float:
        """Fraction of calibration known reads closer to a centroid than `distance`."""
        import numpy as np
        q = self.calib_quantiles
        levels = np.linspace(0.0, 1.0, len(q))
        return float(np.clip(np.interp(distance, q, levels, left=0.0, right=1.0), 0.0, 1.0))

    def describe(self) -> dict:
        return {"centroids_version": CENTROIDS_VERSION, "centroids_sha256": self.sha256[:16],
                "centroids_k": int(self.centroids.shape[0]), "centroids_model_id": self.model_id}


def artifact_paths(head_path: str) -> tuple[str, str]:
    d = os.path.dirname(head_path)
    return os.path.join(d, MANIFEST_NAME), os.path.join(d, ARRAYS_NAME)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_centroid_set(head_path: str, model_id: str, head_checksum: str | None) -> CentroidSet:
    """Load and verify the artifact beside `head_path`. Raises CentroidError."""
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - numpy is in requirements.txt
        raise CentroidError(NUMPY_MISSING, str(exc)) from exc
    manifest_path, arrays_path = artifact_paths(head_path)
    if not (os.path.isfile(manifest_path) and os.path.isfile(arrays_path)):
        raise CentroidError(FILE_MISSING, f"no {MANIFEST_NAME}/{ARRAYS_NAME} beside {head_path}")
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError) as exc:
        raise CentroidError(LOAD_FAILED, f"{manifest_path}: {exc}") from exc
    if manifest.get("model_id") != model_id:
        raise CentroidError(MODEL_MISMATCH, f"manifest model_id {manifest.get('model_id')!r} != {model_id!r}")
    if head_checksum and manifest.get("head_checksum") and manifest["head_checksum"] != head_checksum:
        raise CentroidError(MODEL_MISMATCH, "manifest head_checksum differs from the registry checksum")
    digest = sha256_file(arrays_path)
    if manifest.get("npz_sha256") != digest:
        raise CentroidError(CHECKSUM_MISMATCH, f"{arrays_path} sha256 {digest[:16]} != manifest")
    try:
        with np.load(arrays_path, allow_pickle=False) as z:
            cents = np.asarray(z["centroids"], dtype=np.float32)
            classes = [str(c) for c in z["centroid_class"].tolist()]
            quant = np.asarray(z["calib_quantiles"], dtype=np.float32)
    except Exception as exc:
        raise CentroidError(LOAD_FAILED, f"{arrays_path}: {exc}") from exc
    if cents.ndim != 2 or cents.shape[0] == 0 or len(classes) != cents.shape[0] or quant.ndim != 1 or len(quant) < 2:
        raise CentroidError(LOAD_FAILED, f"{arrays_path}: malformed arrays")
    return CentroidSet(model_id=model_id, route=str(manifest.get("route")), centroids=cents,
                       centroid_class=classes, calib_quantiles=np.sort(quant), manifest=manifest,
                       sha256=digest, path=arrays_path)


class CentroidError(RuntimeError):
    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# resolver (cached per model_id + head path + file mtimes)
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_CACHE: dict[tuple, tuple[CentroidSet | None, str | None]] = {}


def _mtimes(head_path: str) -> tuple:
    out = []
    for p in artifact_paths(head_path):
        try:
            st = os.stat(p)
            out.append((st.st_ino, st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def centroids_for_model(model_id: str | None, registry: Any = None) -> tuple[CentroidSet | None, str | None]:
    """(CentroidSet, None) or (None, fallback reason). Never raises."""
    if not model_id:
        return None, NO_MODEL_ID
    try:
        if registry is None:
            from app.inference.registry import get_registry
            registry = get_registry()
        entry = registry.get(model_id)
    except Exception as exc:  # registry unreadable
        logger.warning("novelty centroids: registry lookup for %s failed: %r", model_id, exc)
        return None, NOT_IN_REGISTRY
    if entry is None:
        return None, NOT_IN_REGISTRY
    head_path = entry.artifact_uri
    if not head_path or not head_path.endswith((".pt", ".bin")):
        return None, NO_HEAD_PATH
    key = (model_id, head_path, entry.checksum, _mtimes(head_path))
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
        try:
            cs = load_centroid_set(head_path, model_id, entry.checksum)
            res: tuple[CentroidSet | None, str | None] = (cs, None)
            logger.info("novelty centroids for %s: %s (K=%d, sha256 %s)", model_id, cs.path,
                        cs.centroids.shape[0], cs.sha256[:16])
        except CentroidError as exc:
            logger.warning("novelty centroids unavailable for %s (%s): %s -- embedding isolation falls back "
                           "to the L2-norm proxy", model_id, exc.reason, exc.detail)
            res = (None, exc.reason)
        _CACHE[key] = res
        return res


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
