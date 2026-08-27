"""
Assigns a result_class label (see ROUTE_LABEL_SETS in
services/worker/app/inference/models.py) to a single record, using signal
that's actually present in the reference data rather than invented:

  - low_quality_unusable  <- same N-ratio/length thresholds the real router
                              already uses (LOW_QUALITY_THRESHOLDS), so the
                              classifier head learns the same boundary the
                              heuristic pre-filter uses.
  - possible_novelty /
    unknown_needs_online_confirmation
                           <- NCBI/BOLD organism names that are literally
                              "uncultured X", "environmental sample",
                              "unidentified" etc. — these ARE real novel/
                              unresolved sequences, not a proxy.
  - likely_taxonomic_group <- records identified only to genus/family
                              ("Genus sp.", "cf. species"), a real signal
                              for "we know the group, not the species".
  - known_species          <- everything else: a clean, species-level
                              curated reference record.

possible_contamination is NOT assigned here — it's an inherently cross-
route signal (route X sample containing route Y's organism), so it's
injected by build_dataset.py after each route's pool is built, not decided
per-record in isolation.
"""
from __future__ import annotations

import re

from app.model_router.reference import LOW_QUALITY_THRESHOLDS
from app.inference.models import SequenceResultClass, ROUTE_LABEL_SETS

_UNRESOLVED_PATTERNS = re.compile(
    r"uncultured|environmental sample|unidentified|unclassified|metagenome",
    re.IGNORECASE,
)
_HIGHER_RANK_ONLY_PATTERNS = re.compile(r"\bsp\.?$|\bcf\.\s", re.IGNORECASE)


def n_ratio(sequence: str) -> float:
    if not sequence:
        return 1.0
    n_count = sum(1 for c in sequence.upper() if c == "N")
    return n_count / len(sequence)


def is_low_quality(sequence: str) -> bool:
    return (
        n_ratio(sequence) >= LOW_QUALITY_THRESHOLDS["max_n_ratio"]
        or len(sequence) < LOW_QUALITY_THRESHOLDS["min_length"]
    )


def is_unresolved(organism_name: str) -> bool:
    return bool(_UNRESOLVED_PATTERNS.search(organism_name or ""))


def is_higher_rank_only(organism_name: str, lineage: dict[str, str]) -> bool:
    # Deliberately NOT falling back to "'species' not in lineage" here.
    # That flags any record where NCBI's taxonomy tree happens to lack a
    # species-rank node — extremely common for bacteria specifically for
    # curatorial reasons unrelated to whether the sequence itself is
    # identifiable, which flooded this label with sequences sequence-level
    # indistinguishable from known_species (measured: dragged that class's
    # F1 to ~0.61 despite more data and class-weighting, both tried and
    # both failing to fix it — a genuine label-definition problem, not a
    # data-volume or class-imbalance one). Rely only on the explicit naming
    # convention ("Genus sp.", "cf. species") — real curatorial judgment
    # that this was identified only to genus, not a taxonomy-completeness
    # artifact.
    return bool(_HIGHER_RANK_ONLY_PATTERNS.search(organism_name or ""))


def assign_label(route: str, sequence: str, organism_name: str, lineage: dict[str, str]) -> str | None:
    """Returns a SequenceResultClass value valid for `route`, or None if
    nothing in this route's label set fits (record should be dropped)."""
    allowed = set(ROUTE_LABEL_SETS.get(route, []))
    if not allowed:
        return None

    if is_low_quality(sequence) and SequenceResultClass.low_quality_unusable in allowed:
        return SequenceResultClass.low_quality_unusable

    if is_unresolved(organism_name):
        if SequenceResultClass.possible_novelty in allowed:
            return SequenceResultClass.possible_novelty
        if SequenceResultClass.unknown_needs_online_confirmation in allowed:
            return SequenceResultClass.unknown_needs_online_confirmation

    if is_higher_rank_only(organism_name, lineage) and SequenceResultClass.likely_taxonomic_group in allowed:
        return SequenceResultClass.likely_taxonomic_group

    if SequenceResultClass.known_species in allowed:
        return SequenceResultClass.known_species
    if SequenceResultClass.unknown_needs_online_confirmation in allowed:
        return SequenceResultClass.unknown_needs_online_confirmation

    return None
