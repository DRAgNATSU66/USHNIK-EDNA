"""
Abyss analysis engine — Phase 10.

Runs a lightweight version of the analysis pipeline suitable for offline
field conditions:

  1. QC   — length, GC, N-ratio, invalid chars (pure Python, no deps)
  2. Route — heuristic router (markers + biophysical scoring, no ML)
  3. Novelty — Phase 8 novelty + contamination scoring

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

import math
from typing import Any

from .models import (
    AbyssSequenceInput,
    AbyssSequenceResult,
    AbyssAnalysisResult,
    ABYSS_DISCLAIMER,
)

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

    possible_novelty = sum(1 for r in results if r.novelty_score >= 0.45)
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
        )

    # Route via heuristic router (no torch required)
    try:
        from ..app.model_router import route_sequence, RouterInput  # type: ignore
    except ImportError:
        pass
    route_result = _heuristic_route(raw, qc, seq)

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
    except ImportError:
        # Worker novelty module not available in this env — produce stub scores
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


def _heuristic_route(
    sequence: str,
    qc: dict[str, Any],
    seq_input: AbyssSequenceInput,
) -> dict[str, Any]:
    """
    Fast heuristic routing using marker gene detection and biophysical priors.
    Tries to use the worker model_router if available; otherwise falls back
    to a simplified inline version.
    """
    try:
        import sys
        import os
        worker_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "worker")
        )
        if worker_path not in sys.path:
            sys.path.insert(0, worker_path)

        from app.model_router import route_sequence, RouterInput  # type: ignore

        inp = RouterInput(
            sequence_id=seq_input.sequence_id,
            sequence=sequence,
            length=qc["length"],
            gc_ratio=qc["gc_ratio"],
            n_ratio=qc["n_ratio"],
            sha256="",
            source_file="abyss",
            habitat=seq_input.habitat,
            depth_meters=seq_input.depth_meters,
        )
        result = route_sequence(inp)
        return {
            "route": str(result.route),
            "route_confidence": result.route_confidence,
            "confidence_tier": str(result.confidence_tier),
            "fallback_routes": result.fallback_routes,
            "reason_codes": result.reason_codes,
        }
    except Exception:
        # Inline fallback — simplified GC-based routing
        return _simple_gc_route(qc, seq_input.habitat)


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
    novelty_frac = sum(1 for r in results if r.novelty_score >= 0.45) / total
    cont_frac = sum(1 for r in results if r.contamination_flagged) / total

    if "preserve_sample" in actions:
        return "preserve_sample", "high"
    if "return_for_full_analysis" in actions:
        return "return_for_full_analysis", "high"
    if novelty_frac > 0.20 or cont_frac > 0.10:
        return "continue_sampling", "medium"
    return "continue_sampling", "low"
