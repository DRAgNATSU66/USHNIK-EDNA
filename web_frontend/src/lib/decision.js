// Readers for the worker orchestrator's per-sequence answer (decision Q7,
// orchestrator-1.2.0; docs/qna.md QNA-024/025/030).
//
// A stored result row carries `decision` {final_route, result_class,
// predicted_taxon, taxon_rank, percent_identity, reference_db,
// reference_db_version, confidence, rule} and `decision_trace` {plan,
// evidence, combine}. Rows written before the orchestrator have neither, and
// the report endpoints may carry the same fields flat on the row. Every
// reader here takes decision.* first, then the flat field, then null -- it
// never fills a gap with a guess.

/** One sequence's final call, read from decision.* with flat-field fallback. */
export function taxonCall(row) {
  const d = row?.decision ?? null;
  const pick = (k) => (d && d[k] != null ? d[k] : row?.[k] ?? null);
  return {
    hasDecision: Boolean(d),
    taxon: pick("predicted_taxon"),
    rank: pick("taxon_rank"),
    percentIdentity: pick("percent_identity"),
    referenceDb: pick("reference_db"),
    referenceDbVersion: pick("reference_db_version"),
    resultClass: (d && d.result_class) || row?.result_class || null,
    finalRoute: (d && d.final_route) || row?.route || null,
    // The router's own top pick; differs from finalRoute when reference
    // evidence moved the read (rule reference_overrides_router etc.).
    routerRoute: row?.router_route ?? null,
    // With a decision, confidence is the final route head's top-class score
    // and null when no head ran. The legacy flat field stores 0.0 for "no
    // head", so it is only used for rows without a decision.
    confidence: d ? (d.confidence ?? null) : (row?.confidence ?? null),
    rule: d?.rule ?? null,
  };
}

// One footer line for the reference DBs the sequence calls were matched
// against. Orchestrated rows each name their route's DB
// ("synthveda-reference/fish" v2); when they share a root and a version the
// footer names that, otherwise it points to the per-sequence tags. Until the
// rows load (or if they fail) the tag keeps its default pending label.
// Takes GET /analysis rows (decision.*) or report rows (flat fields).
export function summarizeReferenceDbs(results) {
  if (!results) return { referenceDb: null, referenceDbVersion: null, missingLabel: undefined };
  const calls = results.map(taxonCall).filter((c) => c.referenceDb);
  if (calls.length === 0) {
    const anyDecision = results.some((r) => r.decision || r.taxon_source === "decision");
    return {
      referenceDb: null,
      referenceDbVersion: null,
      missingLabel: anyDecision
        ? "Reference DB: no sequence was matched against one"
        : "Reference DB: none recorded (pre-orchestrator analysis)",
    };
  }
  const dbs = [...new Set(calls.map((c) => c.referenceDb))];
  const versions = [...new Set(calls.map((c) => c.referenceDbVersion ?? ""))];
  const roots = [...new Set(dbs.map((d) => d.split("/")[0]))];
  if (dbs.length === 1 && versions.length === 1) return { referenceDb: dbs[0], referenceDbVersion: versions[0] || null };
  if (roots.length === 1 && versions.length === 1) {
    return { referenceDb: `${roots[0]} (${dbs.length} route DBs)`, referenceDbVersion: versions[0] || null };
  }
  return { referenceDb: `${dbs.length} reference DBs (see each sequence)`, referenceDbVersion: null };
}

export function formatIdentity(pid) {
  if (pid == null || !Number.isFinite(Number(pid))) return null;
  return `${Number(pid).toFixed(2).replace(/\.?0+$/, "")}%`;
}

export function formatScore(x, digits = 1) {
  if (x == null || !Number.isFinite(Number(x))) return null;
  return `${(Number(x) * 100).toFixed(digits)}%`;
}

// Plain-language text for the rule codes the planner and combiner write.
// Source of truth: services/worker/app/orchestrator/{planner,combiner}.py
// module docstrings. An unknown code is shown as-is, never hidden.
export const RULE_TEXT = {
  // plan, router stage
  confident_router: "Router was confident: one route planned",
  router_uncalibrated: "Heuristic router (scores are not calibrated): extra routes planned",
  low_confidence: "Router's top probability below the threshold: extra routes planned",
  narrow_margin: "Top two routes too close: extra routes planned",
  weak_route: "Router's top pick is a route it often gets wrong: extra routes planned",
  low_quality_gate: "QC gate sent the read to low_quality",
  route_cap: "Route cap of 1: no extra route planned",
  // plan, after the primary reference lookup
  reference_miss: "No assignable hit in the primary reference DB: router's next route added",
  reference_lineage_route: "Primary reference hit's lineage belongs to another route: that route added",
  // route
  single_route: "Only one route was planned",
  grch38_human_route: "GRCh38 search marked the read human and no other candidate matched closer",
  reference_confirms_router: "Reference evidence agrees with the router's pick",
  reference_overrides_router: "Another route's reference hit beat the router's pick by more than the tie margin",
  reference_hit_outside_router: "Router's route had no assignment; another route's reference placed the read",
  router_primary: "No deciding reference evidence: router's pick kept",
  // disagreements (recorded, never decide)
  heads_disagree: "Candidate route heads gave different classes (heads do not choose the route)",
  reference_lineage_vs_router: "A reference lineage points to a route other than the router's",
  // taxon
  reference_taxon: "Taxon from the final route's reference assignment",
  genus_cap: "Plant species name capped at genus (species precision 51.9%, QNA-020)",
  heads_only: "No reference evidence: no taxon",
  no_reference_assignment: "Reference searched, no assignment",
  // contamination
  grch38_beaten_by_closer_assignment: "GRCh38 hit beaten by a closer non-human assignment: not human contamination",
  // class
  qc_gate: "Final route low_quality",
  grch38_contamination: "GRCh38 marked it human contamination off the human route",
  head_low_quality: "Route head says low quality",
  contamination_gates_novelty: "Head said possible novelty, but contamination is flagged",
  novelty_suppressed_by_reference: "Head said possible novelty, but the reference names a species",
  novelty_downgraded_by_reference: "Head said possible novelty; reference ≥ species cut-off but only to a coarser rank",
  head_class: "Class from the final route's head",
  reference_only: "No head prediction: class from the reference rank",
  no_evidence: "Neither a head nor a reference assignment",
  // novelty gate
  novelty_unscored: "Novelty not scored",
  novelty_ungated: "Novelty score not gated",
};

export const ruleText = (code) => RULE_TEXT[code] ?? code;
