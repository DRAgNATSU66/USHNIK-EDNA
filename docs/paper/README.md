# Paper

IEEE conference paper draft for Synth Veda, built from the evaluation results in
`E:\synthveda-data\checkpoints\*\eval_report.json` and the architecture actually
implemented in `services/api` and `services/worker`.

## Compiling in Overleaf

1. Create a new blank project in Overleaf.
2. Upload `main.tex`, `references.bib`, and the `figures/` folder (keep the folder name).
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
  independently verified against the publisher record for each one.
- **Run a plagiarism/AI-detection pass** through whatever tool your venue
  uses. The prose was written directly from this project's own results and
  architecture (not paraphrased from another paper), but you may still want
  to read it aloud once — a piece written in one sitting can pick up
  repeated sentence rhythms that are worth breaking up by ear.
- The paper is deliberately honest about what's heuristic/placeholder vs.
  learned in the system (router, novelty-score embedding signal, offline
  mode). Don't tighten that language to sound more finished than the system
  is — that's the actual defensible core of the paper.
