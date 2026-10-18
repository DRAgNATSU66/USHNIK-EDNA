"""
Abyss analysis engine — Phase 10.

Runs a lightweight version of the analysis pipeline suitable for offline
field conditions:

  1. QC   — length, GC, N-ratio, invalid chars (pure Python, no deps)
  2. Route — the learned k-mer router (learned_router.py: numpy, local
     artifact, no network); GC-only fallback, marked on every result, when the
     router artifact is unavailable (B25)
  3. Novelty — Phase 8 novelty + contamination scoring. The API has no
     app.novelty package, so today this always takes the stub path and marks
     results with the reason code "abyss_stub".

Deliberately omits the foundation model inference stage (Phase 7).
The router result_class is used as a stub result_class so the novelty scorer
can run. This is the same stub path the worker uses when torch is unavailable.

All results carry:
  - requires_cloud_confirmation = True  (always, for Abyss Mode)
  - abyss_recommendation from the novelty scorer
  - a disclaimer reminding users this is field triage only

The engine is synchronous and runs in-process on the API server's thread pool
via asyncio.run_in_executor. Sequences > 500 are truncated to prevent slow
responses on field hardware.
"""
from __future__ import annotations

import logging
import math
from typing import Any

from ..config import NOVELTY_THRESHOLD
from .learned_router import FORCED_REASON, AbyssRouterModel, get_router
from .models import (
    AbyssRouterSummary,
    AbyssSequenceInput,
    AbyssSequenceResult,
    AbyssAnalysisResult,
    ABYSS_DISCLAIMER,
)

logger = logging.getLogger(__name__)

# Fallbacks (router unavailable or failing, missing novelty scorer) already
# logged, keyed by (kind, message), so a batch of 500 sequences hitting the same
# problem logs once, not 500 times.  Every affected result is still marked
# (router_method / router_error_fallback / reason code "abyss_stub").
_LOGGED_FALLBACKS: set[tuple[str, str]] = set()

# Max sequences per abyss analysis call (field triage — not bulk pipeline)
_MAX_SEQUENCES = 500
# Truncate very long sequences before routing to keep analysis fast
_MAX_SEQ_LENGTH = 2000


def run_abyss_analysis(
    expedition_id: str,
    sequences: list[AbyssSequenceInput],
) -> AbyssAnalysisResult:
    """
    Run lightweight abyss analysis synchronously.

    Called via run_in_executor so the event loop is not blocked.
    Returns a fully populated AbyssAnalysisResult with disclaimer.
    """
    truncated = sequences[:_MAX_SEQUENCES]
    results: list[AbyssSequenceResult] = [
        _analyze_one(seq) for seq in truncated
    ]

    possible_novelty = sum(1 for r in results if r.novelty_score >= NOVELTY_THRESHOLD)
    contamination_flags = sum(1 for r in results if r.contamination_flagged)
    low_quality = sum(1 for r in results if r.route == "low_quality")
    requires_cloud = any(r.requires_cloud_confirmation for r in results)

    batch_rec, risk = _batch_recommendation(results)

    return AbyssAnalysisResult(
        expedition_id=expedition_id,
        sequences_analyzed=len(results),
        possible_novelty_count=possible_novelty,
        contamination_flag_count=contamination_flags,
        low_quality_count=low_quality,
        results=results,
        batch_recommendation=batch_rec,
        batch_risk_level=risk,
        requires_cloud_confirmation=requires_cloud,
        router=_router_summary(results),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _analyze_one(seq: AbyssSequenceInput) -> AbyssSequenceResult:
    raw = seq.sequence.upper()[:_MAX_SEQ_LENGTH]
    qc = _compute_qc(raw)

    # Low-quality gate — skip routing and scoring
    if qc["length"] < 30 or qc["n_ratio"] > 0.40 or qc["has_invalid_chars"]:
        return AbyssSequenceResult(
            sequence_id=seq.sequence_id,
            length=qc["length"],
            gc_ratio=qc["gc_ratio"],
            n_ratio=qc["n_ratio"],
            route="low_quality",
            route_confidence=0.0,
            confidence_tier="low",
            novelty_score=0.0,
            novelty_level="none",
            contamination_flagged=False,
            contamination_score=0.0,
            abyss_recommendation="resample",
            requires_cloud_confirmation=False,
            reason_codes=["low_quality_skipped"],
            field_action="resample",
            router_method="low_quality_gate",
        )

    # Route: learned k-mer router, GC-only fallback (no torch, no network)
    route_result = _route(raw, qc, seq)

    # Build a sequence dict that the novelty scorer understands
    seq_dict: dict[str, Any] = {
        "sequence_id": seq.sequence_id,
        "sequence": raw,
        "route": route_result["route"],
        "route_confidence": route_result["route_confidence"],
        "confidence_tier": route_result["confidence_tier"],
        "fallback_routes": route_result.get("fallback_routes", []),
        "result_class": _stub_result_class(route_result["route"], route_result["route_confidence"]),
        "confidence": route_result["route_confidence"],
        "label_scores": _stub_label_scores(route_result["route"], route_result["route_confidence"]),
        "embedding": None,
        "gc_ratio": qc["gc_ratio"],
        "n_ratio": qc["n_ratio"],
        "length": qc["length"],
        "has_invalid_chars": qc["has_invalid_chars"],
        "cpg_oe": qc.get("cpg_oe", 0.0),
        "reason_codes": route_result.get("reason_codes", []),
    }

    # Novelty scoring
    try:
        from ..novelty.contamination import contamination_score
        from ..novelty.scorer import score_sequence

        cont = contamination_score(seq_dict)
        seq_dict["contamination_score"] = cont.contamination_score
        seq_dict["contamination_flagged"] = cont.is_flagged

        nov = score_sequence(seq_dict)
    except ImportError as exc:
        # Worker novelty module not available in this env — produce stub scores
        # (marked with reason code "abyss_stub"). Log once per process.
        key = ("novelty_import", str(exc))
        if key not in _LOGGED_FALLBACKS:
            _LOGGED_FALLBACKS.add(key)
            logger.warning("Abyss novelty scorer unavailable (%s); using stub scores", exc)
        nov = _stub_novelty(seq_dict)
        cont = _stub_contamination(seq_dict)

    field_action = _field_action(nov.abyss_recommendation)

    reason_codes = list(route_result.get("reason_codes", []))
    for code in nov.reason_codes:
        if code not in reason_codes:
            reason_codes.append(code)

    return AbyssSequenceResult(
        sequence_id=seq.sequence_id,
        length=qc["length"],
        gc_ratio=qc["gc_ratio"],
        n_ratio=qc["n_ratio"],
        route=route_result["route"],
        route_confidence=route_result["route_confidence"],
        confidence_tier=route_result["confidence_tier"],
        novelty_score=nov.novelty_score,
        novelty_level=str(nov.novelty_level),
        contamination_flagged=cont.is_flagged,
        contamination_score=cont.contamination_score,
        abyss_recommendation=str(nov.abyss_recommendation),
        requires_cloud_confirmation=True,  # always True in Abyss Mode
        reason_codes=reason_codes,
        field_action=field_action,
        router_method=route_result["router_method"],
        router_version=route_result.get("router_version"),
        router_fallback_reason=route_result.get("router_fallback_reason"),
        route_probabilities=route_result.get("route_probabilities", {}),
        probabilities_calibrated=route_result.get("probabilities_calibrated", False),
        router_error_fallback=route_result.get("router_error_fallback", False),
        router_error=route_result.get("router_error"),
    )


def _compute_qc(sequence: str) -> dict[str, Any]:
    length = len(sequence)
    if length == 0:
        return {"length": 0, "gc_ratio": 0.0, "n_ratio": 0.0,
                "has_invalid_chars": False, "cpg_oe": 0.0}

    valid_bases = set("ACGTNRYSWKMBDHVN")
    gc = sum(1 for b in sequence if b in "GC")
    n_count = sequence.count("N")
    atgc = sum(1 for b in sequence if b in "ATGC")
    has_invalid = any(b not in valid_bases for b in sequence)

    gc_ratio = gc / atgc if atgc > 0 else 0.0
    n_ratio = n_count / length

    # CpG O/E
    cpg = sequence.count("CG")
    c_count = sequence.count("C")
    g_count = sequence.count("G")
    cpg_oe = (cpg * length) / (c_count * g_count) if (c_count > 0 and g_count > 0) else 0.0

    return {
        "length": length,
        "gc_ratio": round(gc_ratio, 4),
        "n_ratio": round(n_ratio, 4),
        "has_invalid_chars": has_invalid,
        "cpg_oe": round(cpg_oe, 4),
    }


def _route(
    sequence: str,
    qc: dict[str, Any],
    seq_input: AbyssSequenceInput,
) -> dict[str, Any]:
    """
    Route one sequence offline (B25).

    First stage: the learned k-mer router (learned_router.py), loaded from the
    same registry entry and router.npz as the worker's, with numpy only and
    no network. When it is unavailable (artifact missing, checksum mismatch,
    numpy missing, SYNTHVEDA_ROUTER=heuristic) or cannot score this sequence
    (no valid k-mer, prediction error), _simple_gc_route answers instead and
    the result says so: router_method "gc_fallback" (or "gc_only" when
    forced), router_fallback_reason, router_error_fallback=True and the reason
    code "router_error_fallback". Each distinct failure is logged once.
    """
    model, reason, detail = get_router()
    if model is not None:
        try:
            probs = model.predict_proba(sequence)
        except Exception as exc:
            reason, detail = "predict_error", f"{type(exc).__name__}: {exc}"
            key = ("predict_error", detail)
            if key not in _LOGGED_FALLBACKS:
                _LOGGED_FALLBACKS.add(key)
                logger.warning(
                    "Abyss learned router failed on %s (%s); falling back to GC-only routing",
                    seq_input.sequence_id, detail, exc_info=True,
                )
        else:
            if probs is not None:
                return _learned_route(model, probs)
            reason, detail = "no_valid_kmers", f"no valid {model.k}-mer (non-ACGT bases)"

    forced = reason == FORCED_REASON
    if not forced:
        key = ("router_unavailable", f"{reason}: {detail}")
        if key not in _LOGGED_FALLBACKS:
            _LOGGED_FALLBACKS.add(key)
            logger.warning("Abyss routing uses GC-only fallback (%s: %s)", reason, detail)
    fallback = _simple_gc_route(qc, seq_input.habitat)
    fallback["router_method"] = "gc_only" if forced else "gc_fallback"
    fallback["router_fallback_reason"] = reason
    fallback["router_error_fallback"] = not forced
    fallback["router_error"] = f"{reason}: {detail}" if detail else reason
    if not forced:
        fallback["reason_codes"] = ["router_error_fallback", *fallback["reason_codes"]]
    return fallback


def _learned_route(model: AbyssRouterModel, probs: dict[str, float]) -> dict[str, Any]:
    """Same conventions as the worker's router._learned_result: route_confidence
    is the top calibrated probability, tiers at 0.70 / 0.40, up to two
    fallbacks above 0.05 and then misc_unknown as the last resort."""
    ranked = sorted(probs, key=probs.__getitem__, reverse=True)
    best = ranked[0]
    conf = probs[best]
    tier = "high" if conf >= 0.70 else "medium" if conf >= 0.40 else "low"
    reasons = ["learned_router"]
    if tier == "low":
        reasons.append("low_confidence_fallback")
    elif tier == "medium":
        reasons.append("medium_confidence_fallback")
    fallbacks = [r for r in ranked[1:] if probs[r] > 0.05 and r != "misc_unknown"][:2]
    if "misc_unknown" not in fallbacks and best != "misc_unknown":
        fallbacks.append("misc_unknown")
    return {
        "route": best,
        "route_confidence": round(conf, 4),
        "confidence_tier": tier,
        "fallback_routes": fallbacks,
        "reason_codes": reasons,
        "router_method": "learned",
        "router_version": model.version,
        "route_probabilities": {r: round(v, 4) for r, v in probs.items()},
        "probabilities_calibrated": True,
    }


def _router_summary(results: list[AbyssSequenceResult]) -> AbyssRouterSummary:
    """Which router ran for this batch, stated once at the top of the result."""
    model, reason, detail = get_router()
    counts: dict[str, int] = {}
    for r in results:
        counts[r.router_method] = counts.get(r.router_method, 0) + 1
    if model is not None:
        return AbyssRouterSummary(
            method="learned",
            model_id=model.model_id,
            version=model.version,
            artifact_sha256=model.sha256,
            counts=counts,
        )
    return AbyssRouterSummary(
        method="gc_only" if reason == FORCED_REASON else "gc_fallback",
        fallback_reason=reason,
        detail=detail,
        counts=counts,
    )


def _simple_gc_route(qc: dict, habitat: str | None) -> dict[str, Any]:
    """Minimal inline fallback router based on GC ratio only."""
    gc = qc["gc_ratio"]
    habitat_lower = (habitat or "").lower()

    if "human" in habitat_lower or "lab" in habitat_lower:
        return {
            "route": "human_domestic_contamination",
            "route_confidence": 0.55,
            "confidence_tier": "medium",
            "fallback_routes": ["misc_unknown"],
            "reason_codes": ["habitat_human_lab"],
        }

    # Fish: GC ~0.42–0.52
    if 0.40 <= gc <= 0.55:
        return {
            "route": "fish",
            "route_confidence": 0.45,
            "confidence_tier": "low",
            "fallback_routes": ["animal_general", "misc_unknown"],
            "reason_codes": ["gc_fish_range_fallback"],
        }

    # Bacteria: GC ~0.35–0.65 (wide range, but high GC is typical)
    if gc >= 0.55:
        return {
            "route": "bacteria_pathogen",
            "route_confidence": 0.40,
            "confidence_tier": "low",
            "fallback_routes": ["misc_unknown"],
            "reason_codes": ["high_gc_bacteria_fallback"],
        }

    return {
        "route": "misc_unknown",
        "route_confidence": 0.30,
        "confidence_tier": "low",
        "fallback_routes": [],
        "reason_codes": ["gc_fallback_misc"],
    }


def _stub_result_class(route: str, confidence: float) -> str:
    if route == "human_domestic_contamination":
        return "possible_contamination"
    if route == "low_quality":
        return "low_quality_unusable"
    if confidence >= 0.70:
        return "known_species"
    if confidence >= 0.40:
        return "unknown_needs_online_confirmation"
    return "unknown_needs_online_confirmation"


def _stub_label_scores(route: str, confidence: float) -> dict[str, float]:
    if route == "human_domestic_contamination":
        return {"possible_contamination": confidence, "unknown_needs_online_confirmation": 1 - confidence}
    remaining = 1.0 - confidence
    return {
        "known_species": confidence * 0.5,
        "possible_novelty": remaining * 0.4,
        "unknown_needs_online_confirmation": remaining * 0.4 + confidence * 0.5,
        "low_quality_unusable": remaining * 0.2,
    }


class _StubNoveltyScore:
    def __init__(self, seq_dict: dict):
        self.novelty_score = 0.3 if seq_dict.get("route") not in ("low_quality", "human_domestic_contamination") else 0.0
        self.novelty_level = "low"
        self.abyss_recommendation = "continue_sampling"
        self.reason_codes = ["abyss_stub"]
        self.requires_cloud_confirmation = True


class _StubContaminationScore:
    def __init__(self, seq_dict: dict):
        self.is_flagged = seq_dict.get("route") == "human_domestic_contamination"
        self.contamination_score = 0.9 if self.is_flagged else 0.0


def _stub_novelty(seq_dict: dict) -> _StubNoveltyScore:
    return _StubNoveltyScore(seq_dict)


def _stub_contamination(seq_dict: dict) -> _StubContaminationScore:
    return _StubContaminationScore(seq_dict)


def _field_action(abyss_recommendation) -> str:
    mapping = {
        "preserve_sample": "preserve_sample",
        "continue_sampling": "continue_sampling",
        "resample": "resample",
        "return_for_full_analysis": "return_for_full_analysis",
    }
    return mapping.get(str(abyss_recommendation), "continue_sampling")


def _batch_recommendation(results: list[AbyssSequenceResult]) -> tuple[str, str]:
    """
    Derive a single batch-level recommendation from individual sequence results.

    Rules (highest urgency wins):
      any preserve_sample → batch: preserve_sample, risk: high
      any return_for_full_analysis → batch: return_for_full_analysis, risk: high
      >20% novelty or >10% contamination → risk: medium
      otherwise → continue_sampling, risk: low
    """
    if not results:
        return "continue_sampling", "low"

    actions = [r.field_action for r in results]
    total = len(results)
    novelty_frac = sum(1 for r in results if r.novelty_score >= NOVELTY_THRESHOLD) / total
    cont_frac = sum(1 for r in results if r.contamination_flagged) / total

    if "preserve_sample" in actions:
        return "preserve_sample", "high"
    if "return_for_full_analysis" in actions:
        return "return_for_full_analysis", "high"
    if novelty_frac > 0.20 or cont_frac > 0.10:
        return "continue_sampling", "medium"
    return "continue_sampling", "low"
