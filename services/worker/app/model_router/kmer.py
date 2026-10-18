"""
Exact k-mer featurisation for the learned route classifier.

One function, used by both training (training/train_router.py) and inference
(model_router/learned.py), so the two cannot drift into different features.

A k-mer is encoded as its base-4 integer (A=0, C=1, G=2, T=3; U is read as T),
so the feature space is exact (4**k columns: 65,536 at k=8 for router v1,
262,144 at k=9 for v2) and needs no hashing. Windows containing any other character (N, IUPAC codes, gaps) are
skipped rather than guessed.

With canonical=True a k-mer and its reverse complement share one index (the
smaller of the two), which makes the features strand-invariant: an eDNA read
sequenced from the opposite strand gets the same vector.

The returned vector is sparse (unique indices + values) and L2-normalised, so a
sequence's length does not change its scale.
"""
from __future__ import annotations

import numpy as np

# ASCII -> base code; everything that is not A/C/G/T/U maps to -1 (invalid).
_CODE = np.full(256, -1, dtype=np.int8)
for _ch, _v in (("A", 0), ("C", 1), ("G", 2), ("T", 3), ("U", 3)):
    _CODE[ord(_ch)] = _v
    _CODE[ord(_ch.lower())] = _v


def n_features(k: int) -> int:
    return 4 ** k


def kmer_indices(sequence: str, k: int, canonical: bool = False) -> np.ndarray:
    """Integer index of every valid k-mer window in `sequence` (int64 array).

    Windows that contain a non-ACGT character are dropped. Returns an empty
    array when the sequence is shorter than k or has no valid window.
    """
    if k < 1 or k > 12:
        raise ValueError(f"k must be in 1..12, got {k}")
    raw = np.frombuffer(sequence.encode("ascii", errors="replace"), dtype=np.uint8)
    if raw.size < k:
        return np.empty(0, dtype=np.int64)
    codes = _CODE[raw].astype(np.int64)
    windows = np.lib.stride_tricks.sliding_window_view(codes, k)
    valid = (windows >= 0).all(axis=1)
    if not valid.any():
        return np.empty(0, dtype=np.int64)
    windows = windows[valid]
    powers = 4 ** np.arange(k - 1, -1, -1, dtype=np.int64)  # most significant first
    fwd = windows @ powers
    if not canonical:
        return fwd
    # Reverse complement of window w is (3 - w) read right-to-left, i.e. the
    # complemented bases weighted by ascending powers.
    rev = (3 - windows) @ powers[::-1]
    return np.minimum(fwd, rev)


def kmer_vector(sequence: str, k: int, canonical: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Sparse L2-normalised k-mer count vector: (indices int64, values float32).

    Both arrays are empty when the sequence has no valid k-mer.
    """
    idx = kmer_indices(sequence, k, canonical=canonical)
    if idx.size == 0:
        return idx, np.empty(0, dtype=np.float32)
    uniq, counts = np.unique(idx, return_counts=True)
    vals = counts.astype(np.float32)
    vals /= np.float32(np.sqrt(np.sum(vals * vals)))
    return uniq, vals


def kmer_matrix(sequences: list[str], k: int, canonical: bool = False):
    """CSR matrix (n_sequences x 4**k) of kmer_vector rows. Training-time helper;
    needs scipy, which inference does not."""
    import scipy.sparse as sp

    indptr = [0]
    indices: list[np.ndarray] = []
    data: list[np.ndarray] = []
    for s in sequences:
        i, v = kmer_vector(s, k, canonical=canonical)
        indices.append(i)
        data.append(v)
        indptr.append(indptr[-1] + i.size)
    return sp.csr_matrix(
        (
            np.concatenate(data) if data else np.empty(0, dtype=np.float32),
            np.concatenate(indices) if indices else np.empty(0, dtype=np.int64),
            np.asarray(indptr, dtype=np.int64),
        ),
        shape=(len(sequences), n_features(k)),
        dtype=np.float32,
    )
