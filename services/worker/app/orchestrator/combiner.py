"""
Combiner: the deterministic rules that turn a sequence's evidence into one
answer. Three ordered rule tables, first match wins, and every step is
written to the decision trace's "combine" list.

1. ROUTE_RULES -- which candidate route's evidence the answer uses.

  rule                         when                                                         final route
  ---------------------------  -----------------------------------------------------------  ------------------------
  low_quality_gate             the QC gate routed it to low_quality                         low_quality
  single_route                 only one route was planned                                   that route
  reference_confirms_router    a candidate has a strong reference hit (assigned, identity   the router's top pick
                               >= REFERENCE_SPECIES_IDENTITY) and the top pick's hit is
                               within REFERENCE_TIE_DELTA of the best
  reference_overrides_router   ... and another candidate's hit beats the top pick's by      that candidate
                               more than REFERENCE_TIE_DELTA
  reference_hit_outside_router no strong hit; the top pick's reference DB was searched and  the candidate with the
                               has no assignment, another candidate's has one               best assigned identity
  router_primary               otherwise (including reference unavailable: heads only)      the router's top pick

   Heads never choose the route: each head was trained only on its own
   route's sequences, so a fish head's 0.9 on a plant read says nothing, and
   probabilities from different heads (different label sets) are not
   comparable. Head disagreement across candidates is recorded
   ("heads_disagree"), as is a reference lineage that implies a route other
   than the router's ("reference_lineage_vs_router"). The reference
   identity IS comparable across routes (same aligner, same coverage floor)
   and each route DB holds only that route's lineages.

2. Taxon, from the final route's reference evidence when it is assigned.
   genus_cap: on ORCHESTRATOR_GENUS_CAP_ROUTES (plant) or a Viridiplantae
   lineage, a species name is cut back to its genus (plant species precision
   51.9 %, QNA-020 Q4). Reference unavailable -> "heads_only", no taxon.

3. CLASS_RULES -- the result_class.

  rule                             when                                                    result_class
  -------------------------------  ------------------------------------------------------  -----------------------------
  qc_gate                          final route low_quality                                 low_quality_unusable
  grch38_contamination             GRCh38 marked it human contamination, final route is    possible_contamination
                                   not the human route (whose head separates human/
                                   domestic species from lab vectors)
  head_low_quality                 the head says low_quality_unusable                      low_quality_unusable
  contamination_gates_novelty      head says possible_novelty, contamination flagged       possible_contamination
  novelty_suppressed_by_reference  head says possible_novelty, reference names a species   known_species
                                   (assigned, effective rank species)
  novelty_downgraded_by_reference  head says possible_novelty, identity >= species cut-    likely_taxonomic_group
                                   off but the effective rank is coarser (genus cap, LCA)
  head_class                       the head ran                                            the head's class
  reference_only                   no head prediction, reference assigned                  known_species if species
                                                                                           rank, else likely_taxonomic_group
  no_evidence                      neither                                                 unknown_needs_online_confirmation

   Novelty score: the scorer's score times a gate, like the scorer's own
   contamination gate. Gate 0 when contamination is flagged
   (contamination_gates_novelty) or the reference names a species
   (novelty_suppressed_by_reference); otherwise 1. A downgrade keeps the
   score, so a flagged sequence still reaches a reviewer. The raw score and
   the gate are both in the trace.

Pure functions over EvidenceRecord.to_dict() dicts; no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.orchestrator.lineage import implied_route
from app.orchestrator.planner import LOW_QUALITY_ROUTE, REFERENCE_MISS_STATUSES, Plan

HUMAN_ROUTE = "human_domestic_contamination"
PLANT_KINGDOMS = frozenset({"Viridiplantae", "Plantae"})


def _ok(rec: dict | None) -> bool:
    return bool(rec) and rec.get("status") == "ok"


def _assigned(rec: dict | None) -> bool:
    return _ok(rec) and (rec.get("payload") or {}).get("status") == "assigned"


def _identity(rec: dict | None) -> float | None:
    v = (rec or {}).get("payload", {}).get("identity") if rec else None
    return float(v) if v is not None else None


def _step(step: str, rule: str, outcome: Any, detail: str | None = None) -> dict:
    return {"step": step, "rule": rule, "outcome": outcome, "detail": detail}


# ---------------------------------------------------------------------------
# 1. route
# ---------------------------------------------------------------------------

def select_route(plan: Plan, heads: dict[str, dict], refs: dict[str, dict], settings: Any
                 ) -> tuple[str, list[dict]]:
    """(final route, combine steps). heads/refs: route -> evidence dict."""
    steps: list[dict] = []
    primary = plan.primary_route

    # Recorded disagreements (they inform, they do not decide).
    head_classes = {r: (heads[r].get("payload") or {}).get("result_class")
                    for r in plan.routes if _ok(heads.get(r))}
    if len(set(head_classes.values())) > 1:
        steps.append(_step("disagreement", "heads_disagree", head_classes,
                           "candidate heads give different classes; heads do not choose the route"))
    for r in plan.routes:
        if _assigned(refs.get(r)):
            p = refs[r]["payload"]
            imp = implied_route(p.get("lineage"))
            if imp and imp != primary:
                steps.append(_step("disagreement", "reference_lineage_vs_router",
                                   {"reference_route": r, "implied_route": imp, "router_route": primary,
                                    "taxon": p.get("taxon"), "identity": p.get("identity")},
                                   f"{r} reference hit {p.get('taxon')} at {p.get('identity')}% has a {imp} "
                                   f"lineage; the router said {primary}"))

    if primary == LOW_QUALITY_ROUTE:
        steps.append(_step("route", "low_quality_gate", primary))
        return primary, steps
    if len(plan.routes) == 1:
        steps.append(_step("route", "single_route", primary))
        return primary, steps

    species_cut = float(settings.reference_species_identity)
    tie = float(settings.reference_tie_delta)
    order = {r: i for i, r in enumerate(plan.routes)}   # primary first, then router rank

    strong = [r for r in plan.routes if _assigned(refs.get(r)) and (_identity(refs[r]) or 0) >= species_cut]
    if strong:
        best = max(strong, key=lambda r: (_identity(refs[r]), -order[r]))
        best_id = _identity(refs[best])
        p_id = _identity(refs[primary]) if _assigned(refs.get(primary)) else None
        if p_id is not None and p_id >= best_id - tie:
            steps.append(_step("route", "reference_confirms_router", primary,
                               f"{primary} reference identity {p_id}% is within {tie:g} of the best ({best_id}%)"))
            return primary, steps
        steps.append(_step("route", "reference_overrides_router", best,
                           f"{best} reference identity {best_id}% vs {primary} "
                           f"{'%s%%' % p_id if p_id is not None else 'no assignment'} (tie delta {tie:g})"))
        return best, steps

    prim_ref = refs.get(primary)
    if _ok(prim_ref) and (prim_ref.get("payload") or {}).get("status") in REFERENCE_MISS_STATUSES:
        others = [r for r in plan.routes if r != primary and _assigned(refs.get(r))]
        if others:
            best = max(others, key=lambda r: (_identity(refs[r]) or 0, -order[r]))
            steps.append(_step("route", "reference_hit_outside_router", best,
                               f"{primary} reference: {prim_ref['payload'].get('status')}; {best} reference assigned "
                               f"at {_identity(refs[best])}%"))
            return best, steps

    if not any(_ok(refs.get(r)) for r in plan.routes):
        why = "reference lookup unavailable for every candidate route: heads only"
    else:
        why = "no reference evidence separates the candidates"
    steps.append(_step("route", "router_primary", primary, why))
    return primary, steps


# ---------------------------------------------------------------------------
# 2-3. taxon, class, novelty
# ---------------------------------------------------------------------------

@dataclass
class CombineInput:
    final_route: str
    head: dict | None            # evidence dicts (to_dict()); None if not collected
    reference: dict | None
    contamination: dict | None
    novelty: dict | None
    reference_enabled: bool = True
    # derived by combine():
    eff_taxon: str | None = None
    eff_rank: str | None = None
    species_cut: float = 97.0
    extras: dict = field(default_factory=dict)

    @property
    def head_ok(self) -> bool:
        return _ok(self.head)

    @property
    def head_class(self) -> str | None:
        return (self.head.get("payload") or {}).get("result_class") if self.head_ok else None

    @property
    def assigned(self) -> bool:
        return _assigned(self.reference)

    @property
    def identity(self) -> float | None:
        return _identity(self.reference) if self.assigned else None

    @property
    def contamination_flagged(self) -> bool:
        return _ok(self.contamination) and bool(self.contamination["payload"].get("flagged"))

    @property
    def grch38(self) -> bool:
        return _ok(self.contamination) and bool(self.contamination["payload"].get("grch38_contamination"))


ClassRule = tuple[str, Callable[[CombineInput], bool], Callable[[CombineInput], str]]

CLASS_RULES: list[ClassRule] = [
    ("qc_gate", lambda c: c.final_route == LOW_QUALITY_ROUTE, lambda c: "low_quality_unusable"),
    ("grch38_contamination", lambda c: c.grch38 and c.final_route != HUMAN_ROUTE,
     lambda c: "possible_contamination"),
    ("head_low_quality", lambda c: c.head_class == "low_quality_unusable", lambda c: "low_quality_unusable"),
    ("contamination_gates_novelty", lambda c: c.head_class == "possible_novelty" and c.contamination_flagged,
     lambda c: "possible_contamination"),
    ("novelty_suppressed_by_reference",
     lambda c: c.head_class == "possible_novelty" and c.assigned and c.eff_rank == "species",
     lambda c: "known_species"),
    ("novelty_downgraded_by_reference",
     lambda c: c.head_class == "possible_novelty" and c.assigned and (c.identity or 0) >= c.species_cut,
     lambda c: "likely_taxonomic_group"),
    ("head_class", lambda c: c.head_ok, lambda c: c.head_class),
    ("reference_only", lambda c: c.assigned,
     lambda c: "known_species" if c.eff_rank == "species" else "likely_taxonomic_group"),
    ("no_evidence", lambda c: True, lambda c: "unknown_needs_online_confirmation"),
]


def _genus_of(lineage: dict) -> tuple[str | None, str | None]:
    for rank in ("genus", "family", "order", "class", "phylum", "kingdom", "superkingdom"):
        if lineage.get(rank):
            return lineage[rank], rank
    return None, None


def combine(c: CombineInput, settings: Any, novelty_threshold: float) -> tuple[dict, list[dict], dict]:
    """(decision, combine steps, novelty outcome). decision is the shared
    contract's "decision" dict."""
    steps: list[dict] = []
    c.species_cut = float(settings.reference_species_identity)
    ref = c.reference
    payload = (ref or {}).get("payload") or {}

    # -- taxon ----------------------------------------------------------------
    if c.final_route == LOW_QUALITY_ROUTE:
        pass
    elif not c.reference_enabled:
        steps.append(_step("taxon", "heads_only", None, "reference lookup disabled (ORCHESTRATOR_REFERENCE_ENABLED)"))
    elif not _ok(ref):
        steps.append(_step("taxon", "heads_only", None,
                           f"reference lookup unavailable: {(ref or {}).get('reason') or 'not run'}"))
    elif not c.assigned:
        hits = payload.get("hits") or []
        steps.append(_step("taxon", "no_reference_assignment", payload.get("status"),
                           (payload.get("reason") or "") + (f"; nearest hit {hits[0].get('identity')}%" if hits else "")))
    else:
        c.eff_taxon, c.eff_rank = payload.get("taxon"), payload.get("rank")
        lineage = payload.get("lineage") or {}
        capped_route = c.reference.get("route") in set(settings.orchestrator_genus_cap_routes or [])
        if c.eff_rank == "species" and (capped_route or lineage.get("kingdom") in PLANT_KINGDOMS):
            g, grank = _genus_of(lineage)
            steps.append(_step("taxon", "genus_cap", {"from": c.eff_taxon, "to": g},
                               "plant species names are capped at genus (species precision 51.9%, QNA-020 Q4)"))
            c.eff_taxon, c.eff_rank = g, grank
        steps.append(_step("taxon", "reference_taxon", {"taxon": c.eff_taxon, "rank": c.eff_rank},
                           f"{payload.get('identity')}% identity, {payload.get('reference_db')} "
                           f"{payload.get('reference_db_version')}"))

    # -- class ----------------------------------------------------------------
    rule_name, result_class = "no_evidence", "unknown_needs_online_confirmation"
    for name, when, then in CLASS_RULES:
        if when(c):
            rule_name, result_class = name, then(c)
            break
    detail = None
    if rule_name in ("novelty_suppressed_by_reference", "novelty_downgraded_by_reference"):
        detail = (f"head said possible_novelty; reference {c.eff_taxon} ({c.eff_rank}) at {c.identity}% "
                  "counts against novelty (QNA-020 Q4)")
    elif rule_name == "contamination_gates_novelty":
        detail = "head said possible_novelty; contamination flagged"
    elif rule_name == "head_class" and c.head_class == "known_species" and _ok(ref) and not c.assigned:
        detail = "head says known_species but the reference has no assignment"
    elif rule_name == "head_class" and c.head_class == "known_species" and c.assigned and c.eff_rank != "species":
        detail = f"head says known_species; reference resolves only to {c.eff_rank}"
    steps.append(_step("class", rule_name, result_class, detail))

    # -- novelty gate -----------------------------------------------------------
    nov = c.novelty if _ok(c.novelty) else None
    raw = float(nov["payload"]["novelty_score"]) if nov else None
    gate, gate_rule = 1.0, None
    if nov is not None:
        if c.contamination_flagged:
            gate, gate_rule = 0.0, "contamination_gates_novelty"
        elif c.assigned and c.eff_rank == "species":
            gate, gate_rule = 0.0, "novelty_suppressed_by_reference"
        elif c.assigned and (c.identity or 0) >= c.species_cut and raw is not None and raw >= novelty_threshold:
            gate_rule = "novelty_downgraded_by_reference"
    raw_flag = (raw is not None and raw >= novelty_threshold) or c.head_class == "possible_novelty"
    final_score = round(raw * gate, 4) if raw is not None else None
    final_flag = (final_score is not None and final_score >= novelty_threshold) or result_class == "possible_novelty"
    if nov is None:
        steps.append(_step("novelty", "novelty_unscored", None, (c.novelty or {}).get("reason")))
    elif gate_rule:
        steps.append(_step("novelty", gate_rule, {"raw": raw, "gate": gate, "final": final_score},
                           "flag kept for review: the reference cannot resolve the species"
                           if gate == 1.0 else None))
    novelty = {"raw_score": raw, "gate": gate, "final_score": final_score, "gate_rule": gate_rule,
               "raw_flag": raw_flag, "final_flag": final_flag,
               "suppressed_by_reference": raw_flag and not final_flag and gate_rule == "novelty_suppressed_by_reference"}

    head_conf = (c.head.get("payload") or {}).get("confidence") if c.head_ok else None
    decision = {
        "final_route": c.final_route,
        "result_class": result_class,
        "predicted_taxon": c.eff_taxon,
        "taxon_rank": c.eff_rank,
        "percent_identity": c.identity,
        "reference_db": payload.get("reference_db") if _ok(ref) else None,
        "reference_db_version": payload.get("reference_db_version") if _ok(ref) else None,
        "confidence": head_conf,
        "rule": rule_name,
    }
    return decision, steps, novelty
