from __future__ import annotations

import numpy as np

from training import hier_decode as hd

NAMES = ["known_species", "possible_novelty", "low_quality_unusable", "likely_taxonomic_group"]


def _d(probs, labels, heads=NAMES):
    return {"probs": np.array(probs, dtype=float), "labels": np.array(labels),
            "head_labels": list(heads), "label_names": NAMES}


def test_merged_known_beats_novelty_that_flat_argmax_would_pick():
    # P(ks)=.3 P(nov)=.4 P(ltg)=.3: flat argmax says novelty; known-or-LTG is .6
    d = _d([[0.3, 0.4, 0.0, 0.3]], [0])
    assert hd.decode(d, None)[0] == 1
    assert hd.decode(d, 1.0)[0] == 0          # tau=1 never emits LTG
    assert hd.decode(d, 0.6)[0] == 0          # share .5 <= .6
    assert hd.decode(d, 0.4)[0] == 3          # share .5 > .4


def test_prefix_head_without_ltg_is_plain_argmax_and_ltg_rows_count_wrong():
    d = _d([[0.9, 0.1, 0.0], [0.8, 0.2, 0.0]], [0, 3], heads=NAMES[:3])
    pred = hd.decode(d, 0.5)
    assert pred.tolist() == [0, 0]
    m = hd.metrics(d, pred, NAMES[:3])
    assert m["acc"] == 0.5 and m["acc_on_prod_classes"] == 1.0 and m["n_prod_class_rows"] == 1
    assert m["ltg_recall"] == 0.0


def test_choose_tau_is_smallest_meeting_the_dev_recall_target():
    # row 0 known with LTG share .7; row 1 LTG with share .9
    d = _d([[0.3, 0.0, 0.0, 0.7], [0.1, 0.0, 0.0, 0.9]], [0, 3])
    tau, sweep = hd.choose_tau(d, 1.0, NAMES[:3])
    assert tau == 0.7                         # .70 keeps row 0 known, still calls row 1 LTG
    row = next(s for s in sweep if s["tau"] == tau)
    assert row["known_species_recall"] == 1.0 and row["ltg_recall"] == 1.0
