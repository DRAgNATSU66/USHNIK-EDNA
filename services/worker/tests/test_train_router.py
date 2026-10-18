"""
Router trainer strand handling (B23): reverse-complement augmentation, and a
dev sweep that only ever selects a strand-invariant configuration.
"""
import os
import random
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest.importorskip("sklearn")
pytest.importorskip("scipy")

from training import train_router as tr  # noqa: E402


def _seqs(n, gc, seed):
    rng = random.Random(seed)
    w = [(1 - gc) / 2, gc / 2, gc / 2, (1 - gc) / 2]
    return ["".join(rng.choices("ACGT", weights=w, k=60)) for _ in range(n)]


def test_revcomp():
    assert tr.revcomp("AACGTN") == "NACGTT"
    assert tr.revcomp(tr.revcomp("ACGGTCA")) == "ACGGTCA"


def test_rc_augment_stacks_reverse_complements():
    seqs = ["AACCGGTTAC", "GGGATCCATT"]
    y = np.array([0, 3])
    A, yA = tr.train_matrix(seqs, y, 3, "rc_augment")
    assert A.shape == (4, 64)
    assert yA.tolist() == [0, 3, 0, 3]
    rc = tr.featurise([tr.revcomp(s) for s in seqs], 3, "forward")
    assert (A[2:] != rc).nnz == 0
    F, yF = tr.train_matrix(seqs, y, 3, "forward")
    assert F.shape == (2, 64) and yF is y


def test_canonical_features_identical_on_both_strands():
    seqs = _seqs(5, 0.5, 1)
    a = tr.featurise(seqs, 4, "canonical")
    b = tr.featurise([tr.revcomp(s) for s in seqs], 4, "canonical")
    assert (a != b).nnz == 0


def test_sweep_selects_only_strand_invariant_configs():
    # Six "routes" separated by GC content; forward-only configs can score well
    # forward, but selection must ignore them.
    gcs = [0.2, 0.3, 0.4, 0.6, 0.7, 0.8]
    Xtr, ytr, Xdv, ydv = [], [], [], []
    for i, gc in enumerate(gcs):
        Xtr += _seqs(30, gc, i)
        ytr += [i] * 30
        Xdv += _seqs(10, gc, 100 + i)
        ydv += [i] * 10
    out = tr.dev_sweep(Xtr, np.array(ytr), Xdv, np.array(ydv), [2], seed=0)
    assert len(out["rows"]) == 9  # 3 strand modes x 3 models
    assert out["best"]["strand"] in tr.STRAND_INVARIANT
    best_score = out["best"]["dev_worst_strand_balanced_accuracy"]
    assert all(r["dev_worst_strand_balanced_accuracy"] <= best_score for r in out["rows"] if r["strand_invariant"])
    for r in out["rows"]:
        assert r["dev_worst_strand_balanced_accuracy"] == min(r["dev_fwd_balanced_accuracy"],
                                                               r["dev_rc_balanced_accuracy"])
        if r["strand"] == "canonical":
            assert r["dev_fwd_balanced_accuracy"] == r["dev_rc_balanced_accuracy"]
