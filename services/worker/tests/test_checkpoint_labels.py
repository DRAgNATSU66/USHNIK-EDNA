"""evaluate_checkpoint.checkpoint_labels: score old heads on new label sets."""
from __future__ import annotations

import pytest

pytest.importorskip("torch")

from app.inference.models import LABEL_SETS_BY_VERSION  # noqa: E402
from training.evaluate_checkpoint import checkpoint_labels  # noqa: E402

V2_FISH = [str(label) for label in LABEL_SETS_BY_VERSION["v2"]["fish"]]


def test_recorded_label_set_is_used():
    assert checkpoint_labels("fish", {"label_set": V2_FISH}, V2_FISH) == V2_FISH


def test_old_checkpoint_resolved_by_num_classes():
    # fish_v2 (2026-10-19) recorded only num_classes=3.
    assert checkpoint_labels("fish", {"num_classes": 3}, V2_FISH) == V2_FISH[:3]


def test_unchanged_route_old_checkpoint():
    animal = [str(label) for label in LABEL_SETS_BY_VERSION["v2"]["animal_general"]]
    assert checkpoint_labels("animal_general", {"num_classes": 3}, animal) == animal


def test_unknown_size_is_refused():
    with pytest.raises(SystemExit):
        checkpoint_labels("fish", {"num_classes": 7}, V2_FISH)


def test_non_prefix_is_refused():
    with pytest.raises(SystemExit):
        checkpoint_labels("fish", {"label_set": ["possible_novelty", "known_species"]}, V2_FISH)
