"""
Checks on the checked-in models/registry/*.json files themselves.

The worker builds a route head with len(ROUTE_LABEL_SETS[route]) outputs and
names the softmax outputs in that order (heads.get_head, predictor._run_model).
It does not read an entry's "label_set" field. So every route-head entry's
label_set must equal ROUTE_LABEL_SETS[route], order included, or its
predictions would be silently mislabelled. If a head is ever trained on a
different label set, this test fails until the worker reads per-entry label
sets.

The v2 heads (Q1, t-1021-1) are registered as "candidate": they must not
change what is served until the B8 promote flow promotes them.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.inference.models import ROUTE_LABEL_SETS
from app.inference.registry import ModelRegistry

REGISTRY_DIR = Path(__file__).resolve().parents[3] / "models" / "registry"
ROUTES = ["fish", "plant", "bacteria_pathogen", "animal_general", "human_domestic_contamination", "misc_unknown"]


def _route_head_entries() -> list[tuple[str, dict]]:
    out = []
    for f in sorted(REGISTRY_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("route") in ROUTES:
            out.append((f.name, data))
    return out


ENTRIES = _route_head_entries()


@pytest.mark.parametrize("name,data", ENTRIES, ids=[n for n, _ in ENTRIES])
def test_label_set_matches_worker_label_order(name, data):
    if "label_set" not in data:
        pytest.skip(f"{name} declares no label_set")
    assert data["label_set"] == [str(l) for l in ROUTE_LABEL_SETS[data["route"]]], name


@pytest.mark.parametrize("name,data", ENTRIES, ids=[n for n, _ in ENTRIES])
def test_notes_are_plain_text(name, data):
    # Catch UTF-8 read as cp1252 ("â€”" for an em dash) in hand-written notes.
    notes = data.get("notes", "")
    assert "â€" not in notes and "Ã" not in notes, name


# Serving state after the 2026-10-19 promotion (QNA-023): four v2 heads are
# production and served; plant and bacteria v2 stay candidates and v1 serves.
PROMOTED_V2 = {"fish", "animal_general", "human_domestic_contamination", "misc_unknown"}


def test_v2_head_selection_matches_promotion():
    reg = ModelRegistry(REGISTRY_DIR)
    v2 = [e for e in reg.all_entries() if e.model_id.startswith("dnabert2_") and e.model_id.endswith("_v2")]
    assert len(v2) == 6
    for e in v2:
        assert e.label_set_version == "v1", e.model_id
        selected = reg.best_available(e.route)
        if str(e.route) in PROMOTED_V2:
            assert e.status == "production", e.model_id
            assert selected is not None and selected.model_id == e.model_id
        else:
            assert e.status == "candidate", e.model_id
            assert selected is None or selected.model_id != e.model_id
