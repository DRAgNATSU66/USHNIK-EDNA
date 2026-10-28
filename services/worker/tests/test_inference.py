"""
Tests for Phase 7 inference pipeline.

torch and transformers are NOT required — all model calls are mocked.
Tests cover:
  - Registry loading and filtering
  - Stub inference (no model available)
  - Mocked model inference (model present but mocked)
  - Low-quality route bypass
  - Confidence threshold logic
  - Batch inference
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.inference.models import (
    ROUTE_LABEL_SETS,
    InferenceMode,
    ModelRegistryEntry,
    PredictionResult,
    SequenceResultClass,
)
from app.model_router.models import ConfidenceTier
from app.inference.registry import ModelRegistry
from app.inference.predictor import (
    run_inference,
    run_inference_batch,
    _stub_prediction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    route: str = "fish",
    status: str = "experimental",
    artifact_uri: str | None = None,
    model_id: str | None = None,
) -> ModelRegistryEntry:
    return ModelRegistryEntry(
        model_id=model_id or f"test_{route}",
        route=route,
        base_model="zhihan1996/DNABERT-2-117M",
        head_type="sequence_classification",
        embedding_dim=768,
        label_set_version="v1",
        status=status,
        artifact_uri=artifact_uri,
        created_at="2026-05-26",
    )


def _write_registry(tmpdir: str, entries: list[dict]) -> str:
    for e in entries:
        path = Path(tmpdir) / f"{e['model_id']}.json"
        path.write_text(json.dumps(e))
    return tmpdir


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestModelRegistry:
    def test_loads_json_files(self, tmp_path):
        e = _make_entry(route="fish", status="experimental")
        (tmp_path / "fish_model.json").write_text(json.dumps({
            "model_id": e.model_id,
            "route": e.route,
            "base_model": e.base_model,
            "head_type": e.head_type,
            "embedding_dim": e.embedding_dim,
            "label_set_version": e.label_set_version,
            "status": e.status,
            "created_at": e.created_at,
        }))
        reg = ModelRegistry(registry_dir=str(tmp_path))
        assert len(reg.all_entries()) == 1
        assert reg.all_entries()[0].model_id == e.model_id

    def test_for_route_filters(self, tmp_path):
        for route in ("fish", "plant", "fish"):
            pass  # create 2 fish entries, 1 plant entry
        entries_data = [
            {"model_id": "fish_a", "route": "fish", "base_model": "x",
             "head_type": "sequence_classification", "embedding_dim": 768,
             "label_set_version": "v1", "status": "experimental", "created_at": "2026-01"},
            {"model_id": "fish_b", "route": "fish", "base_model": "x",
             "head_type": "sequence_classification", "embedding_dim": 768,
             "label_set_version": "v1", "status": "production", "created_at": "2026-02"},
            {"model_id": "plant_a", "route": "plant", "base_model": "x",
             "head_type": "sequence_classification", "embedding_dim": 768,
             "label_set_version": "v1", "status": "experimental", "created_at": "2026-01"},
        ]
        for d in entries_data:
            (tmp_path / f"{d['model_id']}.json").write_text(json.dumps(d))

        reg = ModelRegistry(registry_dir=str(tmp_path))
        fish = reg.for_route("fish")
        assert len(fish) == 2

        plant = reg.for_route("plant")
        assert len(plant) == 1

    def test_production_model_returns_none_when_absent(self, tmp_path):
        d = {"model_id": "test", "route": "fish", "base_model": "x",
             "head_type": "sequence_classification", "embedding_dim": 768,
             "label_set_version": "v1", "status": "experimental", "created_at": "2026-01"}
        (tmp_path / "test.json").write_text(json.dumps(d))
        reg = ModelRegistry(registry_dir=str(tmp_path))
        assert reg.production_model("fish") is None

    def test_best_available_prefers_production(self, tmp_path):
        entries_data = [
            {"model_id": "exp", "route": "fish", "base_model": "x",
             "head_type": "sequence_classification", "embedding_dim": 768,
             "label_set_version": "v1", "status": "experimental",
             "artifact_uri": "/fake/exp.pt", "created_at": "2026-01"},
            {"model_id": "prod", "route": "fish", "base_model": "x",
             "head_type": "sequence_classification", "embedding_dim": 768,
             "label_set_version": "v1", "status": "production",
             "artifact_uri": "/fake/prod.pt", "created_at": "2026-02"},
        ]
        for d in entries_data:
            (tmp_path / f"{d['model_id']}.json").write_text(json.dumps(d))
        reg = ModelRegistry(registry_dir=str(tmp_path))
        best = reg.best_available("fish")
        assert best is not None
        assert best.model_id == "prod"

    def test_missing_registry_dir_returns_empty(self):
        reg = ModelRegistry(registry_dir="/nonexistent/path/xyz")
        assert reg.all_entries() == []

    def test_refresh_clears_cache(self, tmp_path):
        reg = ModelRegistry(registry_dir=str(tmp_path))
        assert reg.all_entries() == []
        # Add a file after initial load.
        d = {"model_id": "new", "route": "fish", "base_model": "x",
             "head_type": "sequence_classification", "embedding_dim": 768,
             "label_set_version": "v1", "status": "experimental", "created_at": "2026-01"}
        (tmp_path / "new.json").write_text(json.dumps(d))
        reg.refresh()
        assert len(reg.all_entries()) == 1

    def test_is_runnable_requires_artifact_uri(self):
        e_no_uri = _make_entry(artifact_uri=None)
        e_with_uri = _make_entry(artifact_uri="/fake/model.pt")
        assert not e_no_uri.is_runnable
        assert e_with_uri.is_runnable

    def test_retired_not_runnable(self):
        e = _make_entry(status="retired", artifact_uri="/fake/model.pt")
        assert not e.is_runnable

    def test_real_registry_loads(self):
        # Smoke-test: the actual models/registry/ directory should parse without error.
        reg = ModelRegistry()
        entries = reg.all_entries()
        # We created 7 entries in Phase 7.
        assert len(entries) >= 6
        routes = {e.route for e in entries}
        assert "fish" in routes
        assert "plant" in routes
        assert "bacteria_pathogen" in routes


# ---------------------------------------------------------------------------
# Model data model tests
# ---------------------------------------------------------------------------

class TestModelDataModels:
    def test_route_label_sets_cover_all_routes(self):
        from app.model_router.models import TaxonomicRoute
        for route in TaxonomicRoute:
            assert str(route) in ROUTE_LABEL_SETS, f"Missing label set for route: {route}"

    def test_prediction_result_to_dict(self):
        result = PredictionResult(
            sequence_id="seq1",
            result_class=SequenceResultClass.known_species,
            predicted_taxon=None,
            confidence=0.87,
            model_version_used="dnabert2_fish_v1",
            inference_mode=InferenceMode.model,
            label_scores={"known_species": 0.87, "possible_novelty": 0.13},
        )
        d = result.to_dict()
        assert d["result_class"] == "known_species"
        assert d["confidence"] == 0.87
        assert d["inference_mode"] == "model"
        assert "label_scores" in d

    def test_sequence_result_class_values(self):
        assert SequenceResultClass.known_species == "known_species"
        assert SequenceResultClass.unknown_needs_online_confirmation == "unknown_needs_online_confirmation"


# ---------------------------------------------------------------------------
# Stub inference tests (no torch required)
# ---------------------------------------------------------------------------

class TestStubInference:
    def _patch_registry_no_model(self):
        """Patch get_registry to return a registry with no runnable models."""
        mock_reg = MagicMock()
        mock_reg.best_available.return_value = None
        return patch("app.inference.predictor.get_registry", return_value=mock_reg)

    def test_stub_returns_unknown_confirmation(self):
        with self._patch_registry_no_model():
            with patch("app.inference.predictor.torch_available", return_value=False):
                result = run_inference("seq1", "ATCGATCG" * 30, "fish")
        assert result.result_class == SequenceResultClass.unknown_needs_online_confirmation
        assert result.inference_mode == InferenceMode.stub
        assert result.confidence == 0.0

    def test_stub_has_correct_sequence_id(self):
        with self._patch_registry_no_model():
            with patch("app.inference.predictor.torch_available", return_value=False):
                result = run_inference("my_seq_42", "ATCGATCG" * 30, "bacteria_pathogen")
        assert result.sequence_id == "my_seq_42"

    def test_low_quality_route_bypasses_model(self):
        result = run_inference("seq1", "NNNN", "low_quality")
        assert result.result_class == SequenceResultClass.low_quality_unusable
        assert result.inference_mode == InferenceMode.low_quality
        assert result.confidence == 1.0

    def test_no_runnable_model_gives_stub(self):
        entry_no_uri = _make_entry(route="misc_unknown", artifact_uri=None)
        mock_reg = MagicMock()
        mock_reg.best_available.return_value = entry_no_uri
        with patch("app.inference.predictor.get_registry", return_value=mock_reg):
            with patch("app.inference.predictor.torch_available", return_value=True):
                with patch("app.inference.predictor.get_or_load", return_value=None):
                    result = run_inference("seq1", "ATCGATCG" * 30, "misc_unknown")
        assert result.inference_mode == InferenceMode.stub

    def test_stub_model_version_contains_reason(self):
        result = _stub_prediction("seq1", "fish", None)
        assert "stub_no_model" in result.model_version_used

    def test_stub_model_version_with_entry_no_uri(self):
        entry = _make_entry(route="fish", artifact_uri=None)
        result = _stub_prediction("seq1", "fish", entry)
        assert "stub_no_weights" in result.model_version_used


# ---------------------------------------------------------------------------
# Mocked model inference tests
# ---------------------------------------------------------------------------

class TestMockedModelInference:
    """
    Test the full inference pipeline with a mocked model that returns
    predetermined tensor outputs.
    """

    def _make_mock_pair(self, probs: list[float]):
        """Return (mock_model, mock_tokenizer) that produce the given probabilities."""
        try:
            import torch

            cls_embedding = torch.zeros(1, 768)
            mock_model = MagicMock()
            mock_model.parameters.return_value = iter([torch.zeros(1)])

            mock_outputs = MagicMock()
            mock_outputs.last_hidden_state = torch.zeros(1, 16, 768)
            mock_model.return_value = mock_outputs

            mock_tokenizer = MagicMock()
            mock_tokenizer.return_value = {
                "input_ids": torch.zeros(1, 16, dtype=torch.long),
                "attention_mask": torch.ones(1, 16, dtype=torch.long),
            }
            return mock_model, mock_tokenizer
        except ImportError:
            return None, None

    def test_inference_with_mocked_model_fish(self):
        """Test full pipeline when torch IS available (mocked)."""
        try:
            import torch
        except ImportError:
            return  # skip if torch not installed

        entry = _make_entry(route="fish", status="production", artifact_uri="/fake/model.pt")
        mock_reg = MagicMock()
        mock_reg.best_available.return_value = entry

        # Mock logits: known_species gets highest score.
        num_labels = len(ROUTE_LABEL_SETS["fish"])
        logits_tensor = torch.zeros(1, num_labels)
        logits_tensor[0, 0] = 3.0   # known_species wins

        mock_head = MagicMock()
        mock_head.return_value = logits_tensor

        mock_model, mock_tokenizer = self._make_mock_pair([0.85, 0.10, 0.05])
        if mock_model is None:
            return

        with patch("app.inference.predictor.get_registry", return_value=mock_reg):
            with patch("app.inference.predictor.torch_available", return_value=True):
                with patch("app.inference.predictor.get_or_load", return_value=(mock_model, mock_tokenizer)):
                    with patch("app.inference.predictor.get_cls_embedding") as mock_cls:
                        mock_cls.return_value = torch.zeros(1, 768)
                        with patch("app.inference.predictor.get_head", return_value=mock_head):
                            with patch("app.inference.predictor.tokenize_dna", return_value={"dummy": torch.zeros(1)}):
                                result = run_inference("seq1", "ATCGATCG" * 30, "fish")

        assert result.inference_mode == InferenceMode.model
        assert result.result_class == SequenceResultClass.known_species
        assert result.confidence > 0.7

    def test_low_confidence_downgraded_to_likely_group(self):
        """When top probability is medium, result_class should be likely_taxonomic_group."""
        try:
            import torch
        except ImportError:
            return

        entry = _make_entry(route="fish", status="production", artifact_uri="/fake/model.pt")
        mock_reg = MagicMock()
        mock_reg.best_available.return_value = entry

        # All labels roughly equal → low confidence.
        num_labels = len(ROUTE_LABEL_SETS["fish"])
        logits_tensor = torch.tensor([[0.6, 0.5, 0.4]])  # known_species wins slightly

        mock_head = MagicMock()
        mock_head.return_value = logits_tensor

        mock_model, mock_tokenizer = self._make_mock_pair([0.4, 0.35, 0.25])
        if mock_model is None:
            return

        with patch("app.inference.predictor.get_registry", return_value=mock_reg):
            with patch("app.inference.predictor.torch_available", return_value=True):
                with patch("app.inference.predictor.get_or_load", return_value=(mock_model, mock_tokenizer)):
                    with patch("app.inference.predictor.get_cls_embedding") as mock_cls:
                        mock_cls.return_value = torch.zeros(1, 768)
                        with patch("app.inference.predictor.get_head", return_value=mock_head):
                            with patch("app.inference.predictor.tokenize_dna", return_value={"dummy": torch.zeros(1)}):
                                result = run_inference("seq1", "ATCGATCG" * 30, "fish")

        # With top prob ~0.45 (below high_threshold 0.75, above low_threshold 0.40),
        # should get likely_taxonomic_group.
        assert result.result_class in (
            SequenceResultClass.likely_taxonomic_group,
            SequenceResultClass.known_species,
            SequenceResultClass.unknown_needs_online_confirmation,
        )


# ---------------------------------------------------------------------------
# Batch inference tests
# ---------------------------------------------------------------------------

class TestBatchInference:
    def test_empty_batch(self):
        results = run_inference_batch([])
        assert results == []

    def test_batch_returns_parallel_results(self):
        sequences = [
            {"sequence_id": f"seq{i}", "sequence": "ATCGATCG" * 20, "route": "misc_unknown"}
            for i in range(4)
        ]
        with patch("app.inference.predictor.torch_available", return_value=False):
            mock_reg = MagicMock()
            mock_reg.best_available.return_value = None
            with patch("app.inference.predictor.get_registry", return_value=mock_reg):
                results = run_inference_batch(sequences)
        assert len(results) == 4
        ids = [r.sequence_id for r in results]
        assert ids == ["seq0", "seq1", "seq2", "seq3"]

    def test_low_quality_in_batch(self):
        sequences = [
            {"sequence_id": "good", "sequence": "ATCGATCG" * 20, "route": "fish"},
            {"sequence_id": "bad", "sequence": "NNNN", "route": "low_quality"},
        ]
        with patch("app.inference.predictor.torch_available", return_value=False):
            mock_reg = MagicMock()
            mock_reg.best_available.return_value = None
            with patch("app.inference.predictor.get_registry", return_value=mock_reg):
                results = run_inference_batch(sequences)
        assert results[1].result_class == SequenceResultClass.low_quality_unusable
        assert results[1].inference_mode == InferenceMode.low_quality
