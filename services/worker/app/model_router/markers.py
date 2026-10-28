"""
Marker gene detection.

Detects conserved motifs from key phylogenetic marker genes.  A sequence that
contains a motif from a specific marker is strongly associated with the
corresponding taxonomic route.

Implementation note: these are simplified exact substring matches against
conserved regions that appear BETWEEN common PCR primers.  In a production
system these would be replaced with profile HMM searches (HMMER3) or
approximate BLAST hits against a reference database.  For Phase 6 they
provide a strong primary signal when the target region was deliberately
amplified (amplicon-based eDNA).

Patterns are stored uppercase; all sequences must be uppercased before calling.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarkerPattern:
    name: str          # identifier, e.g. "16S_v3v4_fw"
    route: str         # associated taxonomic route
    motif: str         # exact uppercase substring to search for
    confidence: float  # how strongly this motif implies the route (0-1)
    description: str = ""


# ---------------------------------------------------------------------------
# Marker catalogue
# ---------------------------------------------------------------------------

# Conserved internal regions of key phylogenetic markers.
# Each motif is taken from heavily-cited PCR primer sites or conserved
# internal regions as described in the primary barcode / metabarcode
# literature (Illumina Earth Microbiome Project, BOLD, etc.).

_MARKERS: list[MarkerPattern] = [
    # ------------------------------------------------------------------
    # Bacteria / Archaea — 16S rRNA gene
    # Universal V3-V4 primers target this region; the conserved flanking
    # sequence appears in most 16S amplicons.
    # ------------------------------------------------------------------
    MarkerPattern("16S_fw_univ",    "bacteria_pathogen", "CCTACGGGNGGCWGCAG",   0.90,
                  "16S V3-V4 forward universal (338F region)"),
    MarkerPattern("16S_rv_univ",    "bacteria_pathogen", "GACTACNVGGGTWTCTAAT", 0.90,
                  "16S V3-V4 reverse universal (806R region)"),
    MarkerPattern("16S_short_1",    "bacteria_pathogen", "CCTACGGG",             0.55,
                  "Short 16S conserved motif (also in archaea)"),
    MarkerPattern("16S_short_2",    "bacteria_pathogen", "GTAAACGATG",           0.50,
                  "Short 16S fragment"),
    MarkerPattern("16S_arch",       "bacteria_pathogen", "TTCCGGTTGATCCYGCC",    0.85,
                  "Archaea 16S primer site (21F)"),

    # ------------------------------------------------------------------
    # Animals — COI (cytochrome c oxidase I) barcode
    # The Folmer region is ~650 bp, amplified with LCO1490/HCO2198 primers.
    # ------------------------------------------------------------------
    MarkerPattern("COI_lco",        "animal_general",    "GGTCAACAAATCATAAAGATATTGG", 0.92,
                  "COI Folmer LCO1490 primer site"),
    MarkerPattern("COI_hco",        "animal_general",    "TAAACTTCAGGGTGACCAAAAAATCA", 0.92,
                  "COI Folmer HCO2198 primer site"),
    MarkerPattern("COI_short",      "animal_general",    "TTTTTTTTTYTTT",         0.40,
                  "Short COI poly-T region (common in metazoans)"),
    MarkerPattern("COI_mam",        "animal_general",    "GGAGCCGGAATAATTGG",     0.75,
                  "COI mammalian-typical internal motif"),

    # ------------------------------------------------------------------
    # Fish — 12S rRNA mitochondrial barcode
    # MiFish primers target the V7 region of the mitochondrial 12S rRNA gene.
    # ------------------------------------------------------------------
    MarkerPattern("12S_mifish_fw",  "fish",              "GTCGGTAAAACTCGTGCCAGC", 0.95,
                  "MiFish-U forward primer site"),
    MarkerPattern("12S_mifish_rv",  "fish",              "CATAGTGGGGTATCTAATCCCAGTTTG", 0.95,
                  "MiFish-U reverse primer site"),
    MarkerPattern("12S_fish_int",   "fish",              "CGCCTGTTTATCAAAAACAT",  0.75,
                  "Fish-specific internal 12S motif"),
    MarkerPattern("12S_teleost",    "fish",              "AAACTATGGCTACACCTTG",   0.70,
                  "Teleost-specific 12S internal region"),

    # ------------------------------------------------------------------
    # Plants — rbcL and matK chloroplast markers
    # RbcLa primers target the first ~600 bp of the rbcL gene.
    # ------------------------------------------------------------------
    MarkerPattern("rbcL_fw",        "plant",             "ATGTCACCACAAACAGAGAC", 0.90,
                  "rbcL forward primer region"),
    MarkerPattern("rbcL_rv",        "plant",             "GTAAAATCAAGTCCACCRCG", 0.85,
                  "rbcL reverse primer region"),
    MarkerPattern("rbcL_int",       "plant",             "TTGGCAGCATTCCGAGTTAT", 0.70,
                  "rbcL internal conserved region"),
    MarkerPattern("matK_fw",        "plant",             "CGTACAGTACTTTTGTGTTTACGAG", 0.85,
                  "matK forward primer"),
    MarkerPattern("matK_int",       "plant",             "ATCCATTATGTAATACGAGC",  0.65,
                  "matK internal conserved"),

    # ------------------------------------------------------------------
    # Human / domestic contamination
    # Human mitochondrial D-loop and nuclear Alu elements are common
    # contamination signals in environmental samples.
    # ------------------------------------------------------------------
    MarkerPattern("hum_mito_dloop", "human_domestic_contamination",
                  "TTAATTAGGGTTCCTACTTCAG",  0.88,
                  "Human mitochondrial D-loop region"),
    MarkerPattern("hum_mito_int",   "human_domestic_contamination",
                  "TTGGGGTTTCTTTTATAATTTAG", 0.82,
                  "Human mtDNA internal control region"),
    MarkerPattern("hum_alu",        "human_domestic_contamination",
                  "GGCCGGGCGCGGTGGCTCACGCCTGTAAT", 0.78,
                  "Human Alu SINE consensus"),
    # Domestic animal (dog/cat) — common field contamination.
    MarkerPattern("dog_mito",       "human_domestic_contamination",
                  "CATGTATTATCGCACATTAATAC",  0.72,
                  "Domestic dog mtDNA"),
]

# ---------------------------------------------------------------------------
# Fast lookup structures
# ---------------------------------------------------------------------------

# Group patterns by route for quick per-route queries.
_PATTERNS_BY_ROUTE: dict[str, list[MarkerPattern]] = {}
for _p in _MARKERS:
    _PATTERNS_BY_ROUTE.setdefault(_p.route, []).append(_p)

# Flat name → pattern dict.
_PATTERNS_BY_NAME: dict[str, MarkerPattern] = {p.name: p for p in _MARKERS}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_markers(sequence: str) -> list[MarkerPattern]:
    """
    Return all MarkerPattern objects whose motif is found in `sequence`.

    `sequence` must be uppercase.  Performs exact substring matching.
    """
    matched: list[MarkerPattern] = []
    for pattern in _MARKERS:
        if pattern.motif in sequence:
            matched.append(pattern)
    return matched


def marker_route_scores(sequence: str) -> dict[str, tuple[float, list[str]]]:
    """
    Return a dict mapping route → (max_confidence, [matched_marker_names]).

    Only routes with at least one matching marker are included.
    """
    hits: dict[str, tuple[float, list[str]]] = {}
    for pattern in _MARKERS:
        if pattern.motif in sequence:
            route = pattern.route
            current_conf, current_names = hits.get(route, (0.0, []))
            # Take the highest confidence among matched markers for this route.
            new_conf = max(current_conf, pattern.confidence)
            hits[route] = (new_conf, current_names + [pattern.name])
    return hits
