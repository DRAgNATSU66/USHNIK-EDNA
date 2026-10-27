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
  embedding_isolation       — [CLS] embedding far from the routed head's known-class
                              centroids (B5; old L2-norm proxy only as a fallback)
  reference_low_identity    — no reference hit at or above the family band (B5)

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
# Signal 6: Embedding isolation (B5: nearest-centroid cosine distance)
# ---------------------------------------------------------------------------

# Legacy proxy (pre-B5): L2 norm of the [CLS] embedding vs a hardcoded
# "typical" norm. Kept only as the fallback when the routed head has no
# usable centroid artifact (app/novelty/centroids.py); the novelty record
# then says so (method "norm_proxy" + reason code "embedding_proxy_<why>").
LEGACY_TYPICAL_NORM = 14.0   # rough expected norm for DNABERT-2 [CLS] embeddings

# A read whose nearest-centroid distance is beyond this share of the known
# calibration reads gets the "embedding_isolated" reason code. Display only:
# the score uses the continuous value.
EMBEDDING_ISOLATED_ECDF = 0.95

METHOD_CENTROID = "centroid_cosine"
METHOD_PROXY = "norm_proxy"
METHOD_NONE = "none"


def _norm_proxy(embedding) -> float:
    norm = math.sqrt(sum(float(x) * float(x) for x in embedding))
    deviation = abs(norm - LEGACY_TYPICAL_NORM) / LEGACY_TYPICAL_NORM
    return min(deviation, 1.0)


def embedding_isolation(seq: dict, resolver=None) -> tuple[float, str, dict]:
    """
    How far the read's [CLS] embedding sits from the known reads of the head
    that produced it: (score in [0, 1], reason code, detail).

    With the head's centroid artifact (seq["model_version_used"] names the
    head): cosine distance to the nearest known-class centroid, mapped
    through the empirical CDF of the same distance on held-out known
    training reads (CentroidSet.ecdf). Without one: the old L2-norm proxy,
    with detail["method"] = "norm_proxy" and the fallback reason.
    """
    embedding = seq.get("embedding")
    if embedding is None:
        return 0.0, "no_embedding", {"method": METHOD_NONE}

    if resolver is None:
        from .centroids import centroids_for_model as resolver
    cs, why = resolver(seq.get("model_version_used"))
    fallback_detail = None
    if cs is not None:
        try:
            distance, j = cs.nearest(embedding)
        except ValueError as exc:
            from .centroids import DIM_MISMATCH
            why, fallback_detail = DIM_MISMATCH, str(exc)[:200]
        else:
            score = cs.ecdf(distance)
            code = "embedding_isolated" if score >= EMBEDDING_ISOLATED_ECDF else "embedding_near_known"
            detail = {"method": METHOD_CENTROID, "cosine_distance": round(distance, 5),
                      "nearest_centroid": j, "nearest_class": cs.centroid_class[j],
                      "ecdf": round(score, 4), **cs.describe()}
            return round(score, 4), code, detail

    score = round(_norm_proxy(embedding), 4)
    code = "embedding_isolated" if score > 0.4 else "embedding_normal"
    detail = {"method": METHOD_PROXY, "fallback_reason": why, "typical_norm": LEGACY_TYPICAL_NORM}
    if fallback_detail:
        detail["fallback_detail"] = fallback_detail
    return score, code, detail


def signal_embedding_isolation(seq: dict) -> tuple[float, str]:
    """(score, code) form of embedding_isolation(), like the other signals."""
    score, code, _ = embedding_isolation(seq)
    return score, code


# ---------------------------------------------------------------------------
# Signal 7: Reference low identity (B5)
# ---------------------------------------------------------------------------

def reference_low_identity(seq: dict, family_identity: float, search_floor: float
                           ) -> tuple[float | None, str, dict]:
    """
    Novelty evidence from the reference lookup on the routed head's route:
    the read has no eligible hit (over the coverage floor) at or above the
    family band (REFERENCE_FAMILY_IDENTITY, provisional 90 %).

      no eligible hit (status no_hit)          -> 1.0
      best eligible identity id < family band  -> (family - id) / (family - search_floor),
                                                  clipped to [0, 1]. The search reports no hit
                                                  below REFERENCE_SEARCH_MIN_IDENTITY (80 %), so
                                                  the term ramps linearly across 90 -> 80 %.
      best eligible identity >= family band    -> 0.0
      lookup not run / unavailable / skipped   -> None: the term is left out of the score
                                                  (a missing DB is not evidence of novelty)

    seq["reference"] is the route's reference EvidenceRecord.to_dict()
    (status + compact payload; app/evidence/providers.ReferenceEvidenceProvider).
    A strong hit is the combiner's job, not this term's: it gates the final
    score to 0 (novelty_suppressed_by_reference) or keeps the flag with a
    downgrade (app/orchestrator/combiner.py).
    """
    rec = seq.get("reference")
    if not rec or rec.get("status") != "ok":
        return None, "reference_unavailable", {"evidence_status": (rec or {}).get("status") or "not_run"}
    p = rec.get("payload") or {}
    status = p.get("status")
    ident = p.get("identity")
    detail = {"reference_status": status, "identity": ident, "family_identity": family_identity,
              "search_floor": search_floor}
    if status == "no_hit" or ident is None:
        return 1.0, "reference_no_hit", detail
    ident = float(ident)
    if ident >= family_identity:
        return 0.0, "reference_hit_at_or_above_family", detail
    span = max(family_identity - search_floor, 1e-6)
    score = max(0.0, min(1.0, (family_identity - ident) / span))
    return round(score, 4), "reference_low_identity", detail


