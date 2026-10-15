# Synth Veda — Project Memory

Regularly-updated status: what's done, what's currently being worked on, per-phase
progress, what's left, what's lacking. Update this whenever a session materially
changes project status — not a diff log (`flow.md` handles that) and not a decision
log (`decisions.md` handles that), just current state.

**Not** the same thing as Claude's own cross-project memory at
`~/.claude/projects/*/memory/` — that tracks facts about the user and their projects
in general across all their repos; this file tracks Synth Veda specifically and lives
in the repo so anyone (or any agent) can read current status without conversation
history.

## Last updated

2026-09-03 — created, then same-day verified against actual source (`main.py`,
`dispatcher.py`, `job_runner.py`, `config.py`, both `requirements.txt`, `ci.yml`)
rather than left as inference. Phase-by-phase status below is now confirmed against
code for phases 1–3, 5–11, 13; phases 0, 14, 15 still need a closer look (see
`phases.md` for exactly what's confirmed vs. not).

## Currently being worked on

- **October v1 sprint (deadline 2026-10-31):** plan in `ROADMAP_REAL_DATA.md`, progress in the tracker
  linked there. End of 2026-10-14: Days 1–2 done; next are Day 3 (dead code, live `/models/status`) and the
  Day 4 learned router. Reference data re-download in progress; BOLD needs the owner's login.

- `web_frontend` Upload/New Analysis page — actively iterated per recent commits
  ("Redesign the Upload/New Analysis page...", "Update Upload/New Analysis page to the
  latest design iteration").
- Shared "liquid glass" button/input material rollout across the frontend (recent
  commits: "Replace Google's rendered widget with our own liquid-glass button",
  "Adopt Apple-style 'liquid glass' as the shared button/input material").
- A checkpoint commit ("Checkpoint before Ubuntu migration") bundled legacy cleanup,
  field log, DNA training pipeline, docs reorg, and an IEEE paper draft — suggests a
  machine migration just happened; verify nothing environment-specific (paths, Windows-
  only steps) broke as a result.
- Two untracked audit docs exist at repo root level of `docs/`:
  `docs/AUDIT_MOCKS_STUBS_TODOS.md` and `docs/ROADMAP_TO_POLISHED_TOOL.md` — read those
  for the most current, most detailed "what's left/lacking" picture; this file
  summarizes, they go deep.

## Phase progress (see `phases.md` for the full list and verification detail)

- Phase 0 (repo weight reset): partial — `.git` is 44M, no git-lfs in use, not
  alarming; model-binary-out-of-git policy not independently checked.
- Phases 1–2 (backend foundation, DB): confirmed — MongoDB is the primary store, Redis
  the queue, Supabase auth-only.
- Phase 3 (Auth): confirmed implemented and tested.
- Phases 5–8 (parser, router, model strategy, novelty scoring): all confirmed live in
  `job_runner.py`'s pipeline, not just "present." Phase 7 specifically has a real stub
  fallback (`inference_mode: "stub"`) for routes without trained weights — worth
  knowing before assuming every result used a real model.
- Phase 9 (review workflow): confirmed implemented and tested.
- Phase 10 (Abyss Mode): confirmed implemented and tested.
- Phase 11 (reports): confirmed implemented and tested.
- Phase 12 (frontend): in active iteration, not a stable "done" state.
- Phase 13 (testing/security/CI): confirmed substantial — pytest+coverage, lint+build,
  bandit scan, `.env`-tracked guard, 3-image Docker build validation. Whether it's
  currently green wasn't checked (needs an actual CI run).
- Phase 14 (training pipeline): files present, not executed/verified this session.
- Phase 15 (post-funding scaling): not started.

## Known gaps

- **2026-10-14: the heuristic router picks the correct route for 24.1% of held-out test sequences**
  (fish 0.3%, plant 0.0%). Per-route head accuracy is not system accuracy. Learned 6-mer router
  prototype: 82.4%. See `docs/qna.md` QNA-001; fix scheduled Day 4 of `ROADMAP_REAL_DATA.md`.
- Real inference now runs on all 6 routes (worker venv, `synthveda-data/checkpoints/`, `data:`
  registry paths). The raw reference data (~44 GB) was lost in the Ubuntu migration; re-fetch via
  `scripts/fetch_reference_data.sh`, with BOLD/UNITE/MIDORI2 downloaded manually.

- Species-level identification (`predicted_taxon`) unimplemented — see `prd.md` /
  `docs/ml/THEORY_README.md`.
- Inference stub fallback: any route without trained DNABERT-2 weights yet returns
  `inference_mode: "stub"` predictions rather than failing — check which routes
  actually have trained weights before trusting a batch of results as model-derived.
- Full current gap list: `docs/AUDIT_MOCKS_STUBS_TODOS.md`.
- Working plan from 2026-10-14: `docs/ROADMAP_REAL_DATA.md` (re-verified gap list + day-wise roadmap). Notable: all 6 route checkpoints now exist under `synthveda-data/checkpoints/`; real inference is blocked only by Windows paths in `models/registry/*.json` and torch not installed.
- `web_frontend/package-lock.json`'s modification (as of 2026-09-03) is npm removing
  stale `"peer": true` flags on ~5 packages — a lockfile-format normalization, not a
  real dependency change. Safe to commit standalone.
- `"PSEUDO FILE"/` (repo root, untracked, never in git history) is a design-reference
  mood board: screenshots, dashboard/UI inspiration images, and two videos including an
  81MB product-demo-style MP4. Not in `.gitignore`. Decide: gitignore it (keep locally,
  never track) or remove — leaving it untracked-but-present risks an accidental `git
  add -A` pulling in 88MB of binary assets.
- `.playwright-mcp/` (repo root, untracked) is Playwright MCP tool output — console
  logs and page snapshots from a QA session on 2026-08-17. Also not in `.gitignore`.
  Same call to make as above; this one is small (~270KB) so lower urgency.

## Docs scaffold status

This file and its siblings (`decisions.md`, `flow.md`, `prd.md`, `architecture.md`,
`rules.md`, `phases.md`, `design.md`) were created 2026-09-03 per a standing
cross-project documentation convention. They're seeded from a repo scan, not a full
audit — expect gaps until a few real sessions have run against them.
