"""
Checks on the checked-in models/registry/*.json files themselves.

The worker builds a route head with one output per label the head was trained
with and names the softmax outputs in that order: models.labels_for() reads
the entry's "label_set", falling back to its label_set_version's list. So a
route-head entry's label_set must equal LABEL_SETS_BY_VERSION[version][route],
order included, or its predictions would be silently mislabelled.

The v2 heads (Q1, t-1021-1) are registered as "candidate": they must not
change what is served until the B8 promote flow promotes them.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.inference.models import LABEL_SETS_BY_VERSION, ROUTE_LABEL_SETS, labels_for
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
    version = data.get("label_set_version", "v1")
    assert version in LABEL_SETS_BY_VERSION, name
    assert data["label_set"] == [str(l) for l in LABEL_SETS_BY_VERSION[version][data["route"]]], name


def test_label_set_versions_only_append():
    # Older heads index the same classes in newer data only if each older
    # list is a prefix of the newer one (evaluate_checkpoint relies on it).
    versions = list(LABEL_SETS_BY_VERSION)
    for older, newer in zip(versions, versions[1:]):
        for route, labels in LABEL_SETS_BY_VERSION[older].items():
            new = LABEL_SETS_BY_VERSION[newer][route]
            assert new[:len(labels)] == labels, (older, newer, route)


def test_v2_adds_genus_level_class_to_fish_and_plant_only():
    v1, v2 = LABEL_SETS_BY_VERSION["v1"], LABEL_SETS_BY_VERSION["v2"]
    changed = {r for r in v1 if v1[r] != v2[r]}
    assert changed == {"fish", "plant"}
    assert all(v2[r][-1] == "likely_taxonomic_group" for r in changed)
    assert ROUTE_LABEL_SETS is v2


def test_labels_for_prefers_the_entry_label_set():
    assert labels_for("fish", "v2", ["known_species", "possible_novelty", "low_quality_unusable"]) == [
        "known_species", "possible_novelty", "low_quality_unusable"]
    assert len(labels_for("fish", "v1")) == 3 and len(labels_for("fish", "v2")) == 4
    assert labels_for("fish") == list(ROUTE_LABEL_SETS["fish"])


def test_registry_parses_label_set():
    entry = ModelRegistry(REGISTRY_DIR).get("dnabert2_fish_v2")
    assert [str(l) for l in entry.label_set] == ["known_species", "possible_novelty", "low_quality_unusable"]


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
