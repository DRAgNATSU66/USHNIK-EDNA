# Synth Veda — Decisions Log

Running log of considerations behind code changes: why this approach over the
alternatives, why this library, why this function, what a function does and why it's
used here. Same spirit as `docs/ml/THEORY_README.md` (which stays focused on ML
theory/Q&A specifically) — this one is the general engineering decision log. Append new
entries at the top; don't edit past entries except to correct factual errors, and note
the correction rather than silently rewriting.

---

## 2026-10-14 (later) — Q4 answered, Q7 confirmed, re-plan

Follow-up to the entry below, which stays as written.

- **Q4:** the team does not run blanks. `negative_control_included` stays optional, and results
  show a "no negative control, contamination not ruled out" flag when it is absent (option a).
- **Q7:** the deterministic-orchestrator interpretation below is confirmed by the owner.
- **Q5 time-box moves from Day 11 (24 Oct) to Day 12 (25 Oct)** in the re-plan, because the
  orchestrator now occupies Days 9–10. The decision itself is unchanged.
- **Cut to v1.1 now, not at the 25 Oct checkpoint:** loader LRU, quantized offline models, offline
  reference pack, offline end-to-end run. This makes room for Q1/Q5/Q7 inside the 31 Oct deadline.
- **Data loss found:** the ~44 GB `synthveda-data/raw/` set lived on the old Windows `E:` drive and
  did not survive the Ubuntu migration (searched the remaining Windows partition read-only; not
  there). `scripts/fetch_reference_data.sh` re-fetches the NCBI/SILVA/UniVec/GRCh38 parts; BOLD,
  UNITE and MIDORI2 need manual downloads. Trained checkpoints and `processed/` survived.

---

## 2026-10-14 — Product decisions Q1–Q7 for the October v1 sprint

Owner answers to the open decisions in `ROADMAP_REAL_DATA.md` §A6, recorded as given. Q4 and the
interpretation of Q7 are still open at time of writing.

**Q1 — Reference data for species names: reuse + expand + retrain.** Reuse the sources
`training/sources.py` already ingests (MIDORI2, SILVA, UNITE, BOLD), add the owner's local BLAST
database (`iter_blastdb` already supports it), and gather more data from other sources. Retrain on
the expanded set. Engineering notes attached to this decision:
- Gather through official bulk downloads and APIs (NCBI E-utilities/Datasets, BOLD, ENA, MGnify),
  not HTML scraping, so every sequence keeps an accession ID and a provenance trail.
- Check each source's licence before redistributing it, especially inside the Abyss offline pack.
- Rerun the deduplication / leakage check from `docs/ml/THEORY_README.md` on the expanded set
  before retraining. Bigger data with leaked test sequences would inflate the reported metrics.
- Retraining the heads is cheap (frozen backbone, linear probe), so it fits in the sprint.

**Q2 — Upload metadata.** Only the file is required to upload. A partner report needs collection
date and coordinates. All other fields (methodology, collector, DO, pH, depth, salinity, temperature,
habitat) stay optional. **Every result must state which optional fields were provided and which
were missing**, and say that missing context can reduce accuracy. Extends the original default,
which only flagged incomplete provenance.

**Q3 — Corrections feed retraining.** Yes, through the existing monthly frozen batches.

**Q5 — Panels needing external data.** First attempt to gather real data (public feeds or
datasets) and, where a model is needed, train on it. Fall back to removal for v1 only if that fails.
Each panel gets a time-box (decision point Day 11, 2026-10-24) so the attempt cannot consume the
deadline.

**Q6 — Co-occurrence network.** Server-side top-50 taxa plus a minimum co-occurrence threshold.

**Q7 — Model selection.** Replace the inert picker with our own orchestration layer that chooses the
best model, or a combination of models and evidence sources, based on the input data. Proposed
interpretation, pending owner confirmation: a deterministic orchestrator in the worker that, per
sequence, picks candidate route models from the router's output, runs the classifier heads plus
reference lookup (vsearch/BLAST), combines their evidence, and records a decision trace the UI
shows. No LLM in the inference path (reproducibility and latency); an LLM may optionally write the
plain-language explanation. This is a routing/orchestration change and gets a `qna.md` entry when
it lands.

**Q4 — Negative control.** Open: owner asked what a negative control is. Explanation given;
awaiting the answer.

---

## 2026-09-03 — Verify-then-write instead of leave-as-inferred

**Decision:** when the scaffold docs (below) shipped with flagged unknowns —
"unverified", "check before relying on it" — the follow-up was to actually read the
relevant source (`main.py`, `dispatcher.py`, `job_runner.py`, `config.py`, both
`requirements.txt`, `ci.yml`) and correct the docs, rather than leave the hedges in
place or guess harder.

**Why:** a hedge ("unverified") is a placeholder for future work, not a substitute for
it — once asked to fill the docs in, the honest options were "go verify" or "say I
can't without more access," not "leave it vague." This surfaced real corrections (see
`flow.md`'s 2026-09-03 follow-up entry, `architecture.md`'s data-stores table,
`rules.md`'s parser/store notes) that the first pass had gotten subtly wrong — e.g. the
first pass said "Auth/DB: Supabase," which undersold that MongoDB is the actual primary
data store and Supabase is auth-only.

**Takeaway for future doc-filling sessions in this repo:** when a doc says "unverified"
or "needs a real pass," that's a todo list, not a caveat to preserve indefinitely — treat
it as workable follow-up work, not permanent hedging.

---

## 2026-09-03 — Documentation scaffold

**Decision:** Add `decisions.md`, `flow.md`, `prd.md`, `architecture.md`, `rules.md`,
`phases.md`, `design.md`, `memory.md` under `docs/` as living, canonical docs going
forward, rather than migrating/rewriting the existing `docs/specs/`,
`docs/architecture/SYNTH_VEDA_PHASE_PLAN.md`, and `docs/ml/THEORY_README.md`.

**Why:** the user asked for this exact 8-file convention to be a standing practice
across all their projects (saved to Claude's cross-project memory, not just this repo).
This project already has substantial pre-existing planning docs that predate the
convention; rewriting/merging them risked losing nuance and wasn't what was asked —
additive-first, pointing back to the legacy docs for depth, keeps both intact.

**Alternative considered:** consolidate everything into the new files immediately.
Rejected for now — large, lossy-risk migration the user didn't explicitly request;
easy to do later if they want it.

---

## Pre-existing decisions (pulled from `docs/ml/THEORY_README.md`, summarized here for discoverability — read the source for full reasoning)

**DNABERT-2 as the backbone, one fine-tuned copy per route, instead of one model for
everything.** A heuristic (non-learned) router runs first — marker-gene pattern
matching plus a Gaussian-kernel score over GC content / CpG ratio / length — and picks
one of 6 taxonomic routes before any neural model runs. Rationale is in
`docs/ml/THEORY_README.md` §1; don't change this split without reading that first.

**Novelty/contamination score is a hand-tuned weighted sum, not a trained model** —
explicitly a placeholder pending a learned-weights phase. If you're touching
`services/worker/app/novelty/scorer.py`, know that the current weights are provisional,
not validated ground truth.

**Species-level ID is not implemented.** `predicted_taxon` is `null` everywhere by
design — the system currently outputs a confidence category, not a species name. Don't
"fix" this without it being a deliberate scoped feature (needs a taxonomy-lookup layer
over the embedding space).
