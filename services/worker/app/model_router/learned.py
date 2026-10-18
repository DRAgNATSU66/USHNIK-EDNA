"""
Learned k-mer route classifier: the router's first stage (roadmap B19, decision Q7).

A linear model over exact, L2-normalised k-mer counts (see kmer.py), with a
temperature fitted on the dev split so its probabilities are calibrated. It is
trained by training/train_router.py and found through the model registry: the
entry with "route": "router" whose artifact_uri points at a router.npz.

Inference needs only numpy. The .npz holds the weights, the bias and the
config (k, canonical, route order, temperature) in one file, loaded with
allow_pickle=False, and its SHA-256 must match the registry entry's checksum.

Nothing in this module fails silently. If the artifact is missing, unreadable
or does not match its checksum, load_learned_router() returns the reason, and
router.route_sequence() falls back to the heuristic with
router_method="heuristic_fallback" and that reason on every result.
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

# Registry entries for the router use this value in their "route" field.
ROUTER_REGISTRY_ROUTE = "router"

# SYNTHVEDA_ROUTER=heuristic forces the heuristic router (kill switch). Any
# other value, or unset, means "use the learned router if it loads".
ROUTER_ENV = "SYNTHVEDA_ROUTER"


class RouterLoadError(Exception):
    """The learned router could not be loaded; .reason is a short machine code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class LearnedRouterModel:
    model_id: str
    version: str
    routes: list[str]          # column order of weights / bias
    k: int
    canonical: bool
    weights: Any               # np.ndarray (4**k, n_routes) float32
    bias: Any                  # np.ndarray (n_routes,) float32
    temperature: float         # calibrated logits = logits / temperature
    min_kmers: int = 1         # fewer valid k-mers than this -> no prediction

    def logits(self, sequence: str):
        """Uncalibrated per-route scores, or None if the sequence has fewer
        than min_kmers valid k-mers (too short or all ambiguous bases)."""
        import numpy as np

        from .kmer import kmer_indices

        idx = kmer_indices(sequence, self.k, canonical=self.canonical)
        if idx.size < self.min_kmers:
            return None
        uniq, counts = np.unique(idx, return_counts=True)
        vals = counts.astype(np.float32)
        vals /= np.float32(np.sqrt(np.sum(vals * vals)))
        return vals @ self.weights[uniq] + self.bias

    def predict_proba(self, sequence: str) -> tuple[dict[str, float], dict[str, float]] | None:
        """(calibrated probabilities, raw logits) keyed by route, or None."""
        import numpy as np

        z = self.logits(sequence)
        if z is None:
            return None
        zt = z / self.temperature
        zt = zt - zt.max()
        p = np.exp(zt)
        p /= p.sum()
        probs = {r: float(v) for r, v in zip(self.routes, p)}
        raw = {r: float(v) for r, v in zip(self.routes, z)}
        return probs, raw


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_router_artifact(path: Path | str, model_id: str = "", expected_sha256: str | None = None) -> LearnedRouterModel:
    """Load a router.npz. Raises RouterLoadError with a reason code on any problem."""
    try:
        import numpy as np
    except ImportError as exc:  # worker image without numpy
        raise RouterLoadError("numpy_unavailable", str(exc)) from exc

    path = Path(path)
    if not path.is_file():
        raise RouterLoadError("artifact_missing", str(path.name))
    if expected_sha256:
        actual = sha256_file(path)
        if actual != expected_sha256:
            raise RouterLoadError(
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
        return LearnedRouterModel(
            model_id=model_id or cfg.get("model_id", ""),
            version=str(cfg["version"]),
            routes=routes,
            k=k,
            canonical=bool(cfg.get("canonical", False)),
            weights=weights,
            bias=bias,
            temperature=temperature,
            min_kmers=int(cfg.get("min_kmers", 1)),
        )
    except RouterLoadError:
        raise
    except Exception as exc:
        raise RouterLoadError("artifact_load_error", f"{type(exc).__name__}: {exc}") from exc


def load_from_registry(registry=None) -> LearnedRouterModel:
    """Find the best router entry in the model registry and load its artifact."""
    if registry is None:
        from ..inference.registry import get_registry

        registry = get_registry()
    entry = registry.best_available(ROUTER_REGISTRY_ROUTE)
    if entry is None:
        raise RouterLoadError("no_registry_entry", "no runnable registry entry with route='router'")
    return load_router_artifact(entry.artifact_uri, model_id=entry.model_id, expected_sha256=entry.checksum or None)


# ---------------------------------------------------------------------------
# Process-wide cache. Loaded once; a failure is cached too (with its reason),
# so a missing artifact costs one disk check, not one per sequence.
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state: dict[str, Any] = {"loaded": False, "model": None, "reason": None}


def get_learned_router() -> tuple[LearnedRouterModel | None, str | None]:
    """(model, None) when the learned router is usable, else (None, reason)."""
    if os.environ.get(ROUTER_ENV, "").strip().lower() == "heuristic":
        return None, "router_forced_heuristic"
    if not _state["loaded"]:
        with _lock:
            if not _state["loaded"]:
                try:
                    _state["model"] = load_from_registry()
                    _state["reason"] = None
                    m = _state["model"]
                    logger.info("Learned router loaded: %s (version %s, k=%d)", m.model_id, m.version, m.k)
                except RouterLoadError as exc:
                    _state["model"] = None
                    _state["reason"] = exc.reason
                    logger.warning("Learned router unavailable, using heuristic fallback: %s", exc)
                except Exception as exc:  # registry import/parse problems
                    _state["model"] = None
                    _state["reason"] = "router_load_error"
                    logger.warning("Learned router unavailable, using heuristic fallback: %r", exc)
                _state["loaded"] = True
    return _state["model"], _state["reason"]


def set_learned_router(model: LearnedRouterModel | None, reason: str | None = None) -> None:
    """Install a model (or a failure reason) directly. For tests and evaluation scripts."""
    with _lock:
        _state.update(loaded=True, model=model, reason=None if model is not None else (reason or "no_model_installed"))


def reset_learned_router() -> None:
    """Forget the cached model so the next call reloads from the registry."""
    with _lock:
        _state.update(loaded=False, model=None, reason=None)
