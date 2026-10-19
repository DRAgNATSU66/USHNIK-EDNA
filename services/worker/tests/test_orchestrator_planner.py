"""
Planner rule tables (app/orchestrator/planner.py; Day 9, tracker t-1022-2).
Table-driven: each row is a router output and the plan it must produce.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import get_worker_settings
from app.orchestrator.planner import RouterView, expand_plan, plan_sequence

FISH, PLANT, ANIMAL, BACT, HUMAN, MISC = (
    "fish", "plant", "animal_general", "bacteria_pathogen", "human_domestic_contamination", "misc_unknown")


def _settings(**over):
    base = dict(orchestrator_max_routes=3, orchestrator_confidence_threshold=0.70,
                orchestrator_margin_threshold=0.6, orchestrator_weak_routes=[HUMAN, MISC],
                orchestrator_reference_expansion=True)
    base.update(over)
    return get_worker_settings().model_copy(update=base)


def _seq(probs: dict[str, float], method: str = "learned", calibrated: bool = True, route: str | None = None) -> dict:
    top = route or max(probs, key=probs.get)
    return {"sequence_id": "s1", "route": top, "route_confidence": probs.get(top, 0.0),
            "route_probabilities": probs, "route_probabilities_calibrated": calibrated,
            "router_method": method, "router_version": "v2", "fallback_routes": []}


CONFIDENT_FISH = {FISH: 0.97, PLANT: 0.01, ANIMAL: 0.01, BACT: 0.005, HUMAN: 0.003, MISC: 0.002}

PLAN_TABLE = [
    # id, router probabilities, settings overrides, routes, rules (router stage)
    ("confident", CONFIDENT_FISH, {}, [FISH], ["confident_router"]),
    # 0.68 < 0.70; margin 0.68 - 0.08 = 0.60 is not < 0.6
    ("low_confidence", {FISH: 0.68, PLANT: 0.08, BACT: 0.07, ANIMAL: 0.06, HUMAN: 0.06, MISC: 0.05}, {},
     [FISH, PLANT, BACT], ["low_confidence"]),
    # confident (0.75 >= 0.70) but a narrow margin (0.75 - 0.20 = 0.55 < 0.6)
    ("narrow_margin", {FISH: 0.75, ANIMAL: 0.20, PLANT: 0.02, BACT: 0.01, HUMAN: 0.01, MISC: 0.01}, {},
     [FISH, ANIMAL, PLANT], ["narrow_margin"]),
    # confidently wrong on a weak route: only the weak-route rule catches it
    ("weak_route", {HUMAN: 0.95, ANIMAL: 0.02, FISH: 0.01, PLANT: 0.01, BACT: 0.005, MISC: 0.005}, {},
     [HUMAN, ANIMAL, FISH], ["weak_route"]),
    ("several_rules", {MISC: 0.5, BACT: 0.4, FISH: 0.05, PLANT: 0.02, ANIMAL: 0.02, HUMAN: 0.01}, {},
     [MISC, BACT, FISH], ["low_confidence", "narrow_margin", "weak_route"]),
    ("cap_2", {FISH: 0.5, PLANT: 0.3, ANIMAL: 0.2}, {"orchestrator_max_routes": 2}, [FISH, PLANT],
     ["low_confidence", "narrow_margin"]),
    ("cap_1", {FISH: 0.5, PLANT: 0.3, ANIMAL: 0.2}, {"orchestrator_max_routes": 1}, [FISH],
     ["low_confidence", "narrow_margin", "route_cap"]),
    ("weak_set_empty", {HUMAN: 0.95, ANIMAL: 0.03, FISH: 0.02}, {"orchestrator_weak_routes": []}, [HUMAN],
     ["confident_router"]),
]


@pytest.mark.parametrize("name,probs,over,routes,rules", PLAN_TABLE, ids=[r[0] for r in PLAN_TABLE])
def test_plan_table(name, probs, over, routes, rules):
    plan = plan_sequence(_seq(probs), _settings(**over))
    assert plan.routes == routes
    assert [r["rule"] for r in plan.rules_fired] == rules
    assert plan.primary_route == routes[0]
    # the first rule that fired lists the routes it added
    assert plan.rules_fired[0]["added"] == routes[1:]


def test_heuristic_router_is_uncalibrated_and_planned_wide():
    probs = {FISH: 0.9, PLANT: 0.06, ANIMAL: 0.04}
    plan = plan_sequence(_seq(probs, method="heuristic_fallback", calibrated=False), _settings())
    assert plan.rules_fired[0]["rule"] == "router_uncalibrated"
    assert plan.routes == [FISH, PLANT, ANIMAL]


def test_low_quality_is_planned_alone():
    seq = {"sequence_id": "s", "route": "low_quality", "route_confidence": 1.0, "route_probabilities": {},
           "router_method": "learned", "route_probabilities_calibrated": False}
    plan = plan_sequence(seq, _settings())
    assert plan.routes == ["low_quality"]
    assert [r["rule"] for r in plan.rules_fired] == ["low_quality_gate"]


def test_router_view_without_probabilities_uses_fallbacks():
    seq = {"route": FISH, "route_confidence": 0.4, "fallback_routes": [PLANT, ANIMAL]}
    v = RouterView.from_sequence(seq)
    assert [r for r, _ in v.ranked] == [FISH, PLANT, ANIMAL]
    plan = plan_sequence(seq, _settings())
    assert plan.routes == [FISH, PLANT, ANIMAL]


def test_plan_records_router_view():
    plan = plan_sequence(_seq(CONFIDENT_FISH), _settings())
    d = plan.to_dict()
    assert d["router"]["top_probability"] == 0.97
    assert d["router"]["margin"] == pytest.approx(0.96)
    assert d["router"]["ranked"][0] == [FISH, 0.97]


# -- second pass ---------------------------------------------------------------

def _ref(status: str, lineage: dict | None = None, taxon: str | None = None, evidence_status: str = "ok") -> dict:
    return {"provider": "reference_lookup", "status": evidence_status,
            "payload": {"status": status, "lineage": lineage or {}, "taxon": taxon, "rank": "species"}}


PLANT_LINEAGE = {"superkingdom": "Eukaryota", "kingdom": "Viridiplantae", "phylum": "Streptophyta",
                 "genus": "Quercus", "species": "Quercus robur"}
FISH_LINEAGE = {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Chordata", "class": "Actinopteri",
                "genus": "Salmo", "species": "Salmo trutta"}

EXPAND_TABLE = [
    # id, primary reference, settings, routes added, rule recorded
    # CONFIDENT_FISH ranks animal_general and plant equal (0.01): name order breaks the tie
    ("miss_adds_next_route", _ref("no_hit"), {}, [ANIMAL], "reference_miss"),
    ("below_threshold_adds_next_route", _ref("below_threshold"), {}, [ANIMAL], "reference_miss"),
    ("lineage_of_other_route", _ref("assigned", PLANT_LINEAGE, "Quercus robur"), {}, [PLANT],
     "reference_lineage_route"),
    ("lineage_of_own_route", _ref("assigned", FISH_LINEAGE, "Salmo trutta"), {}, [], None),
    ("reference_unavailable", _ref("unavailable", evidence_status="unavailable"), {}, [], None),
    ("expansion_off", _ref("no_hit"), {"orchestrator_reference_expansion": False}, [], None),
    ("cap_reached", _ref("no_hit"), {"orchestrator_max_routes": 1}, [], "reference_miss"),
]


@pytest.mark.parametrize("name,ref,over,added,rule", EXPAND_TABLE, ids=[r[0] for r in EXPAND_TABLE])
def test_expand_table(name, ref, over, added, rule):
    s = _settings(**over)
    seq = _seq(CONFIDENT_FISH)
    plan = plan_sequence(seq, s)
    assert plan.routes == [FISH]
    got = expand_plan(plan, seq, ref, s)
    assert got == added
    assert plan.routes == [FISH] + added
    post = [r for r in plan.rules_fired if r["stage"] == "post_reference"]
    if rule is None:
        assert post == []
    else:
        assert post[0]["rule"] == rule
        assert post[0]["added"] == added
        if not added:
            assert "route cap reached" in post[0]["detail"]


def test_expand_never_on_low_quality():
    seq = {"sequence_id": "s", "route": "low_quality", "route_probabilities": {}}
    s = _settings()
    plan = plan_sequence(seq, s)
    assert expand_plan(plan, seq, _ref("no_hit"), s) == []
