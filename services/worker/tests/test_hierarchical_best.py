from __future__ import annotations

import pytest

from app.inference.models import SequenceResultClass as C
from app.inference.predictor import hierarchical_best

KS, NOV, LTG = C.known_species, C.possible_novelty, C.likely_taxonomic_group


def test_no_tau_is_plain_argmax():
    assert hierarchical_best({KS: 0.3, NOV: 0.4, LTG: 0.3}, None) == (NOV, 0.4)


def test_parent_class_beats_novelty_and_ltg_needs_the_share():
    scores = {KS: 0.3, NOV: 0.4, LTG: 0.3}
    assert hierarchical_best(scores, 0.76) == (KS, pytest.approx(0.6))    # share .5
    assert hierarchical_best(scores, 0.4) == (LTG, pytest.approx(0.6))
    assert hierarchical_best({KS: 0.1, NOV: 0.1, LTG: 0.8}, 0.76) == (LTG, pytest.approx(0.9))


def test_other_class_wins_when_above_the_parent():
    assert hierarchical_best({KS: 0.2, NOV: 0.7, LTG: 0.1}, 0.76) == (NOV, 0.7)


def test_head_without_ltg_ignores_tau():
    assert hierarchical_best({KS: 0.6, NOV: 0.4}, 0.76) == (KS, 0.6)
