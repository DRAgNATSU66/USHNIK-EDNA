"""
Combiner rule tables (app/orchestrator/combiner.py; Day 9, tracker t-1022-2)
and the lineage -> route mirror (app/orchestrator/lineage.py).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import get_worker_settings
from app.orchestrator.combiner import CombineInput, combine, select_route
from app.orchestrator.lineage import implied_route, lineage_to_route
from app.orchestrator.planner import Plan

FISH, PLANT, ANIMAL, BACT, HUMAN, MISC = (
    "fish", "plant", "animal_general", "bacteria_pathogen", "human_domestic_contamination", "misc_unknown")
THRESHOLD = 0.45

S = get_worker_settings().model_copy(update=dict(
    reference_species_identity=97.0, reference_tie_delta=0.5, orchestrator_genus_cap_routes=[PLANT]))

FISH_LIN = {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Chordata", "class": "Actinopteri",
            "order": "Salmoniformes", "family": "Salmonidae", "genus": "Salmo", "species": "Salmo trutta"}
PLANT_LIN = {"superkingdom": "Eukaryota", "kingdom": "Viridiplantae", "phylum": "Streptophyta",
             "family": "Fagaceae", "genus": "Quercus", "species": "Quercus robur"}
ANIMAL_LIN = {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Arthropoda", "class": "Insecta",
              "genus": "Apis", "species": "Apis mellifera"}


# ---------------------------------------------------------------------------
# lineage mirror
# ---------------------------------------------------------------------------

LINEAGES = [
    FISH_LIN, PLANT_LIN, ANIMAL_LIN,
    {"superkingdom": "Bacteria", "phylum": "Proteobacteria", "genus": "Escherichia"},
    {"superkingdom": "Archaea", "phylum": "Euryarchaeota"},
    {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Chordata", "class": "Mammalia",
     "species": "Homo sapiens"},
    {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Chordata", "class": "Mammalia",
     "species": "Bos taurus"},
    {"superkingdom": "Eukaryota", "kingdom": "Fungi", "phylum": "Ascomycota"},
    {"superkingdom": "Eukaryota", "phylum": "Chordata", "class": "Chondrichthyes"},
    {"superkingdom": "Eukaryota", "kingdom": "Plantae"},
    {},
]


@pytest.mark.parametrize("lineage", LINEAGES)
def test_lineage_to_route_mirrors_training(lineage):
    from training.routing import lineage_to_route as training_rule
    assert lineage_to_route(lineage) == training_rule(lineage)


def test_implied_route_needs_a_placeable_lineage():
    assert implied_route({"superkingdom": "Eukaryota"}) is None   # LCA too coarse
    assert implied_route({}) is None
    assert implied_route({"superkingdom": "Bacteria"}) == BACT
    assert implied_route(PLANT_LIN) == PLANT


# ---------------------------------------------------------------------------
# evidence builders
# ---------------------------------------------------------------------------

def head(route, result_class, conf=0.9, status="ok"):
    return {"provider": "route_head", "route": route, "status": status, "reason": None if status == "ok" else "stub",
            "payload": {"result_class": result_class, "confidence": conf, "label_scores": {result_class: conf},
                        "model_version_used": f"m_{route}", "inference_mode": "model" if status == "ok" else "stub"}}


def ref(route, status="assigned", identity=99.5, lineage=None, rank=None, taxon=None, evidence_status="ok", hg=None):
    lineage = lineage or {}
    if rank is None and status == "assigned":
        rank = next((r for r in ("species", "genus", "family", "order", "class", "phylum") if lineage.get(r)), None)
    if taxon is None and rank:
        taxon = lineage.get(rank)
    return {"provider": "reference_lookup", "route": route, "status": evidence_status,
            "reason": None if evidence_status == "ok" else "no reference DB",
            "payload": {"status": status, "identity": identity if status in ("assigned", "below_threshold", "no_consensus") else None,
                        "lineage": lineage if status == "assigned" else {}, "rank": rank, "taxon": taxon,
                        "reference_db": f"synthveda-reference/{route}", "reference_db_version": "v2", "hits": [],
                        "human_genome": hg}}


def contam(flagged=False, grch38=False, hg_identity=None, status="ok"):
    return {"provider": "contamination", "status": status,
            "payload": {"contamination_score": 0.8 if flagged else 0.05, "flagged": flagged or grch38,
                        "grch38_contamination": grch38,
                        "human_genome": {"identity": hg_identity, "contamination": grch38} if grch38 else None}}


def nov(score, status="ok"):
    return {"provider": "novelty", "status": status, "reason": None if status == "ok" else "skipped",
            "payload": {"novelty_score": score} if status == "ok" else {}}


def plan(*routes):
    return Plan(primary_route=routes[0], routes=list(routes), max_routes=3)


# ---------------------------------------------------------------------------
# route selection
# ---------------------------------------------------------------------------

ROUTE_TABLE = [
    # id, plan, heads, refs, final route, rule
    ("single_route", plan(FISH), {FISH: head(FISH, "known_species")}, {FISH: ref(FISH, lineage=FISH_LIN)},
     FISH, "single_route"),
    ("low_quality", plan("low_quality"), {}, {}, "low_quality", "low_quality_gate"),
    ("reference_confirms_router", plan(FISH, ANIMAL),
     {FISH: head(FISH, "known_species"), ANIMAL: head(ANIMAL, "known_species")},
     {FISH: ref(FISH, identity=99.5, lineage=FISH_LIN), ANIMAL: ref(ANIMAL, identity=99.8, lineage=ANIMAL_LIN)},
     FISH, "reference_confirms_router"),   # 99.5 is within 0.5 of 99.8
    ("reference_overrides_router", plan(HUMAN, ANIMAL),
     {HUMAN: head(HUMAN, "known_species"), ANIMAL: head(ANIMAL, "known_species")},
     {HUMAN: ref(HUMAN, status="below_threshold", identity=88.0), ANIMAL: ref(ANIMAL, identity=99.9, lineage=ANIMAL_LIN)},
     ANIMAL, "reference_overrides_router"),
    ("override_beats_weaker_primary_hit", plan(FISH, PLANT),
     {FISH: head(FISH, "known_species")},
     {FISH: ref(FISH, identity=97.2, lineage=FISH_LIN), PLANT: ref(PLANT, identity=99.9, lineage=PLANT_LIN)},
     PLANT, "reference_overrides_router"),
    ("hit_outside_router_below_species_cut", plan(MISC, BACT),
     {MISC: head(MISC, "possible_novelty")},
     {MISC: ref(MISC, status="no_hit"),
      BACT: ref(BACT, identity=95.5, lineage={"superkingdom": "Bacteria", "genus": "Vibrio"}, rank="genus")},
     BACT, "reference_hit_outside_router"),
    ("no_reference_separates", plan(FISH, PLANT),
     {FISH: head(FISH, "known_species"), PLANT: head(PLANT, "possible_novelty")},
     {FISH: ref(FISH, status="below_threshold", identity=85.0), PLANT: ref(PLANT, status="no_hit")},
     FISH, "router_primary"),
    ("grch38_moves_to_human_route", plan(MISC, HUMAN),
     {MISC: head(MISC, "unknown_needs_online_confirmation"), HUMAN: head(HUMAN, "known_species")},
     {MISC: ref(MISC, status="no_hit"),
      HUMAN: ref(HUMAN, status="no_hit", hg={"contamination": True, "identity": 100.0, "query_coverage": 100.0})},
     HUMAN, "grch38_human_route"),
    ("grch38_beaten_by_closer_assignment", plan(ANIMAL, HUMAN),
     {ANIMAL: head(ANIMAL, "known_species")},
     {ANIMAL: ref(ANIMAL, identity=100.0, lineage=ANIMAL_LIN),
      HUMAN: ref(HUMAN, status="no_hit", hg={"contamination": True, "identity": 99.2})},
     ANIMAL, "reference_confirms_router"),
    ("no_consensus_primary_counts_in_tie", plan(HUMAN, MISC),
     {HUMAN: head(HUMAN, "possible_contamination")},
     {HUMAN: ref(HUMAN, status="no_consensus", identity=98.86),
      MISC: ref(MISC, identity=98.86, lineage={"superkingdom": "Viruses", "family": "Inoviridae",
                                               "species": "Inovirus M13"})},
     HUMAN, "reference_confirms_router"),
    ("coarse_lineage_outside_router_ignored", plan(PLANT, MISC),
     {PLANT: head(PLANT, "known_species")},
     {PLANT: ref(PLANT, status="below_threshold", identity=89.97),
      MISC: ref(MISC, identity=90.7, lineage={"superkingdom": "Eukaryota"}, rank="superkingdom", taxon="Eukaryota")},
     PLANT, "router_primary"),
    ("reference_unavailable_heads_only", plan(FISH, PLANT),
     {FISH: head(FISH, "known_species"), PLANT: head(PLANT, "known_species")},
     {FISH: ref(FISH, evidence_status="unavailable"), PLANT: ref(PLANT, evidence_status="unavailable")},
     FISH, "router_primary"),
]


@pytest.mark.parametrize("name,p,heads,refs,final,rule", ROUTE_TABLE, ids=[r[0] for r in ROUTE_TABLE])
def test_route_table(name, p, heads, refs, final, rule):
    got, steps = select_route(p, heads, refs, S)
    assert got == final
    route_steps = [s for s in steps if s["step"] == "route"]
    assert [s["rule"] for s in route_steps] == [rule]
    assert route_steps[0]["outcome"] == final


def test_heads_never_choose_the_route():
    # The plant head is far more confident than the fish head, and no
    # reference evidence exists: the router's pick stands.
    p = plan(FISH, PLANT)
    got, steps = select_route(p, {FISH: head(FISH, "possible_novelty", 0.41), PLANT: head(PLANT, "known_species", 0.99)},
                              {}, S)
    assert got == FISH
    assert any(s["rule"] == "heads_disagree" for s in steps)
    assert "heads only" in next(s for s in steps if s["step"] == "route")["detail"]


def test_lineage_vs_router_disagreement_recorded():
    p = plan(FISH, PLANT)
    _, steps = select_route(p, {}, {FISH: ref(FISH, status="no_hit"), PLANT: ref(PLANT, lineage=PLANT_LIN)}, S)
    dis = [s for s in steps if s["rule"] == "reference_lineage_vs_router"]
    assert len(dis) == 1
    assert dis[0]["outcome"]["implied_route"] == PLANT and dis[0]["outcome"]["router_route"] == FISH


# ---------------------------------------------------------------------------
# class, taxon, novelty
# ---------------------------------------------------------------------------

CLASS_TABLE = [
    # id, final route, head, reference, contamination, novelty, result_class, rule, taxon, rank
    ("qc_gate", "low_quality", head("low_quality", "low_quality_unusable", status="skipped"), None, contam(), nov(0.0),
     "low_quality_unusable", "qc_gate", None, None),
    ("head_class_with_species_hit", FISH, head(FISH, "known_species"), ref(FISH, lineage=FISH_LIN), contam(), nov(0.1),
     "known_species", "head_class", "Salmo trutta", "species"),
    ("novelty_suppressed_by_species_hit", FISH, head(FISH, "possible_novelty"), ref(FISH, lineage=FISH_LIN), contam(),
     nov(0.6), "known_species", "novelty_suppressed_by_reference", "Salmo trutta", "species"),
    ("novelty_downgraded_by_lca", FISH, head(FISH, "possible_novelty"),
     ref(FISH, identity=99.5, lineage={k: v for k, v in FISH_LIN.items() if k not in ("genus", "species")}),
     contam(), nov(0.6), "likely_taxonomic_group", "novelty_downgraded_by_reference", "Salmonidae", "family"),
    ("novelty_kept_below_species_cut", FISH, head(FISH, "possible_novelty"),
     ref(FISH, identity=95.5, lineage={k: v for k, v in FISH_LIN.items() if k != "species"}, rank="genus"),
     contam(), nov(0.6), "possible_novelty", "head_class", "Salmo", "genus"),
    ("contamination_gates_novelty", FISH, head(FISH, "possible_novelty"), ref(FISH, status="no_hit"), contam(flagged=True),
     nov(0.6), "possible_contamination", "contamination_gates_novelty", None, None),
    ("grch38_on_other_route", ANIMAL, head(ANIMAL, "known_species"), ref(ANIMAL, status="no_hit"),
     contam(grch38=True, hg_identity=99.8), nov(0.1), "possible_contamination", "grch38_contamination", None, None),
    ("grch38_beaten_by_closer_route_hit", ANIMAL, head(ANIMAL, "known_species"),
     ref(ANIMAL, identity=100.0, lineage=ANIMAL_LIN), contam(grch38=True, hg_identity=99.1), nov(0.1),
     "known_species", "head_class", "Apis mellifera", "species"),
    ("grch38_on_human_route_left_to_head", HUMAN, head(HUMAN, "known_species"), ref(HUMAN, status="no_hit"),
     contam(grch38=True, hg_identity=99.9), nov(0.1), "known_species", "head_class", None, None),
    ("head_low_quality", MISC, head(MISC, "low_quality_unusable"), ref(MISC, status="no_hit"), contam(), nov(0.0),
     "low_quality_unusable", "head_low_quality", None, None),
    ("reference_only_species", FISH, head(FISH, "unknown", status="unavailable"), ref(FISH, lineage=FISH_LIN), contam(),
     nov(0.0, status="skipped"), "known_species", "reference_only", "Salmo trutta", "species"),
    ("reference_only_genus", FISH, head(FISH, "unknown", status="unavailable"),
     ref(FISH, identity=96.0, lineage={k: v for k, v in FISH_LIN.items() if k != "species"}, rank="genus"), contam(),
     nov(0.0, status="skipped"), "likely_taxonomic_group", "reference_only", "Salmo", "genus"),
    ("no_evidence", FISH, head(FISH, "unknown", status="unavailable"), ref(FISH, evidence_status="unavailable"),
     contam(), nov(0.0, status="skipped"), "unknown_needs_online_confirmation", "no_evidence", None, None),
    ("plant_species_capped_at_genus", PLANT, head(PLANT, "known_species"), ref(PLANT, lineage=PLANT_LIN), contam(),
     nov(0.1), "known_species", "head_class", "Quercus", "genus"),
    ("plant_novelty_downgraded_after_cap", PLANT, head(PLANT, "possible_novelty"), ref(PLANT, lineage=PLANT_LIN),
     contam(), nov(0.6), "likely_taxonomic_group", "novelty_downgraded_by_reference", "Quercus", "genus"),
]


@pytest.mark.parametrize("name,route,h,r,c,n,klass,rule,taxon,rank", CLASS_TABLE, ids=[x[0] for x in CLASS_TABLE])
def test_class_table(name, route, h, r, c, n, klass, rule, taxon, rank):
    decision, steps, _ = combine(CombineInput(final_route=route, head=h, reference=r, contamination=c, novelty=n),
                                 S, THRESHOLD)
    assert decision["result_class"] == klass
    assert decision["rule"] == rule
    assert decision["predicted_taxon"] == taxon
    assert decision["taxon_rank"] == rank
    assert decision["final_route"] == route
    assert set(decision) == {"final_route", "result_class", "predicted_taxon", "taxon_rank", "percent_identity",
                             "reference_db", "reference_db_version", "confidence", "rule"}
    assert [s for s in steps if s["step"] == "class"][0]["rule"] == rule


def test_genus_cap_is_recorded():
    _, steps, _ = combine(CombineInput(final_route=PLANT, head=head(PLANT, "known_species"),
                                       reference=ref(PLANT, lineage=PLANT_LIN), contamination=contam(), novelty=nov(0.1)),
                          S, THRESHOLD)
    cap = [s for s in steps if s["rule"] == "genus_cap"]
    assert cap and cap[0]["outcome"] == {"from": "Quercus robur", "to": "Quercus"}


def test_reference_unavailable_says_heads_only():
    decision, steps, _ = combine(CombineInput(final_route=FISH, head=head(FISH, "known_species"),
                                              reference=ref(FISH, evidence_status="unavailable"),
                                              contamination=contam(), novelty=nov(0.1)), S, THRESHOLD)
    assert decision["result_class"] == "known_species"
    assert decision["predicted_taxon"] is None and decision["reference_db"] is None
    assert any(s["rule"] == "heads_only" and "unavailable" in s["detail"] for s in steps)


NOVELTY_TABLE = [
    # id, head class, reference, contamination, raw score, final score, gate rule, suppressed, downgraded
    ("ungated", "possible_novelty", ref(FISH, status="no_hit"), contam(), 0.6, 0.6, None, False, False),
    ("suppressed_by_species_hit", "possible_novelty", ref(FISH, lineage=FISH_LIN), contam(), 0.6, 0.0,
     "novelty_suppressed_by_reference", True, False),
    ("suppressed_even_if_head_not_novel", "likely_taxonomic_group", ref(FISH, lineage=FISH_LIN), contam(), 0.5, 0.0,
     "novelty_suppressed_by_reference", True, False),
    ("downgraded_keeps_score", "possible_novelty",
     ref(FISH, identity=99.0, lineage={k: v for k, v in FISH_LIN.items() if k not in ("genus", "species")}), contam(),
     0.6, 0.6, "novelty_downgraded_by_reference", False, True),
    ("contamination_gate", "possible_novelty", ref(FISH, status="no_hit"), contam(flagged=True), 0.6, 0.0,
     "contamination_gates_novelty", False, False),
]


@pytest.mark.parametrize("name,hc,r,c,raw,final,gate_rule,suppressed,downgraded", NOVELTY_TABLE,
                         ids=[x[0] for x in NOVELTY_TABLE])
def test_novelty_table(name, hc, r, c, raw, final, gate_rule, suppressed, downgraded):
    _, steps, n = combine(CombineInput(final_route=FISH, head=head(FISH, hc), reference=r, contamination=c,
                                       novelty=nov(raw)), S, THRESHOLD)
    assert n["raw_score"] == raw
    assert n["final_score"] == final
    assert n["gate_rule"] == gate_rule
    assert n["suppressed_by_reference"] is suppressed
    assert n["downgraded_by_reference"] is downgraded
    nstep = [s for s in steps if s["step"] == "novelty"]
    assert len(nstep) == 1 and nstep[0]["rule"] == (gate_rule or "novelty_ungated")


def test_novelty_unscored_is_recorded():
    _, steps, n = combine(CombineInput(final_route=FISH, head=head(FISH, "x", status="unavailable"),
                                       reference=ref(FISH, status="no_hit"), contamination=contam(),
                                       novelty=nov(0.0, status="skipped")), S, THRESHOLD)
    assert n["final_score"] is None
    assert [s["rule"] for s in steps if s["step"] == "novelty"] == ["novelty_unscored"]


# Review fix (orchestrator-1.2.0): a no_consensus top pick is not a reference
# miss for reference_hit_outside_router; its identity counts as in the tie rule.
NO_CONSENSUS_TABLE = [
    ("no_consensus_100_beats_weak_family_hit", HUMAN, 100.0, 90.36, HUMAN, "reference_confirms_router"),
    ("no_consensus_within_tie", HUMAN, 94.0, 94.4, HUMAN, "reference_confirms_router"),
    ("no_consensus_weaker_than_other_hit", HUMAN, 85.0, 92.0, MISC, "reference_hit_outside_router"),
]


@pytest.mark.parametrize("name,primary,p_id,other_id,final,rule", NO_CONSENSUS_TABLE,
                         ids=[x[0] for x in NO_CONSENSUS_TABLE])
def test_no_consensus_primary_outside_router(name, primary, p_id, other_id, final, rule):
    retro = {"superkingdom": "Viruses", "phylum": "Artverviricota", "class": "Revtraviricetes",
             "family": "Retroviridae"}
    got, steps = select_route(plan(primary, MISC), {},
                              {primary: ref(primary, status="no_consensus", identity=p_id),
                               MISC: ref(MISC, identity=other_id, lineage=retro, rank="family")}, S)
    assert got == final
    assert [s["rule"] for s in steps if s["step"] == "route"] == [rule]


def test_grch38_beaten_records_step_and_does_not_gate():
    # Contamination record as the provider writes it when the engine says the
    # final route's assignment beat GRCh38: not flagged, beaten_by recorded.
    c = {"provider": "contamination", "status": "ok",
         "payload": {"contamination_score": 0.05, "flagged": False, "grch38_contamination": False, "grch38_hit": True,
                     "grch38_beaten_by": {"route": ANIMAL, "taxon": "Apis mellifera", "identity": 99.9,
                                          "grch38_identity": 99.2},
                     "human_genome": {"identity": 99.2, "contamination": True}}}
    decision, steps, n = combine(CombineInput(final_route=ANIMAL, head=head(ANIMAL, "possible_novelty"),
                                              reference=ref(ANIMAL, identity=99.9, lineage=ANIMAL_LIN),
                                              contamination=c, novelty=nov(0.6)), S, THRESHOLD)
    assert decision["result_class"] == "known_species"
    assert n["gate_rule"] == "novelty_suppressed_by_reference"
    assert "grch38_beaten_by_closer_assignment" in [s["rule"] for s in steps]
