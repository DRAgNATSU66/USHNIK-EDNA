# Paper

IEEE conference paper draft for Synth Veda. Revised 2026-10-27 (Day 17, t-1030-3) to match the
code at `32f38ef` and the measured results. Every number traces to a file: the source list is the
comment block at the top of `main.tex` (router and head `eval_report.json` files under
`synthveda-data/checkpoints/`, `docs/ml/results/*`, `docs/ml/THEORY_README.md` for the August
history, and the `docs/qna.md` entries). The August draft (heuristic router, v1 heads on the leaky
August splits, NT-500M as the bacteria model) is in git history (`492b20a`) and
`synthveda_ieee_paper.zip`; its per-route accuracies are no longer reported as results.

Figures are regenerated from the committed results by `make_figures.py` (needs matplotlib;
it plots stored values and recomputes nothing).

## Compiling in Overleaf

1. Create a new blank project in Overleaf.
2. Upload `main.tex`, `references.bib`, and the `figures/` folder (keep the folder name).
   `synthveda_ieee_paper.zip` is the **August** draft, not this revision.
3. Set the compiler to **pdfLaTeX** and the main document to `main.tex`.
4. Compile twice (once for citations to resolve via BibTeX/biber, once to settle cross-references).

No local LaTeX toolchain was available in this environment to compile-check the
source directly; it was reviewed by hand for balanced environments, brace
matching, and consistent citation/label keys, but do a first Overleaf compile
before trusting it fully.

## Before submitting

- **Fill in the author block** (`\author{...}` near the top of `main.tex`) —
  it's currently a placeholder.
- **Page count**: current draft is written to comfortably fit 12 pages in the
  two-column `IEEEtran` conference format, but actual page count depends on
  Overleaf's rendering — check after first compile and trim if needed.
- **Double-check bibliography details** (exact volume/page numbers) against
  the original sources before submission — the entries in `references.bib`
  reflect real, correctly-attributed papers, but exact page ranges were not
  independently verified against the publisher record for each one. The six entries added on
  2026-10-27 (BLAST+, VSEARCH, SILVA, MIDORI2, UNITE, temperature scaling)
  were written from memory of the published records and need the same check.
- **Run a plagiarism/AI-detection pass** through whatever tool your venue
  uses. The prose was written directly from this project's own results and
  architecture (not paraphrased from another paper), but you may still want
  to read it aloud once — a piece written in one sitting can pick up
  repeated sentence rhythms that are worth breaking up by ear.
- The paper is deliberately honest about what's rule-based vs. learned in the
  system (orchestrator rules, novelty weights, offline mode), and reports the
  unflattering numbers as measured (24.1% heuristic router, species recall
  34.0%, label agreement 77.3% vs 86.3%, centroid novelty at weight 0). Don't tighten that language to sound more finished than the system
  is — that's the actual defensible core of the paper.
