"""
Main inference pipeline.

For each sequence:
  1. Look up the best available model in the registry for its route.
  2. If no runnable model found → return stub prediction.
  3. Load model + tokenizer (cached).
  4. Tokenize sequence → [CLS] embedding.
  5. Run classifier head → softmax probabilities.
  6. Return PredictionResult with confidence, result_class, embedding.

Confidence thresholds (from registry entry or defaults below) determine
result_class when the model is uncertain:
  top-1 probability >= high_threshold  → result class = top label
  top-1 probability >= low_threshold   → result class = "likely_taxonomic_group"
  top-1 probability <  low_threshold   → result class = "unknown_needs_online_confirmation"
"""
from __future__ import annotations

import logging
import math
from typing import Any

from .heads import get_cls_embedding, get_head, tokenize_dna
from .loader import get_or_load, torch_available
from .models import (
    ROUTE_LABEL_SETS,
    InferenceMode,
    ModelRegistryEntry,
    PredictionResult,
    SequenceResultClass,
)
from .registry import get_registry

logger = logging.getLogger(__name__)

# Default confidence thresholds (override per model in registry thresholds dict).
_HIGH_CONF = 0.75
_LOW_CONF = 0.40


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_inference(
    sequence_id: str,
    sequence: str,
    route: str,
    route_confidence: float = 0.0,
) -> PredictionResult:
    """
    Run inference for a single sequence and return a PredictionResult.

    Falls back to stub mode when:
      - route is "low_quality"
      - torch is not installed
      - no runnable model exists for the route
      - model fails to load
    """
    # Low-quality sequences are not sent to inference.
    if route == "low_quality":
        return PredictionResult(
            sequence_id=sequence_id,
            result_class=SequenceResultClass.low_quality_unusable,
            predicted_taxon=None,
            confidence=1.0,
            model_version_used="low_quality",
            inference_mode=InferenceMode.low_quality,
        )

    registry = get_registry()
    entry = registry.best_available(route)

    if entry is None or not torch_available():
        return _stub_prediction(sequence_id, route, entry)

    pair = get_or_load(entry)
    if pair is None:
        return _stub_prediction(sequence_id, route, entry)

    model, tokenizer = pair
    return _run_model(sequence_id, sequence, route, entry, model, tokenizer)


def run_inference_batch(sequences: list[dict]) -> list[PredictionResult]:
    """
    Run inference for a list of sequence dicts (output of _stage_route).

    Each dict must have: sequence_id, sequence, route.
    Returns a parallel list of PredictionResult objects.
    """
    return [
        run_inference(
            sequence_id=s["sequence_id"],
            sequence=s["sequence"],
            route=s.get("route", "misc_unknown"),
            route_confidence=s.get("route_confidence", 0.0),
        )
        for s in sequences
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stub_prediction(
    sequence_id: str,
    route: str,
    entry: ModelRegistryEntry | None,
) -> PredictionResult:
    """
    Return a stub prediction when no model is available.

    The result_class is always unknown_needs_online_confirmation so the
    human-in-the-loop review queue (Phase 9) can handle it.
    """
    model_id = entry.model_id if entry else "none"
    reason = "stub_no_model" if entry is None else "stub_no_weights"
    logger.debug(
        "Stub inference for %s (route=%s, model=%s, reason=%s)",
        sequence_id, route, model_id, reason,
    )
    return PredictionResult(
        sequence_id=sequence_id,
        result_class=SequenceResultClass.unknown_needs_online_confirmation,
        predicted_taxon=None,
        confidence=0.0,
        model_version_used=f"{model_id}:{reason}",
        inference_mode=InferenceMode.stub,
        label_scores={},
        embedding=None,
    )


def _run_model(
    sequence_id: str,
    sequence: str,
    route: str,
    entry: ModelRegistryEntry,
    model: Any,
    tokenizer: Any,
) -> PredictionResult:
    """Run the actual model + classifier head pipeline."""
    try:
        # Tokenise.
        inputs = tokenize_dna(sequence, tokenizer, max_length=512)

        # Get [CLS] embedding.
        cls_emb = get_cls_embedding(model, inputs)
        if cls_emb is None:
            return _stub_prediction(sequence_id, route, entry)

        # Run classifier head.
        head = get_head(
            route=route,
            model_id=entry.model_id,
            embedding_dim=entry.embedding_dim,
            head_weights_path=entry.artifact_uri if entry.artifact_uri and
                              entry.artifact_uri.endswith((".pt", ".bin")) else None,
        )
        if head is None:
            return _stub_prediction(sequence_id, route, entry)

        import torch
        with torch.no_grad():
            logits = head(cls_emb)  # (1, num_classes)
            probs = torch.softmax(logits, dim=-1).squeeze(0).tolist()

        labels = ROUTE_LABEL_SETS.get(route, [])
        label_scores = dict(zip(labels, probs))

        # Determine result_class and confidence from probabilities.
        if not label_scores:
            return _stub_prediction(sequence_id, route, entry)

        best_label = max(label_scores, key=label_scores.__getitem__)
        best_prob = label_scores[best_label]

        thresholds = entry.thresholds
        high_threshold = thresholds.get("high_confidence", _HIGH_CONF)
        low_threshold = thresholds.get("low_confidence", _LOW_CONF)

        if best_prob >= high_threshold:
            result_class = best_label
        elif best_prob >= low_threshold:
            # Uncertain — step back to a softer classification.
            if best_label in (
                SequenceResultClass.known_species,
                SequenceResultClass.possible_novelty,
            ):
                result_class = SequenceResultClass.likely_taxonomic_group
            else:
                result_class = best_label
        else:
            result_class = SequenceResultClass.unknown_needs_online_confirmation

        embedding = cls_emb.squeeze(0).tolist()

        return PredictionResult(
            sequence_id=sequence_id,
            result_class=result_class,
            predicted_taxon=None,  # Phase 14: taxonomy lookup from label index
            confidence=round(best_prob, 4),
            model_version_used=entry.model_id,
            inference_mode=InferenceMode.model,
            label_scores=label_scores,
            embedding=embedding,
        )

    except Exception as exc:
        logger.error(
            "Inference failed for %s (route=%s, model=%s): %s",
            sequence_id, route, entry.model_id, exc,
        )
        return _stub_prediction(sequence_id, route, entry)
