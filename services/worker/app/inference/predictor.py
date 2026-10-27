"""
Main inference pipeline.

For each sequence:
  1. Look up the best available model in the registry for its route.
  2. If no runnable model found → return stub prediction.
  3. Load model + tokenizer (cached).
  4. Tokenize sequence at the model's training max_length (max_length.py)
     → [CLS] embedding.
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

from .heads import HeadUnavailableError, get_cls_embedding, get_head, tokenize_dna
from .loader import get_or_load, torch_available
from .max_length import resolve_max_length
from .models import (
    InferenceMode,
    ModelRegistryEntry,
    PredictionResult,
    SequenceResultClass,
    labels_for,
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
      - backbone fails to load
      - trained head weights are missing or fail to load (never a random head)
    Every stub carries stub_reason saying which of these happened.
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

    if entry is None:
        return _stub_prediction(sequence_id, route, entry, "no_model")
    if not torch_available():
        return _stub_prediction(sequence_id, route, entry, "torch_unavailable")

    pair = get_or_load(entry)
    if pair is None:
        return _stub_prediction(sequence_id, route, entry, "backbone_unavailable")

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
    reason: str | None = None,
) -> PredictionResult:
    """
    Return a stub prediction when no model is available.

    The result_class is always unknown_needs_online_confirmation so the
    human-in-the-loop review queue (Phase 9) can handle it.

    reason becomes stub_reason on the result.  When omitted it defaults to the
    legacy pair: "no_model" (no registry entry) / "no_weights" (entry present).
    """
    model_id = entry.model_id if entry else "none"
    if reason is None:
        reason = "no_model" if entry is None else "no_weights"
    logger.debug(
        "Stub inference for %s (route=%s, model=%s, reason=%s)",
        sequence_id, route, model_id, reason,
    )
    return PredictionResult(
        sequence_id=sequence_id,
        result_class=SequenceResultClass.unknown_needs_online_confirmation,
        predicted_taxon=None,
        confidence=0.0,
        model_version_used=f"{model_id}:stub_{reason}",
        inference_mode=InferenceMode.stub,
        label_scores={},
        embedding=None,
        stub_reason=reason,
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
        # Classifier head first: without trained head weights there is no
        # model prediction to make, so don't spend a backbone forward pass.
        labels = labels_for(route, entry.label_set_version, entry.label_set)
        try:
            head = get_head(
                route=route,
                model_id=entry.model_id,
                embedding_dim=entry.embedding_dim,
                head_weights_path=entry.artifact_uri if entry.artifact_uri and
                                  entry.artifact_uri.endswith((".pt", ".bin")) else None,
                labels=labels,
            )
        except HeadUnavailableError as exc:
            # Already logged (once per route) by get_head.
            return _stub_prediction(sequence_id, route, entry, exc.reason)
        if head is None:
            return _stub_prediction(sequence_id, route, entry, "no_label_set")

        # Tokenise at the window this model was trained at, read from its
        # own training record (see max_length.py), not a fixed literal.
        max_length, _ = resolve_max_length(entry)
        inputs = tokenize_dna(sequence, tokenizer, max_length=max_length)

        # Get [CLS] embedding.
        cls_emb = get_cls_embedding(model, inputs)
        if cls_emb is None:
            return _stub_prediction(sequence_id, route, entry, "no_embedding")

        import torch
        with torch.no_grad():
            logits = head(cls_emb)  # (1, num_classes)
            probs = torch.softmax(logits, dim=-1).squeeze(0).tolist()

        label_scores = dict(zip(labels, probs))

        # Determine result_class and confidence from probabilities.
        if not label_scores:
            return _stub_prediction(sequence_id, route, entry, "no_label_set")

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
            sequence_id, route, entry.model_id, exc, exc_info=True,
        )
        return _stub_prediction(sequence_id, route, entry, "inference_error")
