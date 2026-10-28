"""
Sequence feature extraction for the taxonomic router.

Features used:
  - 4-mer frequency profile (256 features, normalised by count)
  - Minimizer sketch (set of rolling min-hash values for locality-sensitive similarity)
  - Derived scalars: gc_ratio, n_ratio, length (passed through from parser QC)

The k-mer / minimizer features are cheap to compute (linear in sequence length)
and form the backbone of the heuristic router.  Phase 7 replaces them with
dense embeddings from a DNA foundation model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import product


# ---------------------------------------------------------------------------
# Pre-build the 4-mer alphabet once at import time.
# ---------------------------------------------------------------------------

_BASES = "ACGT"
_KMERS_4: list[str] = ["".join(p) for p in product(_BASES, repeat=4)]  # 256 entries
_KMER_INDEX: dict[str, int] = {k: i for i, k in enumerate(_KMERS_4)}


@dataclass
class FeatureVector:
    """All features extracted from one sequence."""
    # Normalised 4-mer frequency profile (length 256, sums to ≈1).
    kmer4_freq: dict[str, float] = field(default_factory=dict)
    # Minimizer sketch — set of 64-bit rolling min-hashes.
    minimizer_sketch: set[int] = field(default_factory=set)
    # Scalars (already computed by the parser; included for completeness).
    length: int = 0
    gc_ratio: float = 0.0
    n_ratio: float = 0.0
    # CpG observed/expected ratio — elevated in human/mammalian genomes.
    cpg_oe: float = 0.0
    # Fraction of sequence covered by homopolymer runs (≥ 4 identical bases).
    homopolymer_fraction: float = 0.0


def extract_features(sequence: str, gc_ratio: float = 0.0, n_ratio: float = 0.0) -> FeatureVector:
    """
    Extract a FeatureVector from a nucleotide sequence.

    `sequence` must be uppercase (guaranteed by the parser).
    `gc_ratio` and `n_ratio` are passed from the parser QC output to avoid
    recomputing them.
    """
    seq = sequence.upper()
    length = len(seq)

    fv = FeatureVector(
        length=length,
        gc_ratio=gc_ratio,
        n_ratio=n_ratio,
    )

    if length < 4:
        return fv

    fv.kmer4_freq = _kmer4_frequencies(seq)
    fv.minimizer_sketch = _minimizer_sketch(seq, k=8, w=15)
    fv.cpg_oe = _cpg_oe(seq)
    fv.homopolymer_fraction = _homopolymer_fraction(seq)

    return fv


def kmer_cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two k-mer frequency profiles."""
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def jaccard_similarity(a: set[int], b: set[int]) -> float:
    """Jaccard similarity between two minimizer sketches."""
    if not a and not b:
        return 1.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _kmer4_frequencies(seq: str) -> dict[str, float]:
    """Count all 4-mers consisting of A/C/G/T only; normalise by count."""
    counts: dict[str, int] = {}
    total = 0
    for i in range(len(seq) - 3):
        kmer = seq[i:i + 4]
        if all(b in _BASES for b in kmer):
            counts[kmer] = counts.get(kmer, 0) + 1
            total += 1

    if total == 0:
        return {}
    return {k: v / total for k, v in counts.items()}


def _minimizer_sketch(seq: str, k: int = 8, w: int = 15) -> set[int]:
    """
    Compute a minimizer sketch using a simple polynomial rolling hash.

    For each window of `w` consecutive k-mers, the k-mer with the smallest
    hash is selected.  This gives a compact, locality-sensitive representation
    suitable for approximate similarity queries.
    """
    if len(seq) < k:
        return set()

    # Compute a polynomial hash for each k-mer.
    BASE = 31
    MOD = (1 << 61) - 1  # Mersenne prime

    hashes: list[int] = []
    h = 0
    b_pow = 1
    for i, ch in enumerate(seq[:k]):
        h = (h + (ord(ch) + 1) * b_pow) % MOD
        if i < k - 1:
            b_pow = (b_pow * BASE) % MOD

    hashes.append(h)
    for i in range(1, len(seq) - k + 1):
        h = (h - (ord(seq[i - 1]) + 1)) % MOD
        h = (h * pow(BASE, MOD - 2, MOD)) % MOD  # divide by BASE
        h = (h + (ord(seq[i + k - 1]) + 1) * b_pow) % MOD
        hashes.append(h)

    minimizers: set[int] = set()
    for i in range(len(hashes) - w + 1):
        minimizers.add(min(hashes[i:i + w]))

    return minimizers


def _cpg_oe(seq: str) -> float:
    """
    CpG observed / expected ratio.

    Elevated (≥ 0.6) in promoter regions of mammals; suppressed in most
    bacteria and invertebrates.  Useful for detecting human/mammalian
    contamination.

    Formula: (CpG count × length) / (C count × G count)
    Returns 0.0 for sequences with too few C or G bases.
    """
    length = len(seq)
    c_count = seq.count("C")
    g_count = seq.count("G")
    if c_count == 0 or g_count == 0:
        return 0.0

    cpg_count = sum(1 for i in range(length - 1) if seq[i] == "C" and seq[i + 1] == "G")
    expected = (c_count * g_count) / length
    if expected == 0.0:
        return 0.0
    return (cpg_count * length) / (c_count * g_count)


def _homopolymer_fraction(seq: str) -> float:
    """Fraction of bases that are part of a homopolymer run of ≥ 4 bases."""
    if not seq:
        return 0.0
    in_run = 0
    run_len = 1
    prev = seq[0]
    for ch in seq[1:]:
        if ch == prev:
            run_len += 1
        else:
            if run_len >= 4:
                in_run += run_len
            run_len = 1
        prev = ch
    if run_len >= 4:
        in_run += run_len
    return in_run / len(seq)
