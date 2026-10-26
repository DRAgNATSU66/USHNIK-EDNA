// ConfidenceChip props for the per-sequence scores this deployment computes
// (D6, t-1028-3). One place for the wording so every page qualifies the same
// score the same way. Each basis names how the worker actually produces it:
//
//   novelty_score        services/worker/app/novelty/scorer.py -- expert-set
//                        weights over six signals (route-head class and
//                        confidence, read quality, contamination gate, label
//                        entropy, embedding isolation); not fitted, not
//                        calibrated.
//   contamination_score  services/worker/app/novelty/contamination.py --
//                        route, marker-motif and sequence-composition signals
//                        combined by hand-set rules; not calibrated.
//   percent_identity     decision.percent_identity -- identity of the single
//                        best reference hit the orchestrator kept; no
//                        uncertainty is estimated for it.
//
// Route-head class scores have their own wording in
// components/results/SequenceCalls.jsx (confidenceProps).

export const NOVELTY_CHIP = { basis: "6 expert-weighted signals", confidence: "uncalibrated score" };

export const CONTAMINATION_CHIP = { basis: "route, marker and composition signals", confidence: "uncalibrated score" };

/** Chip props for a decision's percent identity, naming the database searched. */
export function identityChip(decision) {
  const db = decision?.reference_db;
  const version = decision?.reference_db_version ? ` v${String(decision.reference_db_version).replace(/^v/i, "")}` : "";
  return {
    basis: db ? `best hit in ${db}${version}` : "best reference hit",
    confidence: "not estimated (single hit)",
  };
}
