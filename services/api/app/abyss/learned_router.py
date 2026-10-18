"""
Offline learned router for Abyss Mode (B25).

Abyss used to import the worker's ``app.model_router``. The API's own ``app``
package is already loaded under that name, so the import raised
ModuleNotFoundError and every Abyss result fell back to GC-only routing. The
API Docker image does not contain the worker code at all, so no import-path
trick would fix it in deployment either.

This module is a minimal, inference-only copy of the worker's learned k-mer
router (services/worker/app/model_router/learned.py + kmer.py):

  * the same registry entry (``"route": "router"``, selected with the API's
    mirror of ModelRegistry.best_available in app/models/router.py),
  * the same ``router.npz`` artifact, SHA-256-checked against the entry and
    opened with ``allow_pickle=False``,
  * the same features (exact k-mer counts, non-ACGT windows skipped,
    L2-normalised), logits ``x·W + b``, temperature and softmax.

tests/test_abyss_learned_router.py loads the worker's own learned.py/kmer.py by
file path and checks that both produce the same probabilities, so the copy
cannot drift silently.

Abyss is the offline/expedition mode, so this module never touches the
network: only ``data:<path>`` URIs (resolved against the data root) and plain
local paths are loaded. Anything else (a Hub id, a URL) is refused with
``artifact_not_local``. Inference needs numpy and nothing else.

Nothing here fails silently. ``get_router()`` returns either the model or the
reason it is unavailable; analysis.py then uses GC-only routing and writes
``router_method`` / ``router_fallback_reason`` onto every result.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Registry entries for the router use this value in their "route" field
# (same constant as the worker's learned.ROUTER_REGISTRY_ROUTE).
ROUTER_REGISTRY_ROUTE = "router"

# Same kill switch as the worker: SYNTHVEDA_ROUTER=heuristic skips the learned
# router. Abyss has no heuristic stage, so it means "GC-only".
ROUTER_ENV = "SYNTHVEDA_ROUTER"
FORCED_REASON = "router_forced_heuristic"

DATA_URI_PREFIX = "data:"


class RouterUnavailable(Exception):
    """The learned router cannot be used; .reason is a short machine code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class AbyssRouterModel:
    model_id: str
    version: str
    routes: list[str]      # column order of weights / bias
    k: int
    canonical: bool
    weights: Any           # np.ndarray (4**k, n_routes) float32
    bias: Any              # np.ndarray (n_routes,) float32
    temperature: float     # calibrated logits = logits / temperature
    min_kmers: int = 1
    sha256: str = ""
    artifact_path: str = ""   # local file that was loaded
    artifact_uri: str = ""    # registry value, e.g. "data:checkpoints/router/v1/router.npz"

    def predict_proba(self, sequence: str) -> dict[str, float] | None:
        """Calibrated per-route probabilities, or None when the sequence has
        fewer than min_kmers valid k-mers (all windows contain non-ACGT)."""
        import numpy as np

        idx = kmer_indices(sequence, self.k, canonical=self.canonical)
        if idx.size < self.min_kmers:
            return None
        uniq, counts = np.unique(idx, return_counts=True)
        vals = counts.astype(np.float32)
        vals /= np.float32(np.sqrt(np.sum(vals * vals)))
        z = vals @ self.weights[uniq] + self.bias
        zt = z / self.temperature
        zt = zt - zt.max()
        p = np.exp(zt)
        p /= p.sum()
        return {r: float(v) for r, v in zip(self.routes, p)}


# ---------------------------------------------------------------------------
# Features: identical to services/worker/app/model_router/kmer.py
# ---------------------------------------------------------------------------

_CODE = None  # ASCII -> base code table, built on first use (numpy import)


def _code_table():
    global _CODE
    if _CODE is None:
        import numpy as np

        table = np.full(256, -1, dtype=np.int8)
        for ch, v in (("A", 0), ("C", 1), ("G", 2), ("T", 3), ("U", 3)):
            table[ord(ch)] = v
            table[ord(ch.lower())] = v
        _CODE = table
    return _CODE


def kmer_indices(sequence: str, k: int, canonical: bool = False):
    """Base-4 index of every valid k-mer window (int64 array). Windows with a
    non-ACGT/U character are dropped."""
    import numpy as np

    if k < 1 or k > 12:
        raise ValueError(f"k must be in 1..12, got {k}")
    raw = np.frombuffer(sequence.encode("ascii", errors="replace"), dtype=np.uint8)
    if raw.size < k:
        return np.empty(0, dtype=np.int64)
    codes = _code_table()[raw].astype(np.int64)
    windows = np.lib.stride_tricks.sliding_window_view(codes, k)
    valid = (windows >= 0).all(axis=1)
    if not valid.any():
        return np.empty(0, dtype=np.int64)
    windows = windows[valid]
    powers = 4 ** np.arange(k - 1, -1, -1, dtype=np.int64)
    fwd = windows @ powers
    if not canonical:
        return fwd
    rev = (3 - windows) @ powers[::-1]
    return np.minimum(fwd, rev)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_router_artifact(path: Path | str, model_id: str = "", expected_sha256: str | None = None) -> AbyssRouterModel:
    """Load a router.npz. Raises RouterUnavailable with a reason code on any problem."""
    try:
        import numpy as np
    except ImportError as exc:
        raise RouterUnavailable("numpy_unavailable", str(exc)) from exc

    path = Path(path)
    if not path.is_file():
        raise RouterUnavailable("artifact_missing", str(path))
    actual = _sha256_file(path)
    if expected_sha256 and actual != expected_sha256:
        raise RouterUnavailable(
            "checksum_mismatch", f"{path.name}: expected {expected_sha256[:12]}, got {actual[:12]}"
        )
    try:
        with np.load(path, allow_pickle=False) as z:
            cfg = json.loads(str(z["config_json"]))
            weights = np.ascontiguousarray(z["weights"], dtype=np.float32)
            bias = np.asarray(z["bias"], dtype=np.float32)
        routes = list(cfg["routes"])
        k = int(cfg["k"])
        if weights.shape != (4 ** k, len(routes)) or bias.shape != (len(routes),):
            raise ValueError(f"weights {weights.shape} / bias {bias.shape} do not match k={k}, routes={len(routes)}")
        temperature = float(cfg.get("temperature", 1.0))
        if not temperature > 0:
            raise ValueError(f"temperature must be > 0, got {temperature}")
        return AbyssRouterModel(
            model_id=model_id or cfg.get("model_id", ""),
            version=str(cfg["version"]),
            routes=routes,
            k=k,
            canonical=bool(cfg.get("canonical", False)),
            weights=weights,
            bias=bias,
            temperature=temperature,
            min_kmers=int(cfg.get("min_kmers", 1)),
            sha256=actual,
            artifact_path=str(path),
        )
    except Exception as exc:
        raise RouterUnavailable("artifact_load_error", f"{type(exc).__name__}: {exc}") from exc


def _registry_dir() -> Path:
    from ..models.router import REGISTRY_DIR

    return REGISTRY_DIR


def _data_root() -> Path:
    from ..models.router import _resolve_data_root

    return _resolve_data_root()


def local_artifact_path(uri: str, data_root: Path) -> Path:
    """Resolve a registry artifact_uri to a local file, or refuse.

    Offline mode never downloads: only "data:<relative path>" and an existing
    local path are accepted.
    """
    if uri.startswith(DATA_URI_PREFIX):
        return data_root / uri[len(DATA_URI_PREFIX):]
    p = Path(uri)
    if p.is_absolute() and p.exists():
        return p
    raise RouterUnavailable("artifact_not_local", uri)


def load_from_registry() -> AbyssRouterModel:
    """Find the router entry the worker would pick and load its artifact."""
    from ..models.router import _load_registry, _select_entry

    parsed, _errors = _load_registry(_registry_dir())
    entry = _select_entry(ROUTER_REGISTRY_ROUTE, [e for _f, e in parsed])
    if entry is None:
        raise RouterUnavailable("no_registry_entry", "no runnable registry entry with route='router'")
    path = local_artifact_path(entry["artifact_uri"], _data_root())
    model = load_router_artifact(path, model_id=entry["model_id"], expected_sha256=entry.get("checksum") or None)
    model.artifact_uri = entry["artifact_uri"]
    return model


# ---------------------------------------------------------------------------
# Process-wide cache: loaded once, failures cached with their reason.
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state: dict[str, Any] = {"loaded": False, "model": None, "reason": None, "detail": None}


def get_router() -> tuple[AbyssRouterModel | None, str | None, str | None]:
    """(model, None, None) when the learned router is usable, else (None, reason, detail)."""
    if os.environ.get(ROUTER_ENV, "").strip().lower() == "heuristic":
        return None, FORCED_REASON, f"{ROUTER_ENV}=heuristic"
    if not _state["loaded"]:
        with _lock:
            if not _state["loaded"]:
                try:
                    m = load_from_registry()
                    _state.update(model=m, reason=None, detail=None)
                    logger.info(
                        "Abyss learned router loaded: %s (version %s, k=%d, sha256 %s)",
                        m.model_id, m.version, m.k, m.sha256[:12],
                    )
                except RouterUnavailable as exc:
                    _state.update(model=None, reason=exc.reason, detail=exc.detail)
                    logger.warning("Abyss learned router unavailable, using GC-only routing: %s", exc)
                except Exception as exc:  # registry read/parse problems
                    _state.update(model=None, reason="router_load_error", detail=f"{type(exc).__name__}: {exc}")
                    logger.warning("Abyss learned router unavailable, using GC-only routing: %r", exc)
                _state["loaded"] = True
    return _state["model"], _state["reason"], _state["detail"]


def set_router(model: AbyssRouterModel | None, reason: str | None = None, detail: str | None = None) -> None:
    """Install a model (or a failure reason) directly. For tests."""
    with _lock:
        _state.update(
            loaded=True,
            model=model,
            reason=None if model is not None else (reason or "no_model_installed"),
            detail=None if model is not None else detail,
        )


def reset_router() -> None:
    """Forget the cached model so the next call reloads from the registry."""
    with _lock:
        _state.update(loaded=False, model=None, reason=None, detail=None)
