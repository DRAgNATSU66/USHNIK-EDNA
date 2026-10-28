"""
B12: the Abyss GC-only fallback must be logged and visible.

Since B25 the first stage is the API's offline learned router
(app/abyss/learned_router.py), not an import of the worker's router.  When it
raises on a sequence, or is unavailable, the problem is logged once per
distinct error and every affected result carries router_error_fallback=True,
router_error="<reason>: <detail>", router_method="gc_fallback" and the reason
code "router_error_fallback".
"""
from __future__ import annotations

import logging

import pytest

import app.abyss.analysis as analysis
import app.abyss.learned_router as lr
from app.abyss.models import AbyssSequenceInput

SEQ = "ATGCGTACGTTAGCATGCATGCAAGTCGATCGATGCATGCATGCATCGA" * 3


def _inp(i: int = 0) -> AbyssSequenceInput:
    return AbyssSequenceInput(sequence_id=f"s{i}", sequence=SEQ)


class _Model:
    """Stands in for AbyssRouterModel; predict_proba is replaced per test."""
    model_id = "kmer_router_test"
    version = "vtest"
    k = 8
    sha256 = "0" * 64
    artifact_path = ""
    artifact_uri = ""

    def __init__(self, predict):
        self.predict_proba = predict


@pytest.fixture(autouse=True)
def _reset():
    analysis._LOGGED_FALLBACKS.clear()
    lr.reset_router()
    yield
    analysis._LOGGED_FALLBACKS.clear()
    lr.reset_router()


def test_router_exception_is_marked_on_result():
    def boom(_seq):
        raise RuntimeError("router exploded")

    lr.set_router(_Model(boom))
    r = analysis.run_abyss_analysis("exp_1", [_inp()]).results[0]
    assert r.router_error_fallback is True
    assert r.router_method == "gc_fallback"
    assert r.router_fallback_reason == "predict_error"
    assert r.router_error == "predict_error: RuntimeError: router exploded"
    assert r.reason_codes[0] == "router_error_fallback"
    # Still produces a GC-fallback route rather than failing the request.
    assert r.route in {"fish", "bacteria_pathogen", "misc_unknown", "human_domestic_contamination"}


def test_router_exception_logged_once_with_traceback(caplog):
    def boom(_seq):
        raise RuntimeError("router exploded")

    lr.set_router(_Model(boom))
    with caplog.at_level(logging.WARNING, logger="app.abyss.analysis"):
        res = analysis.run_abyss_analysis("exp_1", [_inp(i) for i in range(5)])
    assert all(r.router_error_fallback for r in res.results)
    recs = [r for r in caplog.records if "learned router failed" in r.getMessage()]
    assert len(recs) == 1
    assert recs[0].exc_info is not None
    assert "router exploded" in recs[0].getMessage()


def test_unavailable_router_logged_once(caplog):
    lr.set_router(None, reason="artifact_missing", detail="router.npz")
    with caplog.at_level(logging.WARNING, logger="app.abyss.analysis"):
        res = analysis.run_abyss_analysis("exp_1", [_inp(i) for i in range(5)])
    assert all(r.router_method == "gc_fallback" for r in res.results)
    assert all(r.router_error == "artifact_missing: router.npz" for r in res.results)
    recs = [r for r in caplog.records if "GC-only fallback" in r.getMessage()]
    assert len(recs) == 1


def test_successful_router_is_not_marked():
    probs = {"fish": 0.9, "plant": 0.02, "bacteria_pathogen": 0.02,
             "animal_general": 0.02, "human_domestic_contamination": 0.02, "misc_unknown": 0.02}
    lr.set_router(_Model(lambda _seq: probs))
    r = analysis.run_abyss_analysis("exp_1", [_inp()]).results[0]
    assert r.router_error_fallback is False
    assert r.router_error is None
    assert r.router_method == "learned"
    assert r.route == "fish"
    assert r.confidence_tier == "high"
    assert "router_error_fallback" not in r.reason_codes
    assert r.reason_codes[0] == "learned_router"
