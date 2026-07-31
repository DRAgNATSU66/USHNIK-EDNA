"""
Novelty scorer — combines signals into a final novelty score.

The final score is a weighted sum of individual signal contributions.
Weights are expert-tuned for Phase 8; Phase 14 replaces them with learned
weights from labelled data.

Signal weights (must sum to 1.0):
  result_class        0.35  — strongest single signal from the model
  low_confidence      0.25  — model uncertainty
  high_quality        0.20  — amplifier: quality × uncertainty
  not_contamination   0.10  — gate: suppress if contamination likely
  label_entropy       0.07  — route/label disagreement
  embedding_isolation 0.03  — weak; grows after Phase 14 training

Novelty thresholds:
  score < 0.20   → none
  score < 0.45   → low
  score < 0.70   → medium
  score >= 0.70  → high
"""
from __future__ import annotations

from .models import AbyssRecommendation, NoveltyLevel, NoveltyScore
from .signals import (
    signal_embedding_isolation,
    signal_high_quality,
    signal_low_confidence,
    signal_not_contamination,
    signal_result_class,
    signal_route_model_disagreement,
)

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "result_class":         0.35,
    "low_confidence":       0.25,
    "high_quality":         0.20,
    "not_contamination":    0.10,
    "label_entropy":        0.07,
    "embedding_isolation":  0.03,
}
assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

# Novelty thresholds.
_THRESHOLDS = {
    NoveltyLevel.none:   (0.00, 0.20),
    NoveltyLevel.low:    (0.20, 0.45),
    NoveltyLevel.medium: (0.45, 0.70),
    NoveltyLevel.high:   (0.70, 1.01),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_sequence(seq: dict) -> NoveltyScore:
    """
    Compute a NoveltyScore for a single sequence dict.

    Input: sequence dict as produced by _stage_infer (must have keys:
      sequence_id, confidence, result_class, route, label_scores,
      n_ratio, length, has_invalid_chars, embedding [optional]).
    """
    seq_id = seq.get("sequence_id", "unknown")

    # Low-quality sequences cannot be novel — skip scoring.
    if seq.get("route") == "low_quality" or seq.get("result_class") == "low_quality_unusable":
        return NoveltyScore(
            sequence_id=seq_id,
            novelty_score=0.0,
            novelty_level=NoveltyLevel.none,
            signals={},
            reason_codes=["low_quality_skipped"],
            abyss_recommendation=AbyssRecommendation.resample,
            requires_cloud_confirmation=False,
        )

    # Compute individual signals.
    s_rc, code_rc = signal_result_class(seq)
    s_conf, code_conf = signal_low_confidence(seq)
    s_qual, code_qual = signal_high_quality(seq)
    s_not_cont, code_not_cont = signal_not_contamination(seq)
    s_entropy, code_entropy = signal_route_model_disagreement(seq)
    s_emb, code_emb = signal_embedding_isolation(seq)

    signals = {
        "result_class":         s_rc,
        "low_confidence":       s_conf,
        "high_quality":         s_qual,
        "not_contamination":    s_not_cont,
        "label_entropy":        s_entropy,
        "embedding_isolation":  s_emb,
    }

    # Weighted combination.
    # The high_quality signal multiplies the other uncertainty signals rather
    # than adding independently — this prevents low-quality noise from scoring
    # high on novelty just because the model is uncertain.
    base_uncertainty = (
        _WEIGHTS["result_class"]     * s_rc
        + _WEIGHTS["low_confidence"] * s_conf
        + _WEIGHTS["label_entropy"]  * s_entropy
        + _WEIGHTS["embedding_isolation"] * s_emb
    )
    base_weight_total = (
        _WEIGHTS["result_class"]
        + _WEIGHTS["low_confidence"]
        + _WEIGHTS["label_entropy"]
        + _WEIGHTS["embedding_isolation"]
    )
    # Normalise base uncertainty to [0, 1].
    base_normalised = base_uncertainty / base_weight_total if base_weight_total > 0 else 0.0

    # Quality amplifier: scale base uncertainty by quality score (0→0, 1→full).
    quality_amplified = base_normalised * (0.3 + 0.7 * s_qual)

    # Contamination gate: suppresses score if contamination is likely.
    gated = quality_amplified * s_not_cont

    # Full weighted score.
    novelty_score = round(gated, 4)

    # Collect reason codes — include only non-trivial codes.
    reason_codes: list[str] = []
    for code in (code_rc, code_conf, code_qual, code_not_cont, code_entropy, code_emb):
        if code and code not in reason_codes:
            reason_codes.append(code)

    # Tier.
    level = _novelty_level(novelty_score)

    # Abyss Mode recommendation.
    recommendation, needs_cloud = _abyss_recommendation(level, seq)

    return NoveltyScore(
        sequence_id=seq_id,
        novelty_score=novelty_score,
        novelty_level=level,
        signals=signals,
        reason_codes=reason_codes,
        abyss_recommendation=recommendation,
        requires_cloud_confirmation=needs_cloud,
    )


def score_batch(sequences: list[dict]) -> list[NoveltyScore]:
    """Score novelty for a list of sequence dicts."""
    return [score_sequence(seq) for seq in sequences]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _novelty_level(score: float) -> NoveltyLevel:
    for level, (lo, hi) in _THRESHOLDS.items():
        if lo <= score < hi:
            return level
    return NoveltyLevel.high


def _abyss_recommendation(
    level: NoveltyLevel,
    seq: dict,
) -> tuple[AbyssRecommendation, bool]:
    """
    Derive a field triage recommendation for Abyss Mode.

    This is NOT a scientific conclusion — it is decision-support for a
    field researcher who needs to decide what to do with a sample NOW,
    without internet connectivity.
    """
    route = seq.get("route", "misc_unknown")
    n_ratio = float(seq.get("n_ratio", 0.0))
    length = int(seq.get("length", 0))

    # Quality gate.
    if n_ratio > 0.4 or length < 50:
        return AbyssRecommendation.resample, False

    # Contamination route.
    if route == "human_domestic_contamination":
        return AbyssRecommendation.continue_sampling, False

    # Novelty tier → recommendation.
    if level == NoveltyLevel.high:
        return AbyssRecommendation.preserve_sample, True
    if level == NoveltyLevel.medium:
        return AbyssRecommendation.preserve_sample, True
    if level == NoveltyLevel.low:
        return AbyssRecommendation.continue_sampling, False

    return AbyssRecommendation.continue_sampling, False
