"""
The frontend Playwright suite (web_frontend/e2e, t-1029-2) mocks the API with
fixtures recorded from this app by scripts/gen_e2e_fixtures.py. This test
regenerates them and fails if the committed files differ, so a response-shape
change cannot leave the e2e suite passing against a stale contract.

Fix a failure by running, from the repo root:
    services/api/.venv/bin/python services/api/scripts/gen_e2e_fixtures.py
and committing the updated web_frontend/e2e/fixtures/api/*.json.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
GEN_PATH = API_DIR / "scripts" / "gen_e2e_fixtures.py"
FIXTURE_DIR = API_DIR.parents[1] / "web_frontend" / "e2e" / "fixtures" / "api"

# models/registry/*.json is real repo data that other work adds to; pinning
# the full body here would fail API CI on every new registry entry. Its
# shape (top-level keys, per-entry keys the pages read) is still checked.
SHAPE_ONLY = {"models_registry"}


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_e2e_fixtures", GEN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def generated():
    gen = _load_generator()
    import asyncio
    return gen, asyncio.run(gen.generate())


@pytest.mark.skipif(not FIXTURE_DIR.is_dir(), reason="web_frontend not checked out next to services/api")
def test_every_fixture_is_committed(generated):
    gen, fixtures = generated
    committed = {p.stem for p in FIXTURE_DIR.glob("*.json")}
    assert committed == set(fixtures), "fixture set differs; rerun scripts/gen_e2e_fixtures.py"


@pytest.mark.skipif(not FIXTURE_DIR.is_dir(), reason="web_frontend not checked out next to services/api")
def test_committed_fixtures_match_live_responses(generated):
    gen, fixtures = generated
    stale = []
    for name, body in fixtures.items():
        path = FIXTURE_DIR / f"{name}.json"
        committed = json.loads(path.read_text(encoding="utf-8"))
        if name in SHAPE_ONLY:
            assert set(committed) == set(body), f"{name}: top-level keys changed"
            for entry in committed["models"]:
                assert {"model_id", "route", "status", "metrics"} <= set(entry), f"{name}: entry shape changed"
            continue
        if committed != body:
            stale.append(name)
    assert not stale, f"stale e2e fixtures {stale}; rerun scripts/gen_e2e_fixtures.py"
