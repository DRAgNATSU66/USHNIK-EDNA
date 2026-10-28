# Docs

Living, canonical docs (updated as the project changes, not archived once written):

- `decisions.md` — why this approach/library/function, logged as changes happen.
- `flow.md` — entry points, call order, and a session-by-session change log.
- `prd.md` — what to build, target users, features.
- `architecture.md` — actual current architecture, folder structure, tech stack.
- `rules.md` — libraries/patterns to use or avoid, error-handling boundaries, AI-harnessing rules.
- `phases.md` — phase breakdown (full detail in `architecture/SYNTH_VEDA_PHASE_PLAN.md`).
- `design.md` — color/typography/material tokens actually in use.
- `memory.md` — current status: what's done, in progress, left, lacking.
- `ROADMAP_REAL_DATA.md` — current working plan: full mock/frontend↔backend difference list and the day-wise roadmap to remove it (2026-10-14). Part A status table: what is resolved or still open (2026-10-27).
- `qna.md` — the contemporaneous, append-only record of every major change and its measured numbers (QNA-001…). The source the other docs and the paper cite.
- `AUDIT_MOCKS_STUBS_TODOS.md` — the 2026-09-03 mock/stub audit, with a resolution status per item (2026-10-27).
- `ml/results/` — measured result files (router, heads, reference lookup, orchestrator, taxon evaluation, novelty) that the paper's numbers come from.

Historical/deep-dive material (superseded by the above for current decisions, kept for
depth and context):

- `architecture/` — system design and execution roadmap.
  - `SYNTH_VEDA_PHASE_PLAN.md` — phased build plan for the full platform (backend, routing, review workflow, offline mode, scaling).
- `ml/` — modeling notes and experiment log.
  - `THEORY_README.md` — running log of modeling decisions, dead ends, and the train/test leakage investigation, kept up to date as questions come up during development.
- `specs/` — product and frontend specifications.
- `paper/` — IEEE conference paper LaTeX source (Overleaf-ready).
- `archive/` — superseded documents kept for history, not reflective of current implementation.
  - `TRAINING_READINESS_ASSESSMENT.md` — an early GPU/training-readiness checklist from before the current DNABERT-2/NT-500M training pipeline existed.
