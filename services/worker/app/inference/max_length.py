"""
Tokenisation window (max_length) a route head is served with.

A head only ever saw [CLS] embeddings of sequences tokenised at its training
max_length (training/finetune.py --max-length, default 256). Inference used to
hard-code 512 for every head (QNA-022 open issue), so any sequence longer than
the training window was embedded from tokens the head was never trained on.
Each model is now served at the max_length its own training record names.

Resolution order -- the first positive integer found wins:
  1. "registry"            entry.metrics["max_length"] in models/registry/*.json
                           (written for the v2 heads from finetune's run_info).
  2. "checkpoint_metrics"  metrics.json beside the head weights (artifact_uri's
                           directory); finetune.save_checkpoint writes
                           max_length there with the rest of run_info.
  3. "tokenizer_json"      truncation.max_length in the backbone directory's
                           tokenizer.json. A fast tokenizer saves the truncation
                           it was last called with; the v1 checkpoints (trained
                           2026-08-03, before finetune.py recorded max_length
                           in metrics.json) carry 256 there. Newer
                           transformers saves null, so v2 relies on 1/2.
  4. "default"             WorkerSettings.inference_default_max_length.

Results are cached per (model_id, artifact_uri, base_model), so the files are
read once per model per process, not once per sequence.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from ..config import get_worker_settings
from .models import ModelRegistryEntry

logger = logging.getLogger(__name__)

# Source labels, in resolution order.
SOURCE_REGISTRY = "registry"
SOURCE_CHECKPOINT_METRICS = "checkpoint_metrics"
SOURCE_TOKENIZER_JSON = "tokenizer_json"
SOURCE_DEFAULT = "default"

_CACHE: dict[tuple[str, str | None, str], tuple[int, str]] = {}


def _as_max_length(value: Any) -> int | None:
    """A usable max_length is a positive int (bool is an int subclass: reject)."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _read_json(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s for max_length: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _from_checkpoint_metrics(entry: ModelRegistryEntry) -> int | None:
    if not entry.artifact_uri:
        return None
    data = _read_json(os.path.join(os.path.dirname(entry.artifact_uri), "metrics.json"))
    return _as_max_length(data.get("max_length")) if data else None


def _from_tokenizer_json(entry: ModelRegistryEntry) -> int | None:
    # Only a local backbone directory has a tokenizer.json to read; a Hub id
    # resolves to nothing here and falls through to the default.
    if not entry.base_model or not os.path.isdir(entry.base_model):
        return None
    data = _read_json(os.path.join(entry.base_model, "tokenizer.json"))
    truncation = data.get("truncation") if data else None
    return _as_max_length(truncation.get("max_length")) if isinstance(truncation, dict) else None


def resolve_max_length(entry: ModelRegistryEntry) -> tuple[int, str]:
    """Return (max_length, source) for the model a registry entry describes."""
    key = (entry.model_id, entry.artifact_uri, entry.base_model)
    if key in _CACHE:
        return _CACHE[key]

    registry_value = (entry.metrics or {}).get("max_length")
    found = _as_max_length(registry_value)
    if found is not None:
        result = (found, SOURCE_REGISTRY)
    else:
        if registry_value is not None:
            logger.warning(
                "Registry entry %s has an unusable metrics.max_length %r; ignoring it",
                entry.model_id, registry_value,
            )
        found = _from_checkpoint_metrics(entry)
        if found is not None:
            result = (found, SOURCE_CHECKPOINT_METRICS)
        else:
            found = _from_tokenizer_json(entry)
            if found is not None:
                result = (found, SOURCE_TOKENIZER_JSON)
            else:
                result = (get_worker_settings().inference_default_max_length, SOURCE_DEFAULT)

    level = logging.WARNING if result[1] == SOURCE_DEFAULT else logging.INFO
    logger.log(
        level, "Model %s tokenises at max_length=%d (source: %s)",
        entry.model_id, result[0], result[1],
    )
    _CACHE[key] = result
    return result


def clear_max_length_cache() -> None:
    _CACHE.clear()
