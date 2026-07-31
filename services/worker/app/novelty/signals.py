"""
Individual novelty signal extractors.

Each function takes a sequence dict (as produced by _stage_infer) and returns
a float in [0.0, 1.0] where 1.0 means the strongest possible novelty evidence.

Signals defined here:
  low_model_confidence      — model confidence is low
  result_class_uncertain    — result_class indicates uncertainty
  route_model_disagreement  — router assigned one route but model is uncertain
  high_sequence_quality     — high quality sequence + low confidence = real signal
  not_contamination         — contamination already ruled out (reduces false positives)
  embedding_isolation       — [CLS] embedding far from cluster centres (Phase 14: train)

These are combined in scorer.py using a weighted sum with learned/tunable weights.
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Signal 1: Low model confidence
# ---------------------------------------------------------------------------

def signal_low_confidence(seq: dict) -> tuple[float, str]:
    """
    High signal when the model assigned low confidence to its best prediction.
    A genuinely novel sequence produces uncertain softmax outputs.
    Score = 1 - confidence (so confidence=0 → signal=1, confidence=1 → signal=0).
    """
    conf = float(seq.get("confidence", 0.0))
    # Apply a non-linear curve to emphasise the low-confidence regime.
    score = 1.0 - conf ** 0.5   # sqrt makes the curve concave — low conf hits harder
    code = "low_model_confidence" if score > 0.5 else "model_confidence_ok"
    return round(score, 4), code


# ---------------------------------------------------------------------------
# Signal 2: Result class uncertainty
# ---------------------------------------------------------------------------

_UNCERTAIN_CLASSES = frozenset({
    "unknown_needs_online_confirmation",
    "possible_novelty",
    "likely_taxonomic_group",
})

_NOVEL_CLASS_SCORE = {
    "possible_novelty": 0.90,
    "unknown_needs_online_confirmation": 0.70,
    "likely_taxonomic_group": 0.45,
    "known_species": 0.05,
    "possible_contamination": 0.00,
    "low_quality_unusable": 0.00,
}


def signal_result_class(seq: dict) -> tuple[float, str]:
    """
    Score based on the result_class assigned by inference.
    possible_novelty → high score; known_species → low score.
    """
    rc = seq.get("result_class", "unknown_needs_online_confirmation")
    score = _NOVEL_CLASS_SCORE.get(rc, 0.50)
    code = f"result_class_{rc}"
    return round(score, 4), code


# ---------------------------------------------------------------------------
# Signal 3: Route / model disagreement
# ---------------------------------------------------------------------------

def signal_route_model_disagreement(seq: dict) -> tuple[float, str]:
    """
    High signal when the router and the model disagree on taxonomic route.

    Disagreement is inferred from the label_scores dict: if the winning label
    is roughly equal to the second-best label, the model is uncertain about
    the taxonomic group — consistent with a genuinely novel sequence.
    """
    label_scores: dict[str, float] = seq.get("label_scores", {})
    if len(label_scores) < 2:
        return 0.0, "no_label_scores"

    sorted_scores = sorted(label_scores.values(), reverse=True)
    top = sorted_scores[0]
    second = sorted_scores[1]

    if top <= 0:
        return 0.0, "zero_scores"

    # Entropy of the softmax distribution as a disagreement measure.
    # High entropy = uniform distribution = strong disagreement.
    total = sum(sorted_scores)
    if total <= 0:
        return 0.0, "zero_total_scores"
    probs = [s / total for s in sorted_scores]
    entropy = -sum(p * math.log(p + 1e-10) for p in probs if p > 0)
    max_entropy = math.log(len(probs))
    normalised_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

    code = "high_label_entropy" if normalised_entropy > 0.6 else "low_label_entropy"
    return round(normalised_entropy, 4), code


# ---------------------------------------------------------------------------
# Signal 4: High sequence quality (quality × uncertainty = real signal)
# ---------------------------------------------------------------------------

def signal_high_quality(seq: dict) -> tuple[float, str]:
    """
    A high-quality sequence with uncertain predictions is more interesting than
    a low-quality sequence with uncertain predictions (which is just noise).

    Quality score = (1 - n_ratio) × (1 - has_invalid_chars) × length_adequacy.
    This signal AMPLIFIES other novelty signals — it is not novelty evidence alone.
    """
    n_ratio = float(seq.get("n_ratio", 0.0))
    has_invalid = bool(seq.get("has_invalid_chars", False))
    length = int(seq.get("length", 0))

    # N ratio penalty.
    n_penalty = 1.0 - min(n_ratio * 2, 1.0)  # doubles the penalty vs raw n_ratio

    # Invalid chars.
    invalid_penalty = 0.5 if has_invalid else 1.0

    # Length adequacy: sequences shorter than 50 bp are not reliable.
    if length >= 200:
        length_factor = 1.0
    elif length >= 50:
        length_factor = 0.5 + 0.5 * (length - 50) / 150
    else:
        length_factor = 0.0

    score = n_penalty * invalid_penalty * length_factor
    code = "high_quality_sequence" if score > 0.7 else "quality_uncertain"
    return round(score, 4), code


# ---------------------------------------------------------------------------
# Signal 5: Not contamination (rules out false-positive novelty)
# ---------------------------------------------------------------------------

def signal_not_contamination(seq: dict) -> tuple[float, str]:
    """
    Returns 1.0 when the sequence is NOT flagged as contamination.
    Returns 0.0 if contamination is suspected.

    A genuinely novel environmental sequence should not be contamination.
    This signal prevents contamination sequences from scoring high on novelty.
    """
    route = seq.get("route", "misc_unknown")
    result_class = seq.get("result_class", "")
    contamination_score = float(seq.get("contamination_score", 0.0))

    if route == "human_domestic_contamination":
        return 0.0, "route_is_contamination"
    if result_class == "possible_contamination":
        return 0.0, "result_class_contamination"
    if contamination_score >= 0.5:
        return 0.0, "contamination_flagged"

    return 1.0, "not_contamination"


# ---------------------------------------------------------------------------
# Signal 6: Embedding isolation (Phase 14 — placeholder)
# ---------------------------------------------------------------------------

def signal_embedding_isolation(seq: dict) -> tuple[float, str]:
    """
    Measures how isolated the sequence's [CLS] embedding is from the cluster
    centres of known species in the embedding space.

    Phase 14 trains cluster centres from curated sequences. Until then this
    returns 0.0 (no isolation data) so it doesn't inflate novelty scores.
    """
    embedding = seq.get("embedding")
    if embedding is None:
        return 0.0, "no_embedding"

    # TODO Phase 14: compute cosine distance to nearest cluster centre.
    # For now, signal is based on the embedding L2 norm relative to expected
    # norm for known sequences — a weak proxy for isolation.
    norm = math.sqrt(sum(x * x for x in embedding))
    typical_norm = 14.0   # rough expected norm for DNABERT-2 [CLS] embeddings
    deviation = abs(norm - typical_norm) / typical_norm
    score = min(deviation, 1.0)

    code = "embedding_isolated" if score > 0.4 else "embedding_normal"
    return round(score, 4), code
