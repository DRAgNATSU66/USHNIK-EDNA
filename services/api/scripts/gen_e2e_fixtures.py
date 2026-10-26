"""
Generate the API fixtures the frontend Playwright suite mocks with
(web_frontend/e2e/fixtures/api/*.json, roadmap t-1029-2).

The fixtures are not hand-written. This script seeds an in-memory stand-in
for MongoDB with one researcher's analysis (upload, results, reviews, field
log, an expedition, two jobs), mounts the real FastAPI app over ASGI, signs
real JWTs for a researcher, a curator and an admin, and records what each GET
endpoint the frontend calls actually returns -- response_model filtering,
datetime serialisation and all. So a fixture can only drift from the API if
someone edits the JSON by hand, and tests/test_e2e_fixtures.py fails API CI
when the committed files no longer match what this script produces.

Only two kinds of value are normalised, both volatile per request:
`generated_at` on reports (default_factory=utcnow) and `created_at` on
/auth/me (the profile is rebuilt from JWT claims on every call).

Usage (from the repo root):
    services/api/.venv/bin/python services/api/scripts/gen_e2e_fixtures.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]
OUT_DIR = REPO_ROOT / "web_frontend" / "e2e" / "fixtures" / "api"
sys.path.insert(0, str(API_DIR))

from httpx import ASGITransport, AsyncClient  # noqa: E402

import app.custody.chain as custody_chain  # noqa: E402
import app.db.mongo as mongo_module  # noqa: E402
import app.main as main_module  # noqa: E402
import app.models.router as models_router_module  # noqa: E402
from app.auth.jwt import create_access_token  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

FIXED_TS = "2026-10-16T09:00:00"
# checked_at: when GET /reports/{id}/custody re-verified the chain.
VOLATILE_KEYS = {"generated_at", "checked_at"}

ANALYSIS_ID = "ana_e2e0000000001"
UPLOAD_ID = "upl_e2e0000000001"
JOB_RUNNING_ID = "job_e2e_running01"
JOB_DONE_ID = "job_e2e_complete1"
EXPEDITION_ID = "exp_e2e0000000001"

USERS = {
    "researcher": {"sub": "usr_e2e_researcher", "email": "researcher@e2e.test", "name": "Rhea Researcher", "role": "researcher"},
    "curator": {"sub": "usr_e2e_curator", "email": "curator@e2e.test", "name": "Cyrus Curator", "role": "curator"},
    "admin": {"sub": "usr_e2e_admin", "email": "admin@e2e.test", "name": "Ada Admin", "role": "admin"},
}
OWNER = USERS["researcher"]["sub"]


def _ts(day: int, hour: int = 9, minute: int = 0) -> datetime:
    # Naive UTC, as Motor returns stored datetimes (db/mongo.py does not set
    # tz_aware), so serialised timestamps look exactly like production's.
    return datetime(2026, 10, day, hour, minute)


# ---------------------------------------------------------------------------
# In-memory Mongo stand-in: just the operations the GET routes use.
# ---------------------------------------------------------------------------

def _matches(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        val = doc.get(key)
        if isinstance(cond, dict) and "$in" in cond:
            if val not in cond["$in"]:
                return False
        elif val != cond:
            return False
    return True


class _Cursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def sort(self, key, direction: int = 1):
        keys = key if isinstance(key, list) else [(key, direction)]
        for k, d in reversed(keys):
            self._docs.sort(key=lambda doc: (doc.get(k) is None, doc.get(k)), reverse=d < 0)
        return self

    def skip(self, n: int):
        self._docs = self._docs[n:]
        return self

    def limit(self, n: int):
        self._docs = self._docs[:n] if n else self._docs
        return self

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    def __init__(self, docs: list[dict] | None = None):
        self.docs = docs or []

    async def find_one(self, query: dict, projection: Any = None, sort: Any = None):
        docs = [d for d in self.docs if _matches(d, query)]
        if sort:  # custody/chain.py append_event: head of the chain by seq
            docs = _Cursor(docs).sort(sort)._docs
        return copy.deepcopy(docs[0]) if docs else None

    async def insert_one(self, doc: dict):
        # custody/chain.py append_event (GET /reports/{id}/custody derives events)
        self.docs.append(copy.deepcopy(doc))

    def find(self, query: dict | None = None, projection: Any = None):
        return _Cursor([copy.deepcopy(d) for d in self.docs if _matches(d, query or {})])

    def aggregate(self, pipeline: list[dict]):
        first = pipeline[0]
        if "$group" in first:  # reviews/curation.py queue_stats
            counts: dict[tuple, int] = {}
            for d in self.docs:
                k = (d["state"], d["review_type"])
                counts[k] = counts.get(k, 0) + 1
            return _Cursor([{"_id": {"state": s, "review_type": t}, "count": c} for (s, t), c in counts.items()])
        # reviews/router.py get_review_queue: $match, urgent-first, created_at.
        docs = [copy.deepcopy(d) for d in self.docs if _matches(d, first["$match"])]
        order = {"urgent": 0, "normal": 1}
        docs.sort(key=lambda d: (order.get(d.get("triage_priority"), 2), d.get("created_at")))
        return _Cursor(docs)


class _Db:
    def __init__(self, seed: dict[str, list[dict]]):
        self._cols = {name: _Collection(docs) for name, docs in seed.items()}

    def __getitem__(self, name: str) -> _Collection:
        return self._cols.setdefault(name, _Collection())


# ---------------------------------------------------------------------------
# Seed data: one deep-sea sample with every result class the pages render.
# ---------------------------------------------------------------------------

def _seq(sequence_id: str, route: str, result_class: str, *, length: int = 300, gc: float = 0.48,
         n_ratio: float = 0.0, confidence: float = 0.0, taxon: str | None = None,
         novelty: float = 0.1, novelty_level: str = "none", contamination: float = 0.0,
         contaminated: bool = False, contamination_type: str | None = None,
         model: str = "dnabert2_fish_v1", reasons: list[str] | None = None,
         recommendation: str = "continue_sampling", cloud: bool = False) -> dict:
    return {
        "sequence_id": sequence_id,
        "sequence": ("ACGTTGCA" * (length // 8 + 1))[:length],
        "route": route,
        "result_class": result_class,
        "length": length,
        "gc_ratio": gc,
        "n_ratio": n_ratio,
        "has_invalid_chars": False,
        "confidence": confidence,
        "predicted_taxon": taxon,
        "novelty_score": novelty,
        "novelty_level": novelty_level,
        "abyss_recommendation": recommendation,
        "requires_cloud_confirmation": cloud,
        "contamination_score": contamination,
        "contamination_flagged": contaminated,
        "contamination_type": contamination_type,
        "model_version_used": model,
        "reason_codes": reasons or [],
        "novelty_reason_codes": reasons or [],
        "contamination_reason_codes": reasons or [],
    }


RESULTS = [
    _seq("seq_e2e_tuna_001", "fish", "known_species", confidence=0.91, taxon="Thunnus albacares", gc=0.46),
    _seq("seq_e2e_lantern_002", "fish", "known_species", confidence=0.62, taxon="Myctophum punctatum", gc=0.44),
    _seq("seq_e2e_novel_003", "fish", "possible_novel_taxon", confidence=0.21, novelty=0.83,
         novelty_level="high", reasons=["low_reference_similarity"], recommendation="preserve_sample", cloud=True),
    _seq("seq_e2e_novel_004", "bacteria", "possible_novel_taxon", confidence=0.18, novelty=0.67,
         novelty_level="medium", model="dnabert2_bacteria_v1", reasons=["low_reference_similarity"],
         recommendation="return_for_full_analysis", cloud=True),
    _seq("seq_e2e_contam_005", "human_domestic", "possible_contaminant", confidence=0.88, taxon="Homo sapiens",
         contamination=0.94, contaminated=True, contamination_type="human", model="dnabert2_human_domestic_v1",
         reasons=["human_contaminant_match"]),
    _seq("seq_e2e_plant_006", "plant", "unknown_needs_online_confirmation", confidence=0.35, novelty=0.3,
         novelty_level="low", model="dnabert2_plant_v1"),
    _seq("seq_e2e_lowq_007", "low_quality", "low_quality_unusable", length=80, n_ratio=0.6, model="stub_none"),
]

UPLOAD = {
    "upload_id": UPLOAD_ID,
    "user_id": OWNER,
    "original_filename": "e2e_arabian_sea_station7.fasta",
    "file_size_bytes": 18_432,
    "status": "stored",
    "collected_at": _ts(9, 6, 30),
    "latitude": 15.52,
    "longitude": 68.21,
    "location_label": "Arabian Sea, Station 7",
    "depth_meters": 1850.0,
    "source_type": "seawater",
    "habitat": "bathypelagic",
    "temperature_celsius": 4.2,
    "methodology": "metabarcoding",
    "negative_control_included": False,
    "collector": "RV Sagar Nidhi crew",
    "created_at": _ts(10, 8),
}

ANALYSIS = {
    "analysis_id": ANALYSIS_ID,
    "job_id": JOB_DONE_ID,
    "upload_id": UPLOAD_ID,
    "user_id": OWNER,
    "mode": "online_full",
    "model_version_set": "dnabert2_v1_set",
    "results": RESULTS,
    "created_at": _ts(10, 8, 5),
}

# ---------------------------------------------------------------------------
# Orchestrated analysis (decision Q7, orchestrator-1.2.0) for the Results
# page's per-sequence calls and "Why this answer" trace (t-1023-2). Rows use
# the stored shape the worker writes (services/worker/app/orchestrator/
# engine.py; a real stored trace was read from local Mongo for the shape):
# legacy fields + "decision" + "decision_trace" {orchestrator_version, plan,
# evidence, combine}. Four cases: confident single route; plant genus cap
# with novelty downgraded; reference overriding the router with novelty
# suppressed; and a reference miss with a provider unavailable. A second,
# pre-orchestrator analysis (no decision, no trace) checks the empty state.
# Both are older than ANALYSIS, so "latest analysis" fixtures are unchanged.
# ---------------------------------------------------------------------------

ORCH_ANALYSIS_ID = "ana_e2e0000000002"
LEGACY_ANALYSIS_ID = "ana_e2e0000000003"
ORCH_VERSION = "orchestrator-1.2.0"
REF_DB_VERSION = "v2"


def _ev(provider: str, sid: str, route: str, payload: dict | None, *, status: str = "ok",
        reason: str | None = None, elapsed_ms: float = 12.0) -> dict:
    return {"provider": provider, "provider_version": "1.0", "sequence_id": sid, "route": route,
            "status": status, "reason": reason, "elapsed_ms": elapsed_ms, "payload": payload}


def _head_ev(sid: str, route: str, result_class: str, confidence: float, model: str) -> dict:
    return _ev("route_head", sid, route, {
        "result_class": result_class, "confidence": confidence,
        "label_scores": {result_class: confidence}, "model_version_used": model,
        "inference_mode": "model", "stub_reason": None})


def _ref_ev(sid: str, route: str, status: str, *, taxon: str | None = None, rank: str | None = None,
            identity: float | None = None, lineage: dict | None = None, hits: list[dict] | None = None,
            reason: str | None = None) -> dict:
    return _ev("reference_lookup", sid, route, {
        "status": status, "taxon": taxon, "rank": rank, "identity": identity,
        "query_coverage": 100.0 if identity is not None else None, "identity_rank": rank,
        "lineage": lineage or {}, "tied_hits": 1 if hits else 0, "tied_taxa": 1 if hits else 0,
        "lca_applied": False, "reason": reason, "hits": hits or [], "method": "blast",
        "reference_db": f"synthveda-reference/{route}", "reference_db_version": REF_DB_VERSION,
        "reference_db_sha256": "0" * 64, "batch_seconds": 0.4, "human_genome": None}, elapsed_ms=150.0)


def _hit(accession: str, taxon: str, identity: float, marker: str, source: str = "midori2") -> dict:
    return {"accession": accession, "source": source, "marker": marker, "identity": identity,
            "query_coverage": 100.0, "alignment_length": 300, "taxon": taxon, "rank": "species"}


def _contam_ev(sid: str, route: str) -> dict:
    return _ev("contamination", sid, route, {
        "contamination_score": 0.01, "heuristic_flagged": False, "grch38_contamination": False,
        "flagged": False, "contamination_type": None, "signals": {"route": 0.0, "lab_motif": 0.0},
        "reason_codes": ["clean_sequence"], "human_genome": None}, elapsed_ms=0.02)


def _novelty_ev(sid: str, route: str, score: float, level: str) -> dict:
    return _ev("novelty", sid, route, {
        "novelty_score": score, "novelty_level": level, "signals": {}, "reason_codes": [],
        "abyss_recommendation": "continue_sampling", "requires_cloud_confirmation": False}, elapsed_ms=0.04)


def _step(step: str, rule: str, outcome: Any, detail: str | None = None) -> dict:
    return {"step": step, "rule": rule, "outcome": outcome, "detail": detail}


def _novelty_step(rule: str, raw: float, gate: float, *, raw_flag: bool, final_flag: bool,
                  suppressed: bool = False, downgraded: bool = False, detail: str | None = None) -> dict:
    gate_rule = rule if rule not in ("novelty_ungated", "novelty_unscored") else None
    return _step("novelty", rule, {
        "raw_score": raw, "gate": gate, "final_score": round(raw * gate, 4), "gate_rule": gate_rule,
        "raw_flag": raw_flag, "final_flag": final_flag, "suppressed_by_reference": suppressed,
        "downgraded_by_reference": downgraded}, detail)


def _plan(primary: str, routes: list[str], rules: list[dict], ranked: list[list]) -> dict:
    return {"primary_route": primary, "routes": routes, "rules_fired": rules, "max_routes": 3,
            "router": {"method": "learned", "version": "v2", "calibrated": True,
                       "top_probability": ranked[0][1], "margin": round(ranked[0][1] - ranked[1][1], 4),
                       "ranked": ranked}}


def _orch_seq(sid: str, *, route: str, router_route: str, result_class: str, taxon: str | None,
              rank: str | None, identity: float | None, head_conf: float, model: str, rule: str,
              novelty: float, plan: dict, evidence: list[dict], combine: list[dict],
              reasons: list[str] | None = None) -> dict:
    row = _seq(sid, route, result_class, confidence=head_conf, taxon=taxon, novelty=novelty, model=model,
               reasons=reasons)
    row.update({
        "route_confidence": plan["router"]["ranked"][0][1] if route == router_route else 0.1,
        "router_route": router_route, "router_method": "learned", "router_version": "v2",
        "route_probabilities_calibrated": True, "inference_mode": "model",
        "decision": {"final_route": route, "result_class": result_class, "predicted_taxon": taxon,
                     "taxon_rank": rank, "percent_identity": identity,
                     "reference_db": f"synthveda-reference/{route}", "reference_db_version": REF_DB_VERSION,
                     "confidence": head_conf, "rule": rule},
        "decision_trace": {"orchestrator_version": ORCH_VERSION, "plan": plan, "evidence": evidence,
                           "combine": combine},
    })
    return row


_TUNA = {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Chordata", "class": "Actinopteri",
         "order": "Scombriformes", "family": "Scombridae", "genus": "Thunnus", "species": "Thunnus albacares"}
_OAK = {"superkingdom": "Eukaryota", "kingdom": "Viridiplantae", "phylum": "Streptophyta",
        "order": "Fagales", "family": "Fagaceae", "genus": "Quercus", "species": "Quercus robur"}
_MUSSEL = {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "phylum": "Mollusca", "class": "Bivalvia",
           "order": "Unionida", "family": "Unionidae", "genus": "Ptychobranchus",
           "species": "Ptychobranchus jonesi"}

ORCH_RESULTS = [
    _orch_seq(
        "seq_e2e_orch_tuna_01", route="fish", router_route="fish", result_class="known_species",
        taxon="Thunnus albacares", rank="species", identity=99.84, head_conf=0.97, model="dnabert2_fish_v2",
        rule="head_class", novelty=0.0,
        plan=_plan("fish", ["fish"], [{"rule": "confident_router", "stage": "router",
                                        "detail": "no wide-plan rule fired", "added": []}],
                   [["fish", 0.96], ["animal_general", 0.02], ["misc_unknown", 0.01]]),
        evidence=[
            _head_ev("seq_e2e_orch_tuna_01", "fish", "known_species", 0.97, "dnabert2_fish_v2"),
            _ref_ev("seq_e2e_orch_tuna_01", "fish", "assigned", taxon="Thunnus albacares", rank="species",
                    identity=99.84, lineage=_TUNA, hits=[_hit("AB000001.1", "Thunnus albacares", 99.84, "COI")]),
            _contam_ev("seq_e2e_orch_tuna_01", "fish"),
            _novelty_ev("seq_e2e_orch_tuna_01", "fish", 0.04, "none"),
        ],
        combine=[
            _step("route", "single_route", "fish"),
            _step("taxon", "reference_taxon", {"taxon": "Thunnus albacares", "rank": "species"},
                  "99.84% identity, synthveda-reference/fish v2"),
            _step("class", "head_class", "known_species"),
            _novelty_step("novelty_suppressed_by_reference", 0.04, 0.0, raw_flag=False, final_flag=False,
                          detail="reference names Thunnus albacares at 99.84% (QNA-020 Q4)"),
        ]),
    _orch_seq(
        "seq_e2e_orch_oak_02", route="plant", router_route="plant", result_class="likely_taxonomic_group",
        taxon="Quercus", rank="genus", identity=98.9, head_conf=0.71, model="dnabert2_plant_v1",
        rule="novelty_downgraded_by_reference", novelty=0.74,
        plan=_plan("plant", ["plant", "misc_unknown", "animal_general"],
                   [{"rule": "low_confidence", "stage": "router", "detail": "top probability 0.58 < 0.7",
                     "added": ["misc_unknown", "animal_general"]}],
                   [["plant", 0.58], ["misc_unknown", 0.31], ["animal_general", 0.06]]),
        evidence=[
            _head_ev("seq_e2e_orch_oak_02", "plant", "possible_novelty", 0.71, "dnabert2_plant_v1"),
            _ref_ev("seq_e2e_orch_oak_02", "plant", "assigned", taxon="Quercus robur", rank="species",
                    identity=98.9, lineage=_OAK, hits=[_hit("MN000002.1", "Quercus robur", 98.9, "rbcL", "ncbi")]),
            _head_ev("seq_e2e_orch_oak_02", "misc_unknown", "unknown_needs_online_confirmation", 0.88,
                     "dnabert2_misc_unknown_v2"),
            _ev("reference_lookup", "seq_e2e_orch_oak_02", "misc_unknown", None, status="unavailable",
                reason="BLAST database for misc_unknown not found on the worker", elapsed_ms=0.5),
            _head_ev("seq_e2e_orch_oak_02", "animal_general", "known_species", 0.64, "dnabert2_animal_v2"),
            _ref_ev("seq_e2e_orch_oak_02", "animal_general", "no_hit", reason="no reference hit"),
            _contam_ev("seq_e2e_orch_oak_02", "plant"),
            _novelty_ev("seq_e2e_orch_oak_02", "plant", 0.74, "high"),
        ],
        combine=[
            _step("disagreement", "heads_disagree",
                  {"plant": "possible_novelty", "misc_unknown": "unknown_needs_online_confirmation",
                   "animal_general": "known_species"},
                  "candidate heads give different classes; heads do not choose the route"),
            _step("route", "reference_confirms_router", "plant",
                  "plant reference identity 98.9% is within 0.5 of the best (98.9%)"),
            _step("taxon", "genus_cap", {"from": "Quercus robur", "to": "Quercus"},
                  "plant species names are capped at genus (species precision 51.9%, QNA-020 Q4)"),
            _step("taxon", "reference_taxon", {"taxon": "Quercus", "rank": "genus"},
                  "98.9% identity, synthveda-reference/plant v2"),
            _step("class", "novelty_downgraded_by_reference", "likely_taxonomic_group",
                  "head said possible_novelty; reference Quercus (genus) at 98.9% counts against novelty (QNA-020 Q4)"),
            _novelty_step("novelty_downgraded_by_reference", 0.74, 1.0, raw_flag=True, final_flag=True,
                          downgraded=True, detail="flag kept for review: the reference cannot resolve the species"),
        ]),
    _orch_seq(
        "seq_e2e_orch_mussel_03", route="animal_general", router_route="misc_unknown",
        result_class="known_species", taxon="Ptychobranchus jonesi", rank="species", identity=99.67,
        head_conf=0.66, model="dnabert2_animal_v2", rule="novelty_suppressed_by_reference", novelty=0.0,
        plan=_plan("misc_unknown", ["misc_unknown", "animal_general", "fish"],
                   [{"rule": "weak_route", "stage": "router", "detail": "misc_unknown is a weak route for the router",
                     "added": ["animal_general", "fish"]}],
                   [["misc_unknown", 0.82], ["animal_general", 0.11], ["fish", 0.04]]),
        evidence=[
            _head_ev("seq_e2e_orch_mussel_03", "misc_unknown", "unknown_needs_online_confirmation", 0.9,
                     "dnabert2_misc_unknown_v2"),
            _ref_ev("seq_e2e_orch_mussel_03", "misc_unknown", "below_threshold", reason="best hit below 80% identity"),
            _head_ev("seq_e2e_orch_mussel_03", "animal_general", "possible_novelty", 0.66, "dnabert2_animal_v2"),
            _ref_ev("seq_e2e_orch_mussel_03", "animal_general", "assigned", taxon="Ptychobranchus jonesi",
                    rank="species", identity=99.67, lineage=_MUSSEL,
                    hits=[_hit("JX311522.1", "Ptychobranchus jonesi", 99.67, "ND1"),
                          _hit("JX311518.1", "Ptychobranchus greenii", 90.5, "ND1")]),
            _head_ev("seq_e2e_orch_mussel_03", "fish", "known_species", 0.55, "dnabert2_fish_v2"),
            _ref_ev("seq_e2e_orch_mussel_03", "fish", "no_hit", reason="no reference hit"),
            _contam_ev("seq_e2e_orch_mussel_03", "animal_general"),
            _novelty_ev("seq_e2e_orch_mussel_03", "animal_general", 0.69, "medium"),
        ],
        combine=[
            _step("disagreement", "heads_disagree",
                  {"misc_unknown": "unknown_needs_online_confirmation", "animal_general": "possible_novelty",
                   "fish": "known_species"}, "candidate heads give different classes; heads do not choose the route"),
            _step("route", "reference_overrides_router", "animal_general",
                  "animal_general reference identity 99.67% beats misc_unknown by more than 0.5"),
            _step("taxon", "reference_taxon", {"taxon": "Ptychobranchus jonesi", "rank": "species"},
                  "99.67% identity, synthveda-reference/animal_general v2"),
            _step("class", "novelty_suppressed_by_reference", "known_species",
                  "head said possible_novelty; reference Ptychobranchus jonesi (species) at 99.67% counts against "
                  "novelty (QNA-020 Q4)"),
            _novelty_step("novelty_suppressed_by_reference", 0.69, 0.0, raw_flag=True, final_flag=False,
                          suppressed=True, detail="reference names Ptychobranchus jonesi at 99.67% (QNA-020 Q4)"),
        ]),
    _orch_seq(
        "seq_e2e_orch_vent_04", route="bacteria_pathogen", router_route="bacteria_pathogen",
        result_class="possible_novelty", taxon=None, rank=None, identity=None, head_conf=0.81,
        model="dnabert2_bacteria_v1", rule="head_class", novelty=0.78,
        plan=_plan("bacteria_pathogen", ["bacteria_pathogen", "misc_unknown"],
                   [{"rule": "confident_router", "stage": "router", "detail": "no wide-plan rule fired", "added": []},
                    {"rule": "reference_miss", "stage": "post_reference",
                     "detail": "bacteria_pathogen reference: no_hit; adding the router's next route misc_unknown",
                     "added": ["misc_unknown"]}],
                   [["bacteria_pathogen", 0.93], ["misc_unknown", 0.05], ["plant", 0.01]]),
        evidence=[
            _head_ev("seq_e2e_orch_vent_04", "bacteria_pathogen", "possible_novelty", 0.81, "dnabert2_bacteria_v1"),
            _ref_ev("seq_e2e_orch_vent_04", "bacteria_pathogen", "no_hit", reason="no reference hit"),
            _head_ev("seq_e2e_orch_vent_04", "misc_unknown", "possible_novelty", 0.62, "dnabert2_misc_unknown_v2"),
            _ref_ev("seq_e2e_orch_vent_04", "misc_unknown", "no_hit", reason="no reference hit"),
            _contam_ev("seq_e2e_orch_vent_04", "bacteria_pathogen"),
            _novelty_ev("seq_e2e_orch_vent_04", "bacteria_pathogen", 0.78, "high"),
        ],
        combine=[
            _step("route", "router_primary", "bacteria_pathogen", "no candidate has a reference assignment"),
            _step("taxon", "no_reference_assignment", "no_hit", "no reference hit"),
            _step("class", "head_class", "possible_novelty"),
            _novelty_step("novelty_ungated", 0.78, 1.0, raw_flag=True, final_flag=True),
        ]),
]

ORCH_ANALYSIS = {
    "analysis_id": ORCH_ANALYSIS_ID,
    "job_id": "job_e2e_orch00001",
    "upload_id": UPLOAD_ID,
    "user_id": OWNER,
    "mode": "online_full",
    "model_version_set": "stub_none",
    "orchestrator_version": ORCH_VERSION,
    "results": ORCH_RESULTS,
    "created_at": _ts(9, 8),
}


def _legacy_seq(sid: str, route: str, result_class: str, confidence: float, model: str, mode: str) -> dict:
    row = _seq(sid, route, result_class, confidence=confidence, model=model)
    row.update({"route_confidence": 0.9, "inference_mode": mode})
    return row


LEGACY_ANALYSIS = {
    "analysis_id": LEGACY_ANALYSIS_ID,
    "job_id": "job_e2e_legacy001",
    "upload_id": UPLOAD_ID,
    "user_id": OWNER,
    "mode": "online_full",
    "model_version_set": "stub_none",
    "results": [
        _legacy_seq("seq_e2e_old_01", "fish", "known_species", 0.93, "dnabert2_fish_v1", "model"),
        _legacy_seq("seq_e2e_old_02", "misc_unknown", "unknown_needs_online_confirmation", 0.0,
                    "dnabert2_misc_unknown_v1:stub_no_weights", "stub"),
    ],
    "created_at": _ts(8, 8),
}

REVIEWS = [
    {"review_id": "rev_e2e_novelty01", "analysis_id": ANALYSIS_ID, "sequence_id": "seq_e2e_novel_003",
     "submitted_by": "system", "state": "submitted", "review_type": "auto_novelty", "triage_priority": "urgent",
     "novelty_score": 0.83, "novelty_level": "high", "abyss_recommendation": "preserve_sample",
     "correction_type": "novelty_flag", "is_novelty": True, "created_at": _ts(10, 8, 6)},
    {"review_id": "rev_e2e_contam01", "analysis_id": ANALYSIS_ID, "sequence_id": "seq_e2e_contam_005",
     "submitted_by": "system", "state": "submitted", "review_type": "auto_contamination",
     "triage_priority": "normal", "contamination_score": 0.94, "correction_type": "contamination_flag",
     "is_contamination": True, "created_at": _ts(10, 8, 7)},
    {"review_id": "rev_e2e_correct01", "analysis_id": ANALYSIS_ID, "sequence_id": "seq_e2e_lantern_002",
     "submitted_by": OWNER, "state": "accepted", "review_type": "manual_correction", "triage_priority": "normal",
     "correction_type": "species_correction", "proposed_taxon": "Myctophum nitidulum",
     "evidence_notes": "Photophore pattern matches M. nitidulum.", "decided_by": USERS["curator"]["sub"],
     "decided_at": _ts(11, 14), "created_at": _ts(10, 12)},
]

FIELD_ENTRIES = [
    {"entry_id": "fle_e2e_note0001", "analysis_id": ANALYSIS_ID, "kind": "note", "author_id": OWNER,
     "author_name": "Rhea Researcher", "body": "CTD cast showed an oxygen minimum near 1,200 m.",
     "anchor_sequence_id": None, "reply_to": None, "created_at": _ts(10, 9), "updated_at": _ts(10, 10),
     "edits": [{"edit_id": "fle_edit_e2e0001", "editor_id": OWNER, "editor_name": "Rhea Researcher",
                "edited_at": _ts(10, 10), "changes": [{"field": "body", "old": "CTD cast showed low oxygen.",
                                                       "new": "CTD cast showed an oxygen minimum near 1,200 m."}]}]},
    {"entry_id": "fle_e2e_cmt00001", "analysis_id": ANALYSIS_ID, "kind": "comment",
     "author_id": USERS["curator"]["sub"], "author_name": "Cyrus Curator",
     "body": "seq_e2e_novel_003 looks worth a voucher specimen.", "anchor_sequence_id": "seq_e2e_novel_003",
     "reply_to": None, "created_at": _ts(11, 9), "updated_at": None, "edits": []},
    {"entry_id": "fle_e2e_cmt00002", "analysis_id": ANALYSIS_ID, "kind": "comment", "author_id": OWNER,
     "author_name": "Rhea Researcher", "body": "Agreed, sample preserved in ethanol.", "anchor_sequence_id": None,
     "reply_to": "fle_e2e_cmt00001", "created_at": _ts(11, 10), "updated_at": None, "edits": []},
    # Field-log tasks (Industrial page). Due dates far in the past / future so
    # "overdue" does not depend on the day the fixtures are generated.
    {"entry_id": "fle_e2e_task0001", "analysis_id": ANALYSIS_ID, "kind": "task", "author_id": OWNER,
     "author_name": "Rhea Researcher", "body": "Re-extract seq_e2e_contam_005 with a fresh negative control.",
     "anchor_sequence_id": None, "reply_to": None, "task_status": "open", "due_date": "2020-01-15",
     "assignee": "Wet lab", "created_at": _ts(11, 11), "updated_at": None, "edits": []},
    {"entry_id": "fle_e2e_task0002", "analysis_id": ANALYSIS_ID, "kind": "task", "author_id": OWNER,
     "author_name": "Rhea Researcher", "body": "Send voucher request for seq_e2e_novel_003.",
     "anchor_sequence_id": None, "reply_to": None, "task_status": "done", "due_date": None,
     "assignee": None, "created_at": _ts(11, 12), "updated_at": None, "edits": []},
]

# Partner audits (Industrial page).
AUDITS = [
    {"audit_id": "aud_e2e000000001", "target": {"kind": "analysis", "ref": ANALYSIS_ID, "label": "Station 7 run"},
     "scope": "Contamination controls for the Station 7 extraction batch",
     "findings": [{"severity": "high", "description": "No negative control included", "reference": None}],
     "status": "scheduled", "due_date": "2099-03-01", "completed_at": None, "created_by": OWNER,
     "created_by_name": "Rhea Researcher", "created_at": _ts(12, 9)},
]

ATTACHMENTS = [
    {"attachment_id": "fla_e2e_ctd00001", "analysis_id": ANALYSIS_ID, "entry_id": "fle_e2e_note0001",
     "uploader_id": OWNER, "uploader_name": "Rhea Researcher", "original_filename": "ctd_cast_station7.pdf",
     "content_type": "application/pdf", "size_bytes": 248_113,
     "checksum_sha256": "4f2c9a" + "0" * 58, "created_at": _ts(10, 9, 30),
     # Server-side only: list_attachments' response_model strips these.
     "storage_uri": "local://field-log/fla_e2e_ctd00001.pdf", "storage_key": "field-log/fla_e2e_ctd00001.pdf"},
]

JOBS = [
    {"job_id": JOB_RUNNING_ID, "upload_id": UPLOAD_ID, "user_id": OWNER, "state": "inferencing",
     "analysis_id": None, "error_message": None, "queued_at": _ts(16, 8), "started_at": _ts(16, 8, 1),
     "completed_at": None, "mode": "online_full"},
    {"job_id": JOB_DONE_ID, "upload_id": UPLOAD_ID, "user_id": OWNER, "state": "completed",
     "analysis_id": ANALYSIS_ID, "error_message": None, "queued_at": _ts(10, 8), "started_at": _ts(10, 8, 1),
     "completed_at": _ts(10, 8, 5), "mode": "online_full"},
]

EXPEDITIONS = [
    {"expedition_id": EXPEDITION_ID, "name": "Carlsberg Ridge Survey", "description": "Hydrothermal vent eDNA",
     "created_by": OWNER, "status": "pre_departure", "planned_start": _ts(20), "planned_end": _ts(30),
     "vessel": "RV Sagar Nidhi", "target_depth_meters": 3200.0, "location_label": "Carlsberg Ridge",
     "offline_license_issued": False, "offline_license_expires_at": None, "synced_at": None,
     "sync_job_count": 0, "created_at": _ts(12)},
]

AUDIT_LOGS = [
    {"action": "model_registered", "model_id": "dnabert2_fish_v1", "route": "fish",
     "registry_file": "dnabert2_fish_v1.json", "checksum": "sha256:e2e", "artifact_uri": "data:heads/fish.pt",
     "training_dataset_version": "tb_2026_09_fish", "metrics": {"test_accuracy": 0.81},
     "actor_id": USERS["admin"]["sub"], "actor_email": USERS["admin"]["email"], "actor_role": "admin",
     "timestamp": _ts(14, 11)},
]


# ---------------------------------------------------------------------------
# Academia page (t-1027-1): a second, older sample whose results carry
# orchestrator decisions (so species co-occurrence has pairs), its
# environmental context, and a third upload with no coordinates or date.
# ---------------------------------------------------------------------------

ANALYSIS_BAY_ID = "ana_e2e0000000004"
UPLOAD_BAY_ID = "upl_e2e0000000002"
UPLOAD_BARE_ID = "upl_e2e0000000003"
# Real provider responses recorded live on 2026-10-18 for 15.6 N, 82.3 E,
# 2026-10-01, surface (tests/fixtures/environment/record_fixtures.py); the
# upload below is placed at exactly that point so the context is its own.
ENV_RECORDING = API_DIR / "tests" / "fixtures" / "environment" / "bay_of_bengal" / "live_results.json"


def _decided(sequence_id: str, taxon: str | None, rank: str | None, **kw) -> dict:
    r = _seq(sequence_id, kw.pop("route", "fish"), kw.pop("result_class", "known_species"), taxon=taxon, **kw)
    r["decision"] = {
        "final_route": r["route"], "result_class": r["result_class"], "predicted_taxon": taxon,
        "taxon_rank": rank, "percent_identity": None, "reference_db": None, "reference_db_version": None,
        "confidence": r["confidence"], "rule": "e2e_fixture",
    }
    return r


UPLOAD_BAY = {
    "upload_id": UPLOAD_BAY_ID,
    "user_id": OWNER,
    "original_filename": "e2e_bay_of_bengal_vizag.fasta",
    "file_size_bytes": 9_216,
    "status": "stored",
    "collected_at": datetime(2026, 10, 1, 6, 0),
    "latitude": 15.6,
    "longitude": 82.3,
    "location_label": "Bay of Bengal, off Visakhapatnam",
    "source_type": "seawater",
    "methodology": "metabarcoding",
    "created_at": _ts(2, 11),
}

UPLOAD_BARE = {
    "upload_id": UPLOAD_BARE_ID,
    "user_id": OWNER,
    "original_filename": "e2e_no_metadata.fasta",
    "file_size_bytes": 4_096,
    "status": "stored",
    "created_at": _ts(12, 14, 20),
}

ANALYSIS_BAY = {
    "analysis_id": ANALYSIS_BAY_ID,
    "job_id": "job_e2e_bay00001",
    "upload_id": UPLOAD_BAY_ID,
    "user_id": OWNER,
    "mode": "online_full",
    "model_version_set": "orchestrator-1.2.0",
    "results": [
        _decided("seq_e2e_bay_001", "Sardinella longiceps", "species", confidence=0.93),
        _decided("seq_e2e_bay_002", "Sardinella longiceps", "species", confidence=0.9),
        _decided("seq_e2e_bay_003", "Rastrelliger kanagurta", "species", confidence=0.88),
        _decided("seq_e2e_bay_004", "Thunnus albacares", "species", confidence=0.86),
        _decided("seq_e2e_bay_005", "Stolephorus", "genus", confidence=0.7),
        _decided("seq_e2e_bay_006", "Homo sapiens", "species", route="human_domestic_contamination",
                 result_class="possible_contamination", confidence=0.97, contamination=0.95, contaminated=True,
                 contamination_type="human", model="dnabert2_human_domestic_v1"),
    ],
    "created_at": _ts(2, 11, 6),
}


def _env_context_bay() -> dict:
    public = {k: v for k, v in json.loads(ENV_RECORDING.read_text(encoding="utf-8"))["surface"].items()
              if k != "transient"}
    ok = sum(1 for v in public.values() if v["status"] == "ok")
    return {
        "upload_id": UPLOAD_BAY_ID, "user_id": OWNER, "status": "complete" if ok == len(public) else "partial",
        "query": {"latitude": 15.6, "longitude": 82.3, "lookup_latitude": 15.6, "lookup_longitude": 82.3,
                  "collected_at": "2026-10-01T06:00:00+00:00", "date": "2026-10-01", "depth_m": None,
                  "target_level": "surface"},
        "cache_key": "v1:15.60:82.30:2026-10-01:surface", "cache_hit": False, "public": public,
        "requested_at": datetime(2026, 10, 18, 13, 4, 30), "retrieved_at": datetime(2026, 10, 18, 13, 4, 41),
    }


def _seed() -> dict[str, list[dict]]:
    return {
        "uploads": [UPLOAD, UPLOAD_BAY, UPLOAD_BARE],
        "analysis_results": [ANALYSIS, ANALYSIS_BAY, ORCH_ANALYSIS, LEGACY_ANALYSIS],
        "environment_contexts": [_env_context_bay()],
        "reviews": REVIEWS,
        "field_log_entries": FIELD_ENTRIES,
        "field_log_attachments": ATTACHMENTS,
        "analysis_jobs": JOBS,
        "abyss_expeditions": EXPEDITIONS,
        "audit_logs": AUDIT_LOGS,
        "audits": AUDITS,
    }


# (fixture file, role, path) -- every GET the routed pages make.
CAPTURES: list[tuple[str, str, str]] = [
    ("health", "researcher", "/health"),
    ("auth_me_researcher", "researcher", "/auth/me"),
    ("auth_me_curator", "curator", "/auth/me"),
    ("auth_me_admin", "admin", "/auth/me"),
    ("reports_list", "researcher", "/reports?limit=1"),
    ("report", "researcher", f"/reports/{ANALYSIS_ID}"),
    ("report_summary", "researcher", f"/reports/{ANALYSIS_ID}/summary"),
    ("report_novelty", "researcher", f"/reports/{ANALYSIS_ID}/novelty"),
    ("report_contamination", "researcher", f"/reports/{ANALYSIS_ID}/contamination"),
    ("reviews_by_sequence", "researcher",
     f"/reviews/by-sequence?analysis_id={ANALYSIS_ID}&sequence_id=seq_e2e_lantern_002"),
    ("reviews_stats", "curator", "/reviews/stats"),
    ("reviews_queue_submitted", "curator", "/reviews/queue?state=submitted"),
    ("field_entries_note", "researcher", f"/field-log/entries?analysis_id={ANALYSIS_ID}&kind=note"),
    ("field_entries_comment", "researcher", f"/field-log/entries?analysis_id={ANALYSIS_ID}&kind=comment"),
    ("field_attachments", "researcher", f"/field-log/attachments?analysis_id={ANALYSIS_ID}"),
    ("job_running", "researcher", f"/analysis/jobs/{JOB_RUNNING_ID}"),
    ("job_completed", "researcher", f"/analysis/jobs/{JOB_DONE_ID}"),
    ("models_registry", "admin", "/models/registry"),
    ("models_promotions", "admin", "/models/promotions?limit=10"),
    ("abyss_expeditions", "researcher", "/abyss/expeditions"),
    # Academia page (t-1027-1)
    ("environment_context", "researcher", f"/environment/uploads/{UPLOAD_ID}"),
    ("environment_context_bay", "researcher", f"/environment/uploads/{UPLOAD_BAY_ID}"),
    ("environment_not_applicable", "researcher", f"/environment/uploads/{UPLOAD_BARE_ID}"),
    ("partner_summary", "researcher", "/partner/summary"),
    ("partner_cooccurrence", "researcher", "/partner/cooccurrence?rank=species&limit=50"),
    ("partner_cooccurrence_any", "researcher", "/partner/cooccurrence?rank=any&limit=50"),
    ("partner_rhythms", "researcher", "/partner/rhythms"),
    # Legislative page (t-1027-3)
    ("partner_hotspots", "researcher", "/partner/hotspots?cell_deg=1"),
    ("partner_alerts", "researcher", "/partner/alerts?limit=100"),
    ("partner_summary_week", "researcher", "/partner/summary?interval=week&top_taxa=1"),
    # Industrial page (t-1028-2)
    ("partner_incidents", "researcher", "/partner/incidents?scope=mine"),
    ("partner_tasks", "researcher", "/partner/tasks?scope=mine"),
    ("partner_audits", "researcher", f"/partner/audits?created_by={OWNER}"),
    # Results page per-sequence calls + decision trace (t-1023-2).
    ("report_orchestrated", "researcher", f"/reports/{ORCH_ANALYSIS_ID}"),
    ("analysis_orchestrated", "researcher", f"/analysis/{ORCH_ANALYSIS_ID}?include_trace=false"),
    ("analysis_orchestrated_trace", "researcher", f"/analysis/{ORCH_ANALYSIS_ID}?include_trace=true"),
    ("analysis_legacy", "researcher", f"/analysis/{LEGACY_ANALYSIS_ID}?include_trace=false"),
    # Upload page "Auto" panel. The data root is pinned to a path that does
    # not exist (see generate()), so every head reads missing_artifacts on
    # any machine; the e2e spec edits a copy for the "served" case.
    ("models_status", "researcher", "/models/status"),
    # Last: it appends the derived custody events to the in-memory DB.
    ("report_custody", "researcher", f"/reports/{ANALYSIS_ID}/custody"),
]

# (fixture file, role, path, JSON body, expected status) -- POSTs whose error
# responses a page renders. Only requests the API refuses before touching the
# database, so the in-memory stand-in needs no write support.
POST_CAPTURES: list[tuple[str, str, str, dict, int]] = [
    # Industrial page audit form: blank label and scope, analysis target without ref.
    ("partner_audit_create_422", "researcher", "/partner/audits",
     {"target": {"kind": "analysis", "label": ""}, "scope": "", "status": "scheduled", "findings": []}, 422),
]

# /models/status checks artifacts under the data root; pin it so the fixture
# does not depend on whether this machine has synthveda-data.
E2E_DATA_ROOT = Path("/nonexistent-e2e-data-root")


def _normalise(name: str, body: Any) -> Any:
    def walk(node):
        if isinstance(node, dict):
            return {k: (FIXED_TS if k in VOLATILE_KEYS else walk(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    body = walk(body)
    if name.startswith("auth_me_"):
        body["created_at"] = FIXED_TS
    return body


async def generate() -> dict[str, Any]:
    """Return {fixture name: response JSON} from the real app."""
    tokens = {
        role: create_access_token(u["sub"], {"email": u["email"], "name": u["name"], "role": u["role"]})
        for role, u in USERS.items()
    }
    out: dict[str, Any] = {}
    # /health echoes settings (max_upload_size_mb); build the app from code
    # defaults so a developer's services/api/.env cannot make fixtures differ
    # between machines.
    defaults = Settings(_env_file=None)
    # GET /environment/uploads/{id} would schedule a live provider lookup for
    # an upload without a context doc; the recorder never goes online, so it
    # records the API's own "lookups disabled" answer instead.
    no_env_lookups = defaults.model_copy(update={"environment_context_enabled": False})
    with patch.object(mongo_module, "_db", _Db(_seed())), \
            patch.object(main_module, "get_settings", lambda: defaults), \
            patch("app.environment.router.get_settings", lambda: no_env_lookups), \
            patch.object(custody_chain, "_utc_now_iso", lambda: f"{FIXED_TS}+00:00"), \
            patch.object(models_router_module, "_resolve_data_root", lambda: E2E_DATA_ROOT):
        transport = ASGITransport(app=create_app())
        async with AsyncClient(transport=transport, base_url="http://api.test") as client:
            for name, role, path in CAPTURES:
                resp = await client.get(path, headers={"Authorization": f"Bearer {tokens[role]}"})
                if resp.status_code != 200:
                    raise RuntimeError(f"{path} as {role}: HTTP {resp.status_code} {resp.text[:300]}")
                out[name] = _normalise(name, resp.json())
            for name, role, path, payload, expected in POST_CAPTURES:
                resp = await client.post(path, json=payload, headers={"Authorization": f"Bearer {tokens[role]}"})
                if resp.status_code != expected:
                    raise RuntimeError(f"POST {path} as {role}: HTTP {resp.status_code}, expected {expected}")
                out[name] = _normalise(name, resp.json())
    return out


def dumps(body: Any) -> str:
    return json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    fixtures = asyncio.run(generate())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, body in fixtures.items():
        (OUT_DIR / f"{name}.json").write_text(dumps(body), encoding="utf-8")
    print(f"wrote {len(fixtures)} fixtures to {OUT_DIR.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
