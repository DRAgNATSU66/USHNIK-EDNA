"""
Route-specific classifier heads.

Each route gets a lightweight linear probe on top of a DNA foundation model's
[CLS] token embedding.  The architecture is intentionally simple:
  dropout → linear → softmax

A head is only ever returned with trained weights loaded.  When head.pt is
missing or fails to load, get_head raises HeadUnavailableError instead of
handing back a randomly initialised head: a random head produces confident-
looking but meaningless probabilities, and the predictor would label them
inference_mode="model".  The predictor turns the error into a stub prediction
with stub_reason "head_missing" / "head_load_failed".

This module is torch-optional: if torch is not installed all functions
are no-ops / return None.  The predictor handles that gracefully.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .models import ROUTE_LABEL_SETS

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False


# ---------------------------------------------------------------------------
# Head architecture
# ---------------------------------------------------------------------------

if _TORCH_AVAILABLE:
    class DNAClassifierHead(nn.Module):
        """
        Linear probe for sequence-level classification on a DNA foundation model.

        Input:  [CLS] embedding tensor of shape (batch, embedding_dim)
        Output: logits tensor of shape (batch, num_classes)
        """

        def __init__(self, embedding_dim: int, num_classes: int, dropout: float = 0.1):
            super().__init__()
            self.dropout = nn.Dropout(dropout)
            self.classifier = nn.Linear(embedding_dim, num_classes)

        def forward(self, cls_embedding: "torch.Tensor") -> "torch.Tensor":
            return self.classifier(self.dropout(cls_embedding))

        @classmethod
        def from_pretrained(cls, path: str, embedding_dim: int, num_classes: int) -> "DNAClassifierHead":
            head = cls(embedding_dim, num_classes)
            state = torch.load(path, map_location="cpu", weights_only=True)
            head.load_state_dict(state)
            head.eval()
            return head

else:
    class DNAClassifierHead:  # type: ignore[no-redef]
        """Stub when torch is not available."""
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass


# ---------------------------------------------------------------------------
# Head cache and factory
# ---------------------------------------------------------------------------

_HEAD_CACHE: dict[str, Any] = {}   # (route, model_id) → head
# Remembered failures, so a missing/corrupt head.pt is logged once per process
# instead of once per sequence.  (route, model_id) → (reason, detail)
_HEAD_FAILURES: dict[str, tuple[str, str]] = {}


class HeadUnavailableError(RuntimeError):
    """
    Trained head weights for a route could not be used.

    reason is one of:
      - "head_missing"      no weights path, or the file does not exist
      - "head_load_failed"  the file exists but torch.load / load_state_dict failed
    """

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def get_head(
    route: str,
    model_id: str,
    embedding_dim: int,
    head_weights_path: str | None = None,
) -> Any | None:
    """
    Return a DNAClassifierHead for the given route with trained weights loaded.

    Returns None when torch is not available or the route has no label set.
    Raises HeadUnavailableError when the trained weights are missing or cannot
    be loaded.  It never returns a randomly initialised head.
    """
    if not _TORCH_AVAILABLE:
        return None

    cache_key = f"{route}:{model_id}"
    if cache_key in _HEAD_CACHE:
        return _HEAD_CACHE[cache_key]
    if cache_key in _HEAD_FAILURES:
        raise HeadUnavailableError(*_HEAD_FAILURES[cache_key])

    labels = ROUTE_LABEL_SETS.get(route, [])
    if not labels:
        logger.warning("No label set defined for route %r", route)
        return None

    def _fail(reason: str, detail: str, exc_info: bool = False) -> HeadUnavailableError:
        logger.warning(
            "Head weights unavailable for %s (%s): %s -- route will run in stub mode",
            cache_key, reason, detail, exc_info=exc_info,
        )
        _HEAD_FAILURES[cache_key] = (reason, detail)
        return HeadUnavailableError(reason, detail)

    if not head_weights_path:
        raise _fail("head_missing", "registry entry has no .pt/.bin head weights path")
    if not os.path.isfile(head_weights_path):
        raise _fail("head_missing", f"file not found: {head_weights_path}")

    num_classes = len(labels)
    head = DNAClassifierHead(embedding_dim=embedding_dim, num_classes=num_classes)
    try:
        state = torch.load(head_weights_path, map_location="cpu", weights_only=True)
        head.load_state_dict(state)
    except Exception as exc:
        raise _fail("head_load_failed", f"{head_weights_path}: {exc}", exc_info=True) from exc
    logger.info("Loaded head weights for %s from %s", cache_key, head_weights_path)

    head.eval()
    _HEAD_CACHE[cache_key] = head
    return head


def clear_head_cache() -> None:
    _HEAD_CACHE.clear()
    _HEAD_FAILURES.clear()


# ---------------------------------------------------------------------------
# Tokenisation helper
# ---------------------------------------------------------------------------

def tokenize_dna(
    sequence: str,
    tokenizer: Any,
    max_length: int,
) -> dict[str, Any]:
    """
    Tokenise a DNA sequence for a HuggingFace model.

    max_length has no default on purpose: it must be the window the model was
    trained at (predictor.py passes max_length.resolve_max_length's value).

    Handles both BPE tokenisers (DNABERT-2) and k-mer tokenisers
    (Nucleotide Transformer) transparently — the tokeniser already knows
    its own vocabulary.

    Returns a dict of tensors suitable for model(**inputs).
    """
    if not _TORCH_AVAILABLE:
        return {}
    import torch

    encoding = tokenizer(
        sequence,
        return_tensors="pt",
        padding="max_length",
        truncation=True,
        max_length=max_length,
    )
    return encoding


def get_cls_embedding(model: Any, inputs: dict[str, Any]) -> "torch.Tensor | None":
    """
    Run a forward pass and return the [CLS] token embedding (first token).

    Returns tensor of shape (1, embedding_dim), or None on failure.
    """
    if not _TORCH_AVAILABLE or not inputs:
        return None
    import torch

    device = next(model.parameters()).device
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)

    # Most HuggingFace models expose last_hidden_state as an attribute, but
    # some custom modeling code (e.g. DNABERT-2's MosaicBERT) returns a
    # plain tuple with no such attribute — shape (batch, seq_len, hidden)
    # either way, so outputs[0] is the correct fallback, not just a comment.
    last_hidden = outputs.last_hidden_state if hasattr(outputs, "last_hidden_state") else outputs[0]
    cls_embedding = last_hidden[:, 0, :]    # [CLS] is always the first token
    return cls_embedding.cpu().float()
