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
import threading
from pathlib import Path
from typing import Any

from .models import ModelRegistryEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional torch / transformers import
# ---------------------------------------------------------------------------

try:
    import torch
    from transformers import AutoModel, AutoTokenizer
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
    uri = entry.artifact_uri
    assert uri is not None  # already checked by caller

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
            "trust_remote_code": False,  # never trust remote code for security
        }
        if device == "cpu":
            load_kwargs["torch_dtype"] = torch.float32
        else:
            load_kwargs["torch_dtype"] = torch.float16

        tokenizer = AutoTokenizer.from_pretrained(local_path or uri, **load_kwargs)
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
