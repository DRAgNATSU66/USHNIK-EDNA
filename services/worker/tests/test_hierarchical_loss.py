from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from training.finetune import HierarchicalLoss  # noqa: E402

# fish label set v2: ks, novelty, low_quality, ltg
KS, NOV, LQ, LTG = 0, 1, 2, 3


def _loss(leaf_weight=0.0, weight=(1.0, 1.0, 1.0)):
    return HierarchicalLoss(KS, LTG, 4, torch.tensor(weight), leaf_weight)


def test_parent_loss_is_ce_on_merged_probabilities():
    torch.manual_seed(0)
    logits = torch.randn(6, 4)
    labels = torch.tensor([KS, LTG, NOV, LQ, LTG, KS])
    p = torch.softmax(logits, dim=1)
    merged = torch.stack([p[:, KS] + p[:, LTG], p[:, NOV], p[:, LQ]], dim=1)
    parent = torch.tensor([0, 0, 1, 2, 0, 0])
    expected = torch.nn.functional.nll_loss(torch.log(merged), parent)
    assert torch.allclose(_loss()(logits, labels), expected, atol=1e-5)


def test_leaf_term_only_on_known_or_ltg_rows():
    logits = torch.tensor([[0.0, 5.0, 0.0, 0.0], [2.0, 0.0, 0.0, 0.0]])
    labels = torch.tensor([NOV, LTG])
    with_leaf = _loss(leaf_weight=1.0).per_example(logits, labels)
    without = _loss().per_example(logits, labels)
    assert torch.isclose(with_leaf[0], without[0])           # novelty row: no leaf loss
    leaf = torch.nn.functional.cross_entropy(logits[1:, [KS, LTG]], torch.tensor([1]))
    assert torch.isclose(with_leaf[1] - without[1], leaf)


def test_class_weights_apply_to_parent_classes():
    logits = torch.zeros(2, 4)
    labels = torch.tensor([LTG, NOV])
    w = _loss(weight=(0.5, 3.0, 1.0)).example_weights(labels)
    assert w.tolist() == [0.5, 3.0]                           # LTG row weighs as its parent, known


def test_parent_preds_never_emit_ltg():
    logits = torch.tensor([[0.0, 0.0, 0.0, 9.0], [0.0, 1.5, 0.0, 1.0]])
    # row 1: novelty 1.5 beats the parent logsumexp(0, 1) = 1.31
    assert _loss().parent_preds(logits).tolist() == [KS, NOV]
    logits[1, KS] = 1.0                                       # logsumexp(1, 1) = 1.69 > 1.5
    assert _loss().parent_preds(logits).tolist() == [KS, KS]
