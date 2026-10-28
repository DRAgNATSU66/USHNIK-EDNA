"""
A non-local base_model loads from the Hugging Face Hub only when the registry
pins it to a commit (base_model_revision); bandit B615 in CI flags unpinned
from_pretrained calls, and an unpinned repo with trust_remote_code would run
whatever code the repo holds today.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest.importorskip("torch")

from app.inference import loader  # noqa: E402
from app.inference.models import ModelRegistryEntry  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _entry(base_model: str, revision: str | None = None) -> ModelRegistryEntry:
    return ModelRegistryEntry(
        model_id="test_hub_head", route="fish", base_model=base_model,
        head_type="sequence_classification", embedding_dim=8, label_set_version="v1",
        status="experimental", artifact_uri="unused.pt", base_model_revision=revision,
    )


@pytest.mark.parametrize("rev", [None, "", "main", "v1.0", COMMIT[:7], COMMIT + "0", "g" * 40])
def test_unpinned_or_malformed_revision_is_refused(rev):
    with pytest.raises(ValueError, match="unpinned Hub download"):
        loader.hub_revision(_entry("InstaDeepAI/some-model", rev))


def test_full_commit_is_accepted_and_normalised():
    assert loader.hub_revision(_entry("InstaDeepAI/some-model", " " + COMMIT.upper())) == COMMIT


def test_load_refuses_before_any_download():
    with patch.object(loader, "AutoTokenizer") as tok:
        assert loader._load(_entry("InstaDeepAI/some-model")) is None
        tok.from_pretrained.assert_not_called()


def test_local_backbone_needs_no_revision(tmp_path):
    with patch.object(loader, "AutoTokenizer") as tok, patch.object(loader, "AutoConfig") as cfg, \
            patch.object(loader, "AutoModel") as model:
        cfg.from_pretrained.return_value.auto_map = {}
        assert loader._load(_entry(str(tmp_path))) is not None
    assert tok.from_pretrained.call_args.kwargs["revision"] is None
    assert model.from_pretrained.call_args.kwargs["revision"] is None
