"""
Taxonomic router — assigns each sequence a route and confidence score.

Algorithm (three-stage evidence combination):
  1. Low-quality gate: sequences that fail QC thresholds → route = low_quality.
  2. Marker gene signal: if one or more strong marker patterns match,
     assign a large score boost to the associated route.
  3. Biophysical scoring: for each viable route, compute a likelihood score
     from GC ratio, CpG O/E, length compatibility, and habitat metadata.
  4. Combine marker + biophysical scores, normalise to probabilities,
     apply confidence-tier thresholds.

Confidence tiers (see models.ConfidenceTier):
  high   (≥ 0.70)  → downstream inference uses specialist model only
  medium (0.40–0.70)→ specialist + top fallback model in parallel
  low    (< 0.40)  → general / misc model + reference sequence search

This is a heuristic-rules model for Phase 6.  Phase 7 replaces
biophysical_score() with a DNA foundation model embedding comparison.
"""
from __future__ import annotations

import math

from .features import extract_features
from .markers import marker_route_scores
from .models import ConfidenceTier, RouteResult, RouterInput, TaxonomicRoute
from .reference import LOW_QUALITY_THRESHOLDS, ROUTE_PROFILES

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route_sequence(inp: RouterInput) -> RouteResult:
    """Route a single sequence and return a RouteResult."""
    reasons: list[str] = []

    # 1. Low-quality gate.
    if _is_low_quality(inp, reasons):
        return RouteResult(
            sequence_id=inp.sequence_id,
            route=TaxonomicRoute.low_quality,
            route_confidence=1.0,
            confidence_tier=ConfidenceTier.high,
            fallback_routes=[],
            reason_codes=reasons,
            raw_scores={"low_quality": 1.0},
        )

    # 2. Extract biophysical features.
    features = extract_features(inp.sequence, gc_ratio=inp.gc_ratio, n_ratio=inp.n_ratio)

    # 3. Marker gene detection.
    marker_hits = marker_route_scores(inp.sequence)
    if marker_hits:
        reasons.append("marker_detected")
        for route, (conf, names) in marker_hits.items():
            reasons.extend(f"marker_{n}" for n in names)

    # 4. Compute per-route raw scores.
    raw_scores: dict[str, float] = {}
    for route_str, profile in ROUTE_PROFILES.items():
        score = profile.base_prior

        # Habitat boost.
        if inp.habitat and inp.habitat.lower() in profile.habitat_boost:
            boost = profile.habitat_boost[inp.habitat.lower()]
            score *= boost
            if boost > 1.0:
                reasons.append(f"habitat_boost_{route_str}")

        # GC ratio Gaussian likelihood.
        gc_score = _gaussian(features.gc_ratio, profile.gc_mean, profile.gc_std)
        score *= max(gc_score, 0.01)

        # CpG O/E score (only meaningful for eukaryotes; bacteria have near-zero).
        cpg_score = _gaussian(features.cpg_oe, profile.cpg_oe_mean, profile.cpg_oe_std)
        score *= max(cpg_score, 0.01)

        # Length compatibility.
        length_score = _length_score(
            features.length,
            profile.typical_length_min,
            profile.typical_length_max,
        )
        score *= length_score

        # Marker gene boost (dominant signal when present).
        if route_str in marker_hits:
            marker_conf, _ = marker_hits[route_str]
            # Boost by up to 10× for a confidence-1.0 marker.
            marker_mult = 1.0 + 9.0 * marker_conf
            score *= marker_mult

        raw_scores[route_str] = score

    # 5. Add reason codes for GC range compatibility.
    _add_gc_reasons(features.gc_ratio, reasons)

    # 6. Normalise to probabilities.
    probs = _normalise(raw_scores)

    # 7. Select best route and fallbacks.
    sorted_routes = sorted(probs, key=probs.__getitem__, reverse=True)
    best_route_str = sorted_routes[0]
    best_conf = probs[best_route_str]

    # Treat misc_unknown as a catch-all: if it wins but confidence is low,
    # report as misc_unknown with low tier.
    best_route = TaxonomicRoute(best_route_str)

    # Confidence tier.
    tier = _confidence_tier(best_conf)
    if tier == ConfidenceTier.low:
        reasons.append("low_confidence_fallback")
    elif tier == ConfidenceTier.medium:
        reasons.append("medium_confidence_fallback")

    # Collect fallback routes (exclude best, include top-2 alternatives
    # if they have non-negligible probability).
    fallbacks = [
        r for r in sorted_routes[1:]
        if probs[r] > 0.05 and r != "misc_unknown"
    ][:2]
    # Always include misc_unknown as last-resort fallback.
    if "misc_unknown" not in fallbacks and best_route_str != "misc_unknown":
        fallbacks.append("misc_unknown")

    # Deduplicate reason codes while preserving order.
    seen: set[str] = set()
    deduped_reasons: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            deduped_reasons.append(r)

    return RouteResult(
        sequence_id=inp.sequence_id,
        route=best_route,
        route_confidence=round(best_conf, 4),
        confidence_tier=tier,
        fallback_routes=fallbacks,
        reason_codes=deduped_reasons,
        raw_scores=raw_scores,
    )


def route_batch(sequences: list[RouterInput]) -> list[RouteResult]:
    """Route a list of sequences and return a parallel list of RouteResults."""
    return [route_sequence(seq) for seq in sequences]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_low_quality(inp: RouterInput, reasons: list[str]) -> bool:
    low = False
    if inp.n_ratio > LOW_QUALITY_THRESHOLDS["max_n_ratio"]:
        reasons.append("high_n_ratio")
        low = True
    if inp.length < LOW_QUALITY_THRESHOLDS["min_length"]:
        reasons.append("length_too_short")
        low = True
    return low


def _gaussian(x: float, mean: float, std: float) -> float:
    """Un-normalised Gaussian likelihood (max = 1.0 at x = mean)."""
    if std <= 0:
        return 1.0
    return math.exp(-0.5 * ((x - mean) / std) ** 2)


def _length_score(length: int, min_len: int, max_len: int) -> float:
    """
    Returns 1.0 if length is in [min_len, max_len],
    decays with a logistic penalty outside that range.
    """
    if min_len <= length <= max_len:
        return 1.0
    if length < min_len:
        # Short penalty: soft below min_len.
        delta = min_len - length
        return 1.0 / (1.0 + delta / max(min_len * 0.3, 1.0))
    else:
        # Long penalty: gentle above max_len.
        delta = length - max_len
        return 1.0 / (1.0 + delta / max(max_len * 0.5, 1.0))


def _normalise(scores: dict[str, float]) -> dict[str, float]:
    """Normalise a score dict to sum to 1.0."""
    total = sum(scores.values())
    if total <= 0:
        n = len(scores)
        return {k: 1.0 / n for k in scores}
    return {k: v / total for k, v in scores.items()}


def _confidence_tier(confidence: float) -> ConfidenceTier:
    if confidence >= 0.70:
        return ConfidenceTier.high
    if confidence >= 0.40:
        return ConfidenceTier.medium
    return ConfidenceTier.low


def _add_gc_reasons(gc_ratio: float, reasons: list[str]) -> None:
    """Append human-readable GC reason codes based on the observed GC ratio."""
    if gc_ratio < 0.35:
        reasons.append("gc_low_at_rich")
    elif gc_ratio > 0.65:
        reasons.append("gc_high_gc_rich")
    elif 0.38 <= gc_ratio <= 0.52:
        reasons.append("gc_vertebrate_compatible")
    if 0.30 <= gc_ratio <= 0.75:
        reasons.append("gc_bacteria_compatible")
    if 0.38 <= gc_ratio <= 0.45:
        reasons.append("gc_human_compatible")
