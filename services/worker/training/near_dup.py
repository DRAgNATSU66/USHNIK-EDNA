"""
Near-duplicate grouping for leakage-safe splits (sprint Day 7, t-1020-1).

write_splits() already removes exact duplicates before splitting (the
2026-08-05 leak, THEORY_README §3). Exact dedup does not stop near-identical
copies (one mismatch, a shifted window, a sibling haplotype) landing on both
sides of the train/test line. QNA-011 Q4 measured this on the supplementary
data with 16-mer Jaccard >= 0.8 (MinHash, 64 hashes, 16 LSH bands):
fish novelty 53.5%, human known_species 55.9% of unique sequences had a
near-identical partner. This module reproduces that measure so the splitter
can keep each near-duplicate group inside one split.

Method
  * k-mers: every 16-mer with no N, 2-bit packed into a uint32.
  * MinHash: 64 multiply-shift hashes, h_i(x) = ((a_i * x + b_i) mod 2**64) >> 32,
    a_i odd, seeded. signature_i = min over the sequence's unique k-mers.
  * LSH: 16 bands x 4 rows. Sequences sharing any band are candidates.
  * A candidate pair is a near-duplicate when the fraction of equal signature
    positions (the MinHash estimate of Jaccard) is >= threshold (0.8).
  * Groups are the connected components of near-duplicate pairs (union-find).
    Inside a very large bucket only pairs against the first `max_bucket`
    members are compared, so the grouping is a lower bound there.

Sequences with no valid 16-mer (shorter than 16 bp, or N-rich) get no
signature and stay singletons.
"""
from __future__ import annotations

import numpy as np

K = 16
NUM_HASHES = 64
BANDS = 16
ROWS = NUM_HASHES // BANDS
DEFAULT_THRESHOLD = 0.8
_SEED = 20261020

_LUT = np.full(256, 255, dtype=np.uint8)
for _i, _b in enumerate(b"ACGT"):
    _LUT[_b] = _i
_SHIFTS = (np.arange(K - 1, -1, -1, dtype=np.uint32) * 2)


def _hash_params(num_hashes: int = NUM_HASHES, seed: int = _SEED) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    a = rng.integers(1, 2**63, size=num_hashes, dtype=np.uint64) * np.uint64(2) + np.uint64(1)
    b = rng.integers(0, 2**63, size=num_hashes, dtype=np.uint64)
    return a, b


_A, _B = _hash_params()


def kmer_codes(seq: str, k: int = K) -> np.ndarray:
    """Unique 2-bit-packed k-mers of `seq` that contain only A/C/G/T."""
    if len(seq) < k:
        return np.empty(0, dtype=np.uint32)
    codes = _LUT[np.frombuffer(seq.upper().encode("ascii"), dtype=np.uint8)]
    win = np.lib.stride_tricks.sliding_window_view(codes, k)
    valid = (win != 255).all(axis=1)
    if not valid.any():
        return np.empty(0, dtype=np.uint32)
    win = win[valid].astype(np.uint32)
    packed = np.bitwise_or.reduce(win << _SHIFTS[-k:], axis=1)
    return np.unique(packed)


def signature(seq: str) -> np.ndarray | None:
    kmers = kmer_codes(seq)
    if kmers.size == 0:
        return None
    x = kmers.astype(np.uint64)[:, None]
    with np.errstate(over="ignore"):
        h = (x * _A[None, :] + _B[None, :]) >> np.uint64(32)
    return h.min(axis=0).astype(np.uint32)


def signatures(seqs: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """(sig matrix [n, NUM_HASHES] uint32, has_sig bool[n])."""
    sig = np.zeros((len(seqs), NUM_HASHES), dtype=np.uint32)
    has = np.zeros(len(seqs), dtype=bool)
    for i, s in enumerate(seqs):
        v = signature(s)
        if v is not None:
            sig[i] = v
            has[i] = True
    return sig, has


class _UnionFind:
    def __init__(self, n: int):
        self.parent = np.arange(n)

    def find(self, x: int) -> int:
        p = self.parent
        root = x
        while p[root] != root:
            root = p[root]
        while p[x] != root:
            p[x], x = root, p[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if ra < rb:
                self.parent[rb] = ra
            else:
                self.parent[ra] = rb


def candidate_buckets(sig: np.ndarray, has: np.ndarray) -> list[np.ndarray]:
    """Index arrays of sequences sharing one LSH band (buckets of size >= 2)."""
    idx = np.flatnonzero(has)
    out: list[np.ndarray] = []
    if idx.size < 2:
        return out
    for band in range(BANDS):
        cols = sig[idx, band * ROWS:(band + 1) * ROWS]
        # one uint64-ish key per row via a void view, then group equal keys
        keys = np.ascontiguousarray(cols).view(np.dtype((np.void, cols.dtype.itemsize * ROWS))).ravel()
        order = np.argsort(keys, kind="stable")
        sk = keys[order]
        breaks = np.flatnonzero(sk[1:] != sk[:-1]) + 1
        for grp in np.split(order, breaks):
            if grp.size >= 2:
                out.append(idx[grp])
    return out


def near_duplicate_groups(seqs: list[str], threshold: float = DEFAULT_THRESHOLD,
                          max_bucket: int = 2000,
                          sig: tuple[np.ndarray, np.ndarray] | None = None) -> np.ndarray:
    """Group id per sequence; sequences in one group are linked by a chain of
    near-duplicate pairs (estimated 16-mer Jaccard >= threshold)."""
    n = len(seqs)
    if n == 0:
        return np.empty(0, dtype=np.int64)
    S, has = sig if sig is not None else signatures(seqs)
    uf = _UnionFind(n)
    need = int(np.ceil(threshold * NUM_HASHES))
    for members in candidate_buckets(S, has):
        m = members if members.size <= max_bucket else members[:max_bucket]
        sub = S[m]
        for j in range(len(m) - 1):
            eq = (sub[j + 1:] == sub[j]).sum(axis=1)
            for t in np.flatnonzero(eq >= need):
                uf.union(int(m[j]), int(m[j + 1 + t]))
        if members.size > max_bucket:
            # tail members: compare against the first max_bucket only
            for extra in members[max_bucket:]:
                eq = (sub == S[extra]).sum(axis=1)
                for t in np.flatnonzero(eq >= need):
                    uf.union(int(extra), int(m[t]))
    return np.array([uf.find(i) for i in range(n)], dtype=np.int64)


def cross_set_near_duplicates(query: list[str], reference: list[str], threshold: float = DEFAULT_THRESHOLD,
                              max_bucket: int = 2000) -> np.ndarray:
    """Bool per query sequence: True if some reference sequence is a
    near-duplicate (estimated 16-mer Jaccard >= threshold). Used by the
    leakage check (test vs train, etc.)."""
    if not query or not reference:
        return np.zeros(len(query), dtype=bool)
    Sq, hq = signatures(query)
    Sr, hr = signatures(reference)
    S = np.vstack([Sq, Sr])
    has = np.concatenate([hq, hr])
    nq = len(query)
    need = int(np.ceil(threshold * NUM_HASHES))
    hit = np.zeros(nq, dtype=bool)
    for members in candidate_buckets(S, has):
        qs = members[members < nq]
        rs = members[members >= nq]
        if qs.size == 0 or rs.size == 0:
            continue
        qs = qs[~hit[qs]]
        if qs.size == 0:
            continue
        rs = rs[:max_bucket]
        R = S[rs]
        for q in qs:
            if ((R == S[q]).sum(axis=1) >= need).any():
                hit[q] = True
    return hit
