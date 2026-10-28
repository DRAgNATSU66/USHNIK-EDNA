"""
Inference tokenises each model at the max_length it was trained at.

Before this, predictor.py called tokenize_dna(..., max_length=512) for every
head, while training/finetune.py trains at --max-length 256 (QNA-022 open
issue). app/inference/max_length.py resolves the window from the model's own
record -- registry metrics, then the checkpoint's metrics.json, then the
backbone's tokenizer.json -- and only then falls back to the
inference_default_max_length setting.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import get_worker_settings
from app.inference import max_length as ml
from app.inference.max_length import (
    SOURCE_CHECKPOINT_METRICS,
    SOURCE_DEFAULT,
    SOURCE_REGISTRY,
    SOURCE_TOKENIZER_JSON,
    clear_max_length_cache,
    resolve_max_length,
)
from app.inference.models import ModelRegistryEntry
from app.inference.registry import ModelRegistry

REGISTRY_DIR = Path(__file__).resolve().parents[3] / "models" / "registry"


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_max_length_cache()
    yield
    clear_max_length_cache()


def _checkpoint(
    tmp_path: Path,
    metrics: dict | None = None,
    truncation: dict | None | str = "absent",
) -> tuple[str, str]:
    """Lay out <tmp>/head.pt, optional metrics.json, and backbone/tokenizer.json.
    Returns (artifact_uri, base_model)."""
    (tmp_path / "head.pt").write_bytes(b"")
    if metrics is not None:
        (tmp_path / "metrics.json").write_text(json.dumps(metrics))
    backbone = tmp_path / "backbone"
    backbone.mkdir()
    if truncation != "absent":
        (backbone / "tokenizer.json").write_text(json.dumps({"version": "1.0", "truncation": truncation}))
    return str(tmp_path / "head.pt"), str(backbone)


def _entry(artifact_uri: str | None, base_model: str, metrics: dict | None = None,
           model_id: str = "test_fish_head") -> ModelRegistryEntry:
    return ModelRegistryEntry(
        model_id=model_id,
        route="fish",
        base_model=base_model,
        head_type="sequence_classification",
        embedding_dim=768,
        label_set_version="v1",
        status="production",
        metrics=metrics or {},
        artifact_uri=artifact_uri,
        created_at="2026-10-19",
    )


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------

def test_registry_metrics_win(tmp_path):
    head, backbone = _checkpoint(tmp_path, metrics={"max_length": 300}, truncation={"max_length": 400})
    assert resolve_max_length(_entry(head, backbone, {"max_length": 200})) == (200, SOURCE_REGISTRY)


def test_checkpoint_metrics_when_registry_has_none(tmp_path):
    head, backbone = _checkpoint(tmp_path, metrics={"max_length": 300}, truncation={"max_length": 400})
    assert resolve_max_length(_entry(head, backbone)) == (300, SOURCE_CHECKPOINT_METRICS)


def test_tokenizer_json_truncation_when_no_metrics_record_it(tmp_path):
    # The v1 layout: metrics.json without max_length, tokenizer.json with it.
    head, backbone = _checkpoint(tmp_path, metrics={"test_accuracy": 0.9}, truncation={"max_length": 256})
    assert resolve_max_length(_entry(head, backbone)) == (256, SOURCE_TOKENIZER_JSON)


def test_default_when_nothing_is_recorded(tmp_path):
    # The v2 layout minus its metrics: newer transformers saves truncation null.
    head, backbone = _checkpoint(tmp_path, metrics={}, truncation=None)
    expected = get_worker_settings().inference_default_max_length
    assert resolve_max_length(_entry(head, backbone)) == (expected, SOURCE_DEFAULT)


def test_default_is_the_named_setting_not_a_literal(tmp_path):
    head, backbone = _checkpoint(tmp_path)
    fake = MagicMock(inference_default_max_length=123)
    with patch.object(ml, "get_worker_settings", return_value=fake):
        assert resolve_max_length(_entry(head, backbone)) == (123, SOURCE_DEFAULT)


def test_hub_id_backbone_and_no_artifact_fall_back_to_default():
    entry = _entry(None, "zhihan1996/DNABERT-2-117M")
    assert resolve_max_length(entry)[1] == SOURCE_DEFAULT


def test_setting_default_matches_finetune_default():
    # The fallback must equal what training/finetune.py trains at unless set.
    import re
    src = (Path(__file__).resolve().parents[1] / "training" / "finetune.py").read_text(encoding="utf-8")
    m = re.search(r'"--max-length", type=int, default=(\d+)', src)
    assert m is not None
    from app.config import WorkerSettings
    assert WorkerSettings.model_fields["inference_default_max_length"].default == int(m.group(1))


@pytest.mark.parametrize("bad", [0, -5, "256", 256.0, True, None, [256]])
def test_unusable_registry_values_are_skipped(tmp_path, bad):
    head, backbone = _checkpoint(tmp_path, metrics={"max_length": 300})
    assert resolve_max_length(_entry(head, backbone, {"max_length": bad})) == (300, SOURCE_CHECKPOINT_METRICS)


def test_unreadable_files_fall_through(tmp_path):
    head, backbone = _checkpoint(tmp_path)
    (tmp_path / "metrics.json").write_text("{not json")
    Path(backbone, "tokenizer.json").write_text("[1, 2]")
    assert resolve_max_length(_entry(head, backbone))[1] == SOURCE_DEFAULT


def test_result_is_cached_per_model(tmp_path):
    head, backbone = _checkpoint(tmp_path, metrics={"max_length": 300})
    entry = _entry(head, backbone)
    assert resolve_max_length(entry) == (300, SOURCE_CHECKPOINT_METRICS)
    (tmp_path / "metrics.json").write_text(json.dumps({"max_length": 999}))
    assert resolve_max_length(entry) == (300, SOURCE_CHECKPOINT_METRICS)
    clear_max_length_cache()
    assert resolve_max_length(entry) == (999, SOURCE_CHECKPOINT_METRICS)


def test_different_models_are_resolved_separately(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    head_a, bb_a = _checkpoint(a, metrics={"max_length": 128})
    head_b, bb_b = _checkpoint(b, metrics={"max_length": 512})
    assert resolve_max_length(_entry(head_a, bb_a, model_id="a"))[0] == 128
    assert resolve_max_length(_entry(head_b, bb_b, model_id="b"))[0] == 512


# ---------------------------------------------------------------------------
# The predictor uses it
# ---------------------------------------------------------------------------

def test_predictor_tokenises_at_resolved_max_length(tmp_path):
    torch = pytest.importorskip("torch")
    from app.inference.models import ROUTE_LABEL_SETS
    from app.inference.predictor import run_inference

    head_path, backbone = _checkpoint(tmp_path)
    entry = _entry(head_path, backbone, {"max_length": 192})
    reg = MagicMock()
    reg.best_available.return_value = entry
    head = MagicMock(return_value=torch.zeros(1, len(ROUTE_LABEL_SETS["fish"])))
    with patch("app.inference.predictor.get_registry", return_value=reg), \
         patch("app.inference.predictor.torch_available", return_value=True), \
         patch("app.inference.predictor.get_or_load", return_value=(MagicMock(), MagicMock())), \
         patch("app.inference.predictor.get_head", return_value=head), \
         patch("app.inference.predictor.get_cls_embedding", return_value=torch.zeros(1, 768)), \
         patch("app.inference.predictor.tokenize_dna", return_value={"x": torch.zeros(1)}) as tok:
        result = run_inference("seq1", "ACGT" * 200, "fish")
    assert result.inference_mode == "model"
    assert tok.call_args.kwargs["max_length"] == 192


def test_tokenize_dna_passes_max_length_through():
    pytest.importorskip("torch")
    from app.inference.heads import tokenize_dna

    tokenizer = MagicMock(return_value={"input_ids": None})
    tokenize_dna("ACGT", tokenizer, max_length=256)
    kwargs = tokenizer.call_args.kwargs
    assert kwargs["max_length"] == 256
    assert kwargs["truncation"] is True and kwargs["padding"] == "max_length"


# ---------------------------------------------------------------------------
# The checked-in registry + local checkpoints
# ---------------------------------------------------------------------------

def _runnable_head_entries():
    reg = ModelRegistry(REGISTRY_DIR)
    return [e for e in reg.all_entries() if e.route != "router" and e.is_runnable]


@pytest.mark.parametrize("entry", _runnable_head_entries(), ids=lambda e: e.model_id)
def test_every_registered_head_has_a_recorded_max_length(entry):
    """Every DNABERT-2 head in models/registry resolves from its own record
    (not the default), and all of them were trained at 256."""
    if not entry.artifact_uri or not os.path.isfile(entry.artifact_uri):
        pytest.skip(f"checkpoint not on this machine: {entry.artifact_uri}")
    value, source = resolve_max_length(entry)
    assert source != SOURCE_DEFAULT, entry.model_id
    assert value == 256, (entry.model_id, value, source)
