"""
Missing / unloadable head weights must never produce inference_mode="model".

Before this fix heads.get_head logged a warning and returned a randomly
initialised head, and the predictor labelled its (meaningless) output as a
real model prediction.  Now get_head raises HeadUnavailableError and the
predictor returns a stub with stub_reason "head_missing" / "head_load_failed",
the same way the backbone-missing path stubs ("backbone_unavailable").
"""
from __future__ import annotations

import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

torch = pytest.importorskip("torch")

from app.inference import heads  # noqa: E402
from app.inference.heads import HeadUnavailableError, clear_head_cache, get_head  # noqa: E402
from app.inference.models import (  # noqa: E402
    LABEL_SETS_BY_VERSION,
    InferenceMode,
    ModelRegistryEntry,
)
from app.inference.predictor import run_inference  # noqa: E402

EMB_DIM = 768
# _entry() is a v1 fish head: 3 outputs, not the 4 of the current (v2) list.
V1_FISH = LABEL_SETS_BY_VERSION["v1"]["fish"]
NUM_CLASSES = len(V1_FISH)


@pytest.fixture(autouse=True)
def _fresh_head_cache():
    clear_head_cache()
    yield
    clear_head_cache()


def _entry(artifact_uri: str | None) -> ModelRegistryEntry:
    return ModelRegistryEntry(
        model_id="test_fish_head",
        route="fish",
        base_model="data:checkpoints/fish/backbone",
        head_type="sequence_classification",
        embedding_dim=EMB_DIM,
        label_set_version="v1",
        status="experimental",
        artifact_uri=artifact_uri,
        created_at="2026-10-15",
    )


def _save_trained_head(path, favour: int = 0, num_classes: int = NUM_CLASSES) -> None:
    """Write a valid head state_dict whose output strongly favours one label."""
    head = heads.DNAClassifierHead(EMB_DIM, num_classes)
    with torch.no_grad():
        head.classifier.weight.zero_()
        head.classifier.bias.zero_()
        head.classifier.bias[favour] = 10.0
    torch.save(head.state_dict(), path)


def _run_with_mocked_backbone(entry: ModelRegistryEntry):
    """run_inference with a mocked backbone but the REAL get_head."""
    reg = MagicMock()
    reg.best_available.return_value = entry
    pair = (MagicMock(), MagicMock())
    with patch("app.inference.predictor.get_registry", return_value=reg), \
         patch("app.inference.predictor.torch_available", return_value=True), \
         patch("app.inference.predictor.get_or_load", return_value=pair), \
         patch("app.inference.predictor.tokenize_dna", return_value={"x": torch.zeros(1)}), \
         patch("app.inference.predictor.get_cls_embedding", return_value=torch.zeros(1, EMB_DIM)):
        return run_inference("seq1", "ACGT" * 50, "fish")


# ---------------------------------------------------------------------------
# get_head
# ---------------------------------------------------------------------------

class TestGetHead:
    def test_no_path_raises_head_missing(self):
        with pytest.raises(HeadUnavailableError) as ei:
            get_head("fish", "m", EMB_DIM, head_weights_path=None)
        assert ei.value.reason == "head_missing"

    def test_nonexistent_file_raises_head_missing(self, tmp_path):
        with pytest.raises(HeadUnavailableError) as ei:
            get_head("fish", "m", EMB_DIM, head_weights_path=str(tmp_path / "head.pt"))
        assert ei.value.reason == "head_missing"

    def test_corrupt_file_raises_head_load_failed(self, tmp_path):
        bad = tmp_path / "head.pt"
        bad.write_bytes(b"not a torch file")
        with pytest.raises(HeadUnavailableError) as ei:
            get_head("fish", "m", EMB_DIM, head_weights_path=str(bad))
        assert ei.value.reason == "head_load_failed"

    def test_wrong_shape_raises_head_load_failed(self, tmp_path):
        p = tmp_path / "head.pt"
        torch.save(heads.DNAClassifierHead(EMB_DIM, NUM_CLASSES + 2).state_dict(), p)
        with pytest.raises(HeadUnavailableError) as ei:
            get_head("fish", "m", EMB_DIM, head_weights_path=str(p), labels=V1_FISH)
        assert ei.value.reason == "head_load_failed"

    def test_valid_file_loads_trained_weights(self, tmp_path):
        p = tmp_path / "head.pt"
        _save_trained_head(p, favour=1)
        head = get_head("fish", "m", EMB_DIM, head_weights_path=str(p), labels=V1_FISH)
        assert head is not None
        assert float(head.classifier.bias[1].detach()) == pytest.approx(10.0)

    def test_failure_logged_once_and_cached(self, tmp_path, caplog):
        missing = str(tmp_path / "head.pt")
        with caplog.at_level(logging.WARNING, logger="app.inference.heads"):
            for _ in range(3):
                with pytest.raises(HeadUnavailableError):
                    get_head("fish", "m", EMB_DIM, head_weights_path=missing)
        warnings = [r for r in caplog.records if "Head weights unavailable" in r.getMessage()]
        assert len(warnings) == 1
        assert "head_missing" in warnings[0].getMessage()


# ---------------------------------------------------------------------------
# predictor: head failures become stubs, never "model"
# ---------------------------------------------------------------------------

class TestPredictorHeadPaths:
    def test_missing_head_gives_stub_not_model(self, tmp_path):
        result = _run_with_mocked_backbone(_entry(str(tmp_path / "head.pt")))
        assert result.inference_mode == InferenceMode.stub
        assert result.stub_reason == "head_missing"
        assert result.label_scores == {}
        assert result.embedding is None
        assert result.confidence == 0.0
        assert result.model_version_used == "test_fish_head:stub_head_missing"
        assert result.to_dict()["stub_reason"] == "head_missing"

    def test_non_pt_artifact_uri_gives_head_missing(self):
        # artifact_uri that is not a .pt/.bin is never passed to get_head.
        result = _run_with_mocked_backbone(_entry("org/some-hub-model"))
        assert result.inference_mode == InferenceMode.stub
        assert result.stub_reason == "head_missing"

    def test_unloadable_head_gives_stub_not_model(self, tmp_path):
        bad = tmp_path / "head.pt"
        bad.write_bytes(b"\0")
        result = _run_with_mocked_backbone(_entry(str(bad)))
        assert result.inference_mode == InferenceMode.stub
        assert result.stub_reason == "head_load_failed"
        assert result.model_version_used == "test_fish_head:stub_head_load_failed"

    def test_valid_head_gives_model(self, tmp_path):
        p = tmp_path / "head.pt"
        _save_trained_head(p, favour=0)
        result = _run_with_mocked_backbone(_entry(str(p)))
        assert result.inference_mode == InferenceMode.model
        assert result.stub_reason is None
        assert result.result_class == V1_FISH[0]
        assert result.confidence > 0.99

    def test_backbone_missing_gives_stub_with_reason(self, tmp_path):
        p = tmp_path / "head.pt"
        _save_trained_head(p)
        reg = MagicMock()
        reg.best_available.return_value = _entry(str(p))
        with patch("app.inference.predictor.get_registry", return_value=reg), \
             patch("app.inference.predictor.torch_available", return_value=True), \
             patch("app.inference.predictor.get_or_load", return_value=None):
            result = run_inference("seq1", "ACGT" * 50, "fish")
        assert result.inference_mode == InferenceMode.stub
        assert result.stub_reason == "backbone_unavailable"

    def test_inference_exception_is_marked(self, tmp_path):
        p = tmp_path / "head.pt"
        _save_trained_head(p)
        reg = MagicMock()
        reg.best_available.return_value = _entry(str(p))
        with patch("app.inference.predictor.get_registry", return_value=reg), \
             patch("app.inference.predictor.torch_available", return_value=True), \
             patch("app.inference.predictor.get_or_load", return_value=(MagicMock(), MagicMock())), \
             patch("app.inference.predictor.tokenize_dna", side_effect=RuntimeError("boom")):
            result = run_inference("seq1", "ACGT" * 50, "fish")
        assert result.inference_mode == InferenceMode.stub
        assert result.stub_reason == "inference_error"

    def test_v1_head_is_not_built_at_the_v2_size(self, tmp_path):
        # Production fish v2 and plant v1 were trained on v1 lists; the v2
        # label set must not change the head they are loaded into.
        p = tmp_path / "head.pt"
        _save_trained_head(p, favour=2)
        result = _run_with_mocked_backbone(_entry(str(p)))
        assert result.inference_mode == InferenceMode.model
        assert list(result.label_scores) == [str(l) for l in V1_FISH]
        assert result.result_class == "low_quality_unusable"

    def test_v2_head_can_predict_the_genus_level_class(self, tmp_path):
        v2 = LABEL_SETS_BY_VERSION["v2"]["fish"]
        p = tmp_path / "head.pt"
        _save_trained_head(p, favour=3, num_classes=len(v2))
        entry = _entry(str(p))
        entry.label_set_version = "v2"
        entry.model_id = "test_fish_head_v2"
        result = _run_with_mocked_backbone(entry)
        assert result.inference_mode == InferenceMode.model
        assert result.result_class == "likely_taxonomic_group"
        assert len(result.label_scores) == 4
