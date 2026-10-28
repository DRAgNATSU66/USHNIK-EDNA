"""
Contamination detector.

Combines three independent signal families:
  1. Route signal  — router assigned human_domestic_contamination
  2. Marker signal — marker gene patterns from Phase 6 markers.py that are
                     specific to human / domestic animals
  3. Sequence features — GC ratio, CpG O/E, homopolymer fraction consistent
                         with human/domestic animal genomes

Contamination types reported:
  human_dna           — human mitochondrial or nuclear DNA
  domestic_animal     — dog, cat, cattle, horse DNA
  lab_reagent         — common lab vector / adapter sequences
  low_abundance_common — a well-known contaminant at very low read count
  unknown_contamination — contamination suspected but type unknown

Flag threshold: contamination_score >= 0.5
"""
from __future__ import annotations

import math

from .models import ContaminationScore

# ---------------------------------------------------------------------------
# Lab reagent / vector signatures
# These are common sources of cross-contamination in eDNA workflows.
# ---------------------------------------------------------------------------

_LAB_MOTIFS: list[str] = [
    # pUC19 / pBR322 plasmid backbone (often used as positive control)
    "GAATTCGAGCTCGGTACCC",
    # PhiX174 control library (Illumina spike-in)
    "GAGTTTTATCGCTTCCATGAC",
    "CCCTATAGTGAGTCGTATTA",
    # Illumina universal adapter sequence (TruSeq)
    "AGATCGGAAGAGC",
    # Common PCR primer dimer (from 16S V3-V4 primers)
    "CCTACGGGNGGCWGCAGCCTACGGG",
]

# GC ratio of the human genome: ~0.41 (±0.03)
_HUMAN_GC_MEAN = 0.41
_HUMAN_GC_STD  = 0.03

# CpG O/E: human promoters have islands ≥ 0.6; genome-wide ~0.25–0.35.
# We flag when CpG O/E is in the human-typical range.
_HUMAN_CPG_MIN = 0.20
_HUMAN_CPG_MAX = 0.80


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def contamination_score(seq: dict) -> ContaminationScore:
    """
    Compute a ContaminationScore for a single sequence dict.

    Expects keys from the full pipeline dict:
      sequence_id, route, result_class, sequence, gc_ratio, n_ratio,
      has_invalid_chars, length.  Optional: cpg_oe (from features).
    """
    seq_id = seq.get("sequence_id", "unknown")
    signals: dict[str, float] = {}
    reason_codes: list[str] = []
    detected_type: str | None = None

    # 1. Router / inference signal.
    route_score, route_code, route_type = _signal_route(seq)
    signals["route"] = route_score
    if route_code:
        reason_codes.append(route_code)
    if route_type:
        detected_type = route_type

    # 2. Lab reagent motifs.
    lab_score, lab_code = _signal_lab_motifs(seq)
    signals["lab_motif"] = lab_score
    if lab_code:
        reason_codes.append(lab_code)
    if lab_score >= 0.8 and detected_type is None:
        detected_type = "lab_reagent"

    # 3. Human genome biophysical profile.
    human_score, human_code, human_type = _signal_human_profile(seq)
    signals["human_profile"] = human_score
    if human_code:
        reason_codes.append(human_code)
    if human_score >= 0.6 and detected_type is None:
        detected_type = human_type

    # 4. Combined score — weighted average.
    # Route signal is the strongest since it incorporates marker detection.
    weights = {"route": 0.50, "lab_motif": 0.30, "human_profile": 0.20}
    total_score = sum(weights[k] * signals[k] for k in weights)
    total_score = round(min(total_score, 1.0), 4)

    # Hard-flag when any single definitive signal is very strong — the weighted
    # sum can stay below 0.5 even when one signal alone is conclusive.
    hard_flag = route_score >= 0.80 or lab_score >= 0.80
    is_flagged = total_score >= 0.50 or hard_flag
    if is_flagged and detected_type is None:
        detected_type = "unknown_contamination"
    if is_flagged and "contamination_flagged" not in reason_codes:
        reason_codes.append("contamination_flagged")
    if not is_flagged and not reason_codes:
        reason_codes.append("clean_sequence")

    return ContaminationScore(
        sequence_id=seq_id,
        contamination_score=total_score,
        is_flagged=is_flagged,
        contamination_type=detected_type,
        signals=signals,
        reason_codes=reason_codes,
    )


def contamination_score_batch(sequences: list[dict]) -> list[ContaminationScore]:
    """Score contamination for a list of sequence dicts."""
    return [contamination_score(seq) for seq in sequences]


# ---------------------------------------------------------------------------
# Individual signal functions
# ---------------------------------------------------------------------------

def _signal_route(seq: dict) -> tuple[float, str, str | None]:
    """Score based on router route and inference result_class."""
    route = seq.get("route", "misc_unknown")
    result_class = seq.get("result_class", "")

    if route == "human_domestic_contamination":
        return 0.90, "route_human_domestic", "human_dna"
    if result_class == "possible_contamination":
        return 0.75, "result_class_contamination", "unknown_contamination"

    # Weak signal: human_domestic fallback route in fallback_routes.
    fallbacks: list[str] = seq.get("fallback_routes", [])
    if "human_domestic_contamination" in fallbacks:
        return 0.30, "fallback_includes_contamination", None

    return 0.0, "", None


def _signal_lab_motifs(seq: dict) -> tuple[float, str]:
    """Detect known lab reagent / adapter sequences."""
    sequence: str = seq.get("sequence", "").upper()
    if not sequence:
        return 0.0, ""

    for motif in _LAB_MOTIFS:
        if motif in sequence:
            return 0.95, f"lab_motif_{motif[:12]}"

    return 0.0, ""


def _signal_human_profile(seq: dict) -> tuple[float, str, str | None]:
    """
    Score based on biophysical features consistent with human genome.

    Uses GC ratio and CpG O/E as primary discriminators.
    A sequence with GC ~0.41 AND elevated CpG O/E is consistent with
    human nuclear DNA.
    """
    gc_ratio = float(seq.get("gc_ratio", 0.5))
    cpg_oe = float(seq.get("cpg_oe", 0.0))
    length = int(seq.get("length", 0))

    if length < 50:
        return 0.0, "", None

    # GC proximity to human mean.
    gc_dist = abs(gc_ratio - _HUMAN_GC_MEAN)
    gc_score = math.exp(-0.5 * (gc_dist / _HUMAN_GC_STD) ** 2)

    # CpG O/E in human-typical range.
    if _HUMAN_CPG_MIN <= cpg_oe <= _HUMAN_CPG_MAX:
        cpg_score = 0.7
    else:
        cpg_score = 0.1

    combined = 0.5 * gc_score + 0.5 * cpg_score

    if combined >= 0.60:
        detected = "human_dna" if cpg_score > 0.5 else "domestic_animal"
        return round(combined, 4), "gc_cpg_human_compatible", detected

    return round(combined * 0.4, 4), "", None  # dampen weak signal
