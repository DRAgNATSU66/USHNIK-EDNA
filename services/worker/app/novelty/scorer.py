"""
Novelty scorer — combines signals into a final novelty score.

  base      = sum(w_i * s_i) / sum(w_i) over the uncertainty terms present
  amplified = base * (0.3 + 0.7 * high_quality)      quality amplifier
  score     = amplified * not_contamination          contamination gate (0 or 1)

Uncertainty terms and weights (unnormalised; each present term's share is
w_i / sum of the present w_i):

  result_class            0.35   head's result class (possible_novelty high)
  low_confidence          0.25   1 - sqrt(head confidence)
  label_entropy           0.07   normalised entropy of the head's softmax
  embedding_isolation     W_EMB  nearest known-class centroid of the routed head
                                 (B5; app/novelty/centroids.py), as the ECDF of
                                 the cosine distance over held-out known reads.
                                 Without a usable centroid artifact: the old
                                 L2-norm proxy at its old weight 0.03, and the
                                 record says "embedding_proxy_<why>".
  reference_low_identity  W_REF  no reference hit at or above the family band
                                 (signals.reference_low_identity). Left out when
                                 the reference lookup did not run or was
                                 unavailable, so its absence is not novelty.

W_EMB and W_REF, and the shared NOVELTY_THRESHOLD, were chosen together on
the DEV split (training/eval_novelty_centroid.py calibrate, 2026-10-20;
criterion stated before the run: max mean over the five novelty-labelled
routes of the possible_novelty F1 of the orchestrator's final flag). The
grid's best point was W_EMB = 0, W_REF = 0, threshold 0.44 (mean F1 0.8233
vs 0.8223 for the old scorer at 0.45); the best point giving both new terms
a weight (0.50 / 0.05 @ 0.64) scored 0.8229. Neither term moves the flag
against the dataset labels, so both are served at weight 0: they are
computed and recorded in every novelty record (details) and their weights
are the one place to change. The centroid signal on its own separates
novel from known reads far better than the proxy did (dev AUROC 0.961 vs
0.879; held-out TEST 0.959 vs 0.877). On TEST the served flag vs the old
one: mean F1 0.7964 vs 0.7958 (+7 flags, 4 true; paired bootstrap 95 % CI
of the difference [-0.0012, +0.0027]); no dev-fixed nonzero weighting did
measurably better. docs/ml/results/novelty_centroid_2026-10-27.{json,md}.
With no centroid artifact and no reference evidence the score is exactly
the pre-B5 one (0.35/0.25/0.07/0.03).

high_quality and not_contamination are not weights: they multiply.

Novelty levels:
  score < 0.20   → none
  score < NOVELTY_THRESHOLD (app/config.py) → low
  score < 0.70   → medium
  score >= 0.70  → high
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ..config import NOVELTY_THRESHOLD
from .models import AbyssRecommendation, NoveltyLevel, NoveltyScore
from .signals import (
    METHOD_CENTROID,
    METHOD_PROXY,
    embedding_isolation,
    reference_low_identity,
    signal_high_quality,
    signal_low_confidence,
    signal_not_contamination,
    signal_result_class,
    signal_route_model_disagreement,
)

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

# Pre-B5 weight of the L2-norm proxy; used only when it is the fallback.
LEGACY_EMBEDDING_WEIGHT = 0.03

WEIGHTS: dict[str, float] = {
    "result_class":           0.35,
    "low_confidence":         0.25,
    "label_entropy":          0.07,
    "embedding_isolation":    0.0,    # W_EMB: dev-calibrated to 0 (module docstring)
    "reference_low_identity": 0.0,    # W_REF: dev-calibrated to 0 (module docstring)
}

# Novelty thresholds. The low/medium boundary is the shared possible-novelty
# cutoff, so "flagged as possible novelty" and "level >= medium" agree.
_THRESHOLDS = {
    NoveltyLevel.none:   (0.00, 0.20),
    NoveltyLevel.low:    (0.20, NOVELTY_THRESHOLD),
    NoveltyLevel.medium: (NOVELTY_THRESHOLD, 0.70),
    NoveltyLevel.high:   (0.70, 1.01),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _reference_bands(settings: Any) -> tuple[float, float]:
    if settings is None:
        from ..config import get_worker_settings
        settings = get_worker_settings()
    return float(settings.reference_family_identity), float(settings.reference_search_min_identity)


def score_sequence(seq: dict, *, weights: Mapping[str, float] | None = None, settings: Any = None,
                   resolver: Callable[[str | None], tuple[Any, str | None]] | None = None) -> NoveltyScore:
    """
    Compute a NoveltyScore for a single sequence dict.

    Input: sequence dict as produced by _stage_infer / the orchestrator's
    novelty context (keys: sequence_id, confidence, result_class, route,
    label_scores, n_ratio, length, has_invalid_chars; optional: embedding,
    model_version_used (selects the head's centroid artifact), reference
    (the route's reference EvidenceRecord.to_dict()), contamination_score).

    weights / settings / resolver are for evaluation and tests; the
    defaults are the served configuration.
    """
    seq_id = seq.get("sequence_id", "unknown")
    w = dict(WEIGHTS if weights is None else weights)

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
    s_emb, code_emb, emb_detail = embedding_isolation(seq, resolver=resolver)
    family, floor = _reference_bands(settings)
    s_ref, code_ref, ref_detail = reference_low_identity(seq, family, floor)

    signals = {
        "result_class":         s_rc,
        "low_confidence":       s_conf,
        "high_quality":         s_qual,
        "not_contamination":    s_not_cont,
        "label_entropy":        s_entropy,
        "embedding_isolation":  s_emb,
    }
    if s_ref is not None:
        signals["reference_low_identity"] = s_ref

    # Weighted mean of the uncertainty terms that are present.
    emb_w = w["embedding_isolation"] if emb_detail.get("method") == METHOD_CENTROID else LEGACY_EMBEDDING_WEIGHT
    terms = [
        (w["result_class"], s_rc),
        (w["low_confidence"], s_conf),
        (w["label_entropy"], s_entropy),
        (emb_w, s_emb),
    ]
    if s_ref is not None:
        terms.append((w["reference_low_identity"], s_ref))
    total_w = sum(wi for wi, _ in terms)
    base_normalised = sum(wi * si for wi, si in terms) / total_w if total_w > 0 else 0.0

    # Quality amplifier: scale base uncertainty by quality score (0→0, 1→full).
    quality_amplified = base_normalised * (0.3 + 0.7 * s_qual)

    # Contamination gate: suppresses score if contamination is likely.
    gated = quality_amplified * s_not_cont

    novelty_score = round(gated, 4)

    # Reason codes — include only non-trivial codes.
    codes = [code_rc, code_conf, code_qual, code_not_cont, code_entropy, code_emb]
    if emb_detail.get("method") == METHOD_PROXY:
        codes.append(f"embedding_proxy_{emb_detail.get('fallback_reason') or 'fallback'}")
    codes.append(code_ref)
    reason_codes: list[str] = []
    for code in codes:
        if code and code not in reason_codes:
            reason_codes.append(code)

    level = _novelty_level(novelty_score)
    recommendation, needs_cloud = _abyss_recommendation(level, seq)

    return NoveltyScore(
        sequence_id=seq_id,
        novelty_score=novelty_score,
        novelty_level=level,
        signals=signals,
        reason_codes=reason_codes,
        abyss_recommendation=recommendation,
        requires_cloud_confirmation=needs_cloud,
        details={
            "embedding_isolation": {**emb_detail, "weight": emb_w},
            "reference_low_identity": {**ref_detail,
                                       "weight": w["reference_low_identity"] if s_ref is not None else 0.0},
        },
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
