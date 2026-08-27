"""
Model loader with graceful degradation.

torch and transformers are optional runtime dependencies.  When they are not
installed the loader returns None and the predictor falls back to stub mode.

Loading rules:
  1. `artifact_uri` in the registry entry controls where weights come from.
     - None → stub mode (no weights loaded yet)
     - Local path (starts with "/" or "./" or "C:\\") → load from disk
     - HF Hub path ("org/model" format) → load via transformers.from_pretrained
  2. Models are cached in _MODEL_CACHE keyed by model_id.  The cache is
     process-global so each model is only loaded once per worker process.
  3. Security: artifact_uri values come from signed registry files on disk,
     NOT from user input.  Never allow users to supply model paths.

Supported base models (Windows-compatible, no custom Triton/FlashAttention):
  zhihan1996/DNABERT-2-117M         — DNABERT-2, BPE tokenizer, 768-dim
  InstaDeepAI/nucleotide-transformer-500m-human-ref  — NT 500M, 6-mer vocab, 1024-dim
  InstaDeepAI/nucleotide-transformer-50m-multi-species — NT 50M, 512-dim (fast)
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

from .models import ModelRegistryEntry

logger = logging.getLogger(__name__)

# DNABERT-2's custom modeling code falls back to plain PyTorch attention when
# Triton is unavailable -- but if a `triton` package is importable in this
# environment while its JIT compiler isn't (e.g. no C compiler on PATH, the
# case on this project's Windows training host), it takes the Triton path
# and crashes instead of falling back. Force the ImportError so it degrades
# the way the architecture actually intends. No-op if triton was never
# going to import here anyway. See services/worker/training/finetune.py for
# the reproduction that surfaced this.
sys.modules.setdefault("triton", None)  # type: ignore[arg-type]

# ---------------------------------------------------------------------------
# Optional torch / transformers import
# ---------------------------------------------------------------------------

try:
    import torch
    from transformers import AutoConfig, AutoModel, AutoModelForMaskedLM, AutoTokenizer
    _TORCH_AVAILABLE = True
    logger.info("torch %s available — model inference enabled", torch.__version__)
except ImportError:
    _TORCH_AVAILABLE = False
    logger.warning(
        "torch / transformers not installed — worker will run in stub mode. "
        "Install with: pip install -r services/worker/requirements-ml.txt"
    )

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_MODEL_CACHE: dict[str, tuple[Any, Any]] = {}   # model_id → (model, tokenizer)
_CACHE_LOCK = threading.Lock()

# Maximum number of models held in memory at once.
# LRU eviction is not implemented — for the MVP a single-model-per-route
# strategy keeps memory manageable on a 8 GB GPU / 16 GB RAM machine.
_MAX_CACHED = 4


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def torch_available() -> bool:
    return _TORCH_AVAILABLE


def get_or_load(entry: ModelRegistryEntry) -> tuple[Any, Any] | None:
    """
    Return (model, tokenizer) for the given registry entry, or None if:
      - torch is not installed
      - artifact_uri is None (no weights yet)
      - loading fails (with a logged warning)

    Thread-safe.
    """
    if not _TORCH_AVAILABLE:
        return None
    if not entry.is_runnable:
        logger.debug("Model %s has no artifact_uri — stub mode", entry.model_id)
        return None

    with _CACHE_LOCK:
        if entry.model_id in _MODEL_CACHE:
            return _MODEL_CACHE[entry.model_id]

        pair = _load(entry)
        if pair is not None:
            if len(_MODEL_CACHE) >= _MAX_CACHED:
                # Evict the first-inserted entry (oldest).
                oldest = next(iter(_MODEL_CACHE))
                del _MODEL_CACHE[oldest]
                logger.info("Model cache evicted: %s", oldest)
            _MODEL_CACHE[entry.model_id] = pair

        return pair


def unload(model_id: str) -> None:
    """Remove a model from the cache (frees GPU/CPU memory on next GC)."""
    with _CACHE_LOCK:
        _MODEL_CACHE.pop(model_id, None)


def clear_cache() -> None:
    with _CACHE_LOCK:
        _MODEL_CACHE.clear()


# ---------------------------------------------------------------------------
# Internal loader
# ---------------------------------------------------------------------------

def _load(entry: ModelRegistryEntry) -> tuple[Any, Any] | None:
    # The BACKBONE comes from base_model (an HF Hub ID or local model dir —
    # config.json + weights). artifact_uri is the per-route HEAD weights
    # (.pt/.bin, a bare state_dict) — see heads.get_head, which predictor.py
    # calls separately. Loading a bare state_dict here via AutoModel would
    # fail outright, so these two must never be conflated.
    uri = entry.base_model
    assert entry.artifact_uri is not None  # already checked by caller (is_runnable)

    logger.info("Loading model %s from %s ...", entry.model_id, uri)
    try:
        # Determine device.
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda":
            logger.info("  using CUDA device: %s", torch.cuda.get_device_name(0))
        else:
            logger.info("  using CPU (no CUDA device found)")

        # Resolve local vs Hub path.
        local_path = _resolve_local(uri)

        load_kwargs: dict[str, Any] = {
            # Only True when the registry entry explicitly allowlists this
            # base_model (see ModelRegistryEntry.trusted_remote_code) — e.g.
            # DNABERT-2 ships custom modeling code and needs this to load at
            # all, but that trust must never silently extend to other models.
            "trust_remote_code": entry.trusted_remote_code,
        }
        # Always load in fp32. Loading straight into fp16 on CUDA was tried
        # and reverted — DNABERT-2's custom modeling code (and likely other
        # trust_remote_code models with hand-written layers, e.g. newly-
        # initialized pooler weights that don't inherit the load dtype)
        # isn't guaranteed fp16-safe end to end, and crashes ("expected
        # scalar type Half but found Float") rather than degrading. A 117M
        # model in fp32 is a non-issue on an 8GB GPU for single-sequence
        # inference; mixed precision belongs in training (autocast), where
        # it's applied safely op-by-op instead of forced at load time.
        load_kwargs["torch_dtype"] = torch.float32

        tokenizer = AutoTokenizer.from_pretrained(local_path or uri, trust_remote_code=load_kwargs["trust_remote_code"])
        config = AutoConfig.from_pretrained(local_path or uri, trust_remote_code=load_kwargs["trust_remote_code"])
        if "AutoModel" not in getattr(config, "auto_map", {}) and getattr(config, "model_type", None) == "esm":
            # Some ESM-family repos (e.g. Nucleotide Transformer) only map
            # AutoModelForMaskedLM to their custom gated-FFN encoder class,
            # not plain AutoModel — see finetune.py for the full story on
            # why AutoModel silently resolves to the wrong (non-gated)
            # architecture here and fails to load the checkpoint weights.
            model = AutoModelForMaskedLM.from_pretrained(local_path or uri, **load_kwargs).esm
        else:
            model = AutoModel.from_pretrained(local_path or uri, **load_kwargs)
        model.eval()
        model.to(device)

        logger.info("Model %s loaded successfully (%s)", entry.model_id, device)
        return model, tokenizer

    except Exception as exc:
        logger.error("Failed to load model %s: %s", entry.model_id, exc)
        return None


def _resolve_local(uri: str) -> str | None:
    """If uri points to an existing local path, return it; else return None (HF Hub)."""
    p = Path(uri)
    if p.exists():
        return str(p)
    # Also try relative to repo root.
    repo_root = Path(__file__).parents[5]
    candidate = repo_root / uri
    if candidate.exists():
        return str(candidate)
    return None  # treat as HF Hub identifier
