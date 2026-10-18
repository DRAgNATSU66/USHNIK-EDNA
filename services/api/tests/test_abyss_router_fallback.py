"""
B12: the Abyss heuristic router's GC-only fallback must be logged and visible.

_heuristic_route used to catch every exception from the worker router and
silently return _simple_gc_route's answer.  Now the exception is logged (once
per distinct error, with traceback) and every affected result carries
router_error_fallback=True, router_error="<Type>: <msg>" and the reason code
"router_error_fallback".
"""
from __future__ import annotations

import logging
import os
import sys
import types
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.abyss.analysis as analysis  # noqa: E402
from app.abyss.models import AbyssSequenceInput  # noqa: E402

SEQ = "ATGCGTACGTTAGCATGCATGCAAGTCGATCGATGCATGCATGCATCGA" * 3


def _inp(i: int = 0) -> AbyssSequenceInput:
    return AbyssSequenceInput(sequence_id=f"s{i}", sequence=SEQ)


@pytest.fixture(autouse=True)
def _reset_logged():
    analysis._LOGGED_FALLBACKS.clear()
    yield
    analysis._LOGGED_FALLBACKS.clear()


def _fake_router(monkeypatch, route_sequence):
    mod = types.ModuleType("app.model_router")
    mod.route_sequence = route_sequence
    mod.RouterInput = lambda **kw: SimpleNamespace(**kw)
    monkeypatch.setitem(sys.modules, "app.model_router", mod)


def test_router_exception_is_marked_on_result(monkeypatch):
    def boom(_inp):
        raise RuntimeError("router exploded")

    _fake_router(monkeypatch, boom)
    r = analysis.run_abyss_analysis("exp_1", [_inp()]).results[0]
    assert r.router_error_fallback is True
    assert r.router_error == "RuntimeError: router exploded"
    assert r.reason_codes[0] == "router_error_fallback"
    # Still produces a GC-fallback route rather than failing the request.
    assert r.route in {"fish", "bacteria_pathogen", "misc_unknown", "human_domestic_contamination"}


def test_router_exception_logged_once_with_traceback(monkeypatch, caplog):
    def boom(_inp):
        raise RuntimeError("router exploded")

    _fake_router(monkeypatch, boom)
    with caplog.at_level(logging.WARNING, logger="app.abyss.analysis"):
        res = analysis.run_abyss_analysis("exp_1", [_inp(i) for i in range(5)])
    assert all(r.router_error_fallback for r in res.results)
    recs = [r for r in caplog.records if "heuristic router failed" in r.getMessage()]
    assert len(recs) == 1
    assert recs[0].exc_info is not None
    assert "router exploded" in recs[0].getMessage()


def test_successful_router_is_not_marked(monkeypatch):
    def ok(_inp):
        return SimpleNamespace(
            route="fish", route_confidence=0.9, confidence_tier="high",
            fallback_routes=[], reason_codes=["marker_12s"],
        )

    _fake_router(monkeypatch, ok)
    r = analysis.run_abyss_analysis("exp_1", [_inp()]).results[0]
    assert r.router_error_fallback is False
    assert r.router_error is None
    assert r.route == "fish"
    assert "router_error_fallback" not in r.reason_codes
