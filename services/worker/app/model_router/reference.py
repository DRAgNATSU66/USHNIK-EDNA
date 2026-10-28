"""
Heuristic reference profiles for each taxonomic route.

Each RouteProfile encodes expert knowledge about the expected GC content,
sequence length, homopolymer content, and CpG ratio for sequences belonging
to that route.  These parameters are used by the Gaussian scoring kernel in
router.py to compute per-route likelihood scores.

Phase 7 replaces these heuristic profiles with learned embeddings from a
DNA foundation model.  The profiles here are intentionally conservative:
they produce wide probability distributions so the router correctly expresses
uncertainty rather than confidently mis-routing.

Sources:
  - Miya et al. 2015 (MiFish 12S, teleost GC ~42-48%)
  - Jerde et al. 2011 (eDNA fish detection)
  - Klindworth et al. 2013 (16S universal primers, bacteria GC 25-75%)
  - BOLD Systems v4 (COI animal GC ~40-46%)
  - Fazekas et al. 2008 (rbcL plant chloroplast GC ~38-46%)
  - Human mtDNA reference (GC ~44%)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RouteProfile:
    route: str
    # Gaussian prior on GC ratio: (mean, standard_deviation)
    gc_mean: float
    gc_std: float
    # Typical amplicon/barcode length range for this route.
    typical_length_min: int
    typical_length_max: int
    # CpG O/E ratio: (mean, std).  Only meaningful for eukaryote routes.
    cpg_oe_mean: float
    cpg_oe_std: float
    # Base prior weight — used before any evidence is applied.
    # Routes that are more commonly encountered in typical eDNA samples
    # have a higher prior.
    base_prior: float = 1.0
    # Habitat hints: if sample metadata matches, multiply base_prior.
    # Keys are habitat strings from the upload metadata.
    habitat_boost: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Profile catalogue
# ---------------------------------------------------------------------------

ROUTE_PROFILES: dict[str, RouteProfile] = {
    "fish": RouteProfile(
        route="fish",
        gc_mean=0.45,
        gc_std=0.06,
        typical_length_min=100,
        typical_length_max=800,
        cpg_oe_mean=0.15,
        cpg_oe_std=0.10,
        base_prior=1.0,
        habitat_boost={"marine": 1.4, "freshwater": 1.4, "estuarine": 1.3},
    ),
    "plant": RouteProfile(
        route="plant",
        gc_mean=0.42,
        gc_std=0.06,
        typical_length_min=100,
        typical_length_max=900,
        cpg_oe_mean=0.12,
        cpg_oe_std=0.09,
        base_prior=0.8,
        habitat_boost={"terrestrial": 1.5, "wetland": 1.3, "riparian": 1.3},
    ),
    "bacteria_pathogen": RouteProfile(
        route="bacteria_pathogen",
        gc_mean=0.50,
        gc_std=0.15,   # bacteria GC is extremely variable (25–75%)
        typical_length_min=100,
        typical_length_max=1600,
        cpg_oe_mean=0.05,
        cpg_oe_std=0.05,
        base_prior=1.2,  # bacteria very common in eDNA samples
    ),
    "animal_general": RouteProfile(
        route="animal_general",
        gc_mean=0.44,
        gc_std=0.07,
        typical_length_min=100,
        typical_length_max=750,
        cpg_oe_mean=0.20,
        cpg_oe_std=0.12,
        base_prior=0.9,
        habitat_boost={"marine": 1.2, "freshwater": 1.1, "terrestrial": 1.2},
    ),
    "human_domestic_contamination": RouteProfile(
        route="human_domestic_contamination",
        gc_mean=0.41,
        gc_std=0.04,   # human genome GC is fairly uniform (~41%)
        typical_length_min=50,
        typical_length_max=1000,
        cpg_oe_mean=0.60,
        cpg_oe_std=0.20,  # CpG islands present in human promoters
        base_prior=0.3,   # low prior — not expected in clean eDNA samples
    ),
    "misc_unknown": RouteProfile(
        route="misc_unknown",
        gc_mean=0.50,
        gc_std=0.20,   # flat/agnostic distribution
        typical_length_min=30,
        typical_length_max=5000,
        cpg_oe_mean=0.30,
        cpg_oe_std=0.25,
        base_prior=0.5,
    ),
}

# low_quality is a special case — it is assigned before profile scoring.
LOW_QUALITY_THRESHOLDS = {
    "max_n_ratio": 0.40,
    "min_length": 30,
}
