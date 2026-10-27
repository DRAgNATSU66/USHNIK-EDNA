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

2026-10-27 — Day 17 docs pass (t-1030-3), re-verified against the code at `32f38ef`
(`LATEST_USHNIK`) and the measured results in `docs/ml/results/`. Earlier state (2026-09-03,
2026-10-14) is in git history; the change record for 2026-10-14 onward is `docs/qna.md`.

## Currently being worked on

- **October v1 sprint (deadline 2026-10-31):** plan in `ROADMAP_REAL_DATA.md`, progress in the tracker
  linked there. As of 2026-10-27 every tracker task through Day 17 is done except the owner's BOLD
  download (t-1014-3) and this docs pass (t-1030-3). Next: Day 18 release candidate (fresh clone →
  `make up` → full flow, tag `v1.0.0-rc1`, walk the exit criteria).
- `sprint/d15-review-fixes` is in flight and **not merged at `32f38ef`**: incidents stop counting
  human DNA expected on the human route, Novelty DNA header/footer name the reference DBs, Academia
  stale-report guard, hotspot `cell_index` edge rule, stray quotes in taxon names.

## Phase progress (see `phases.md` for the full list and verification detail)

- Phase 0 (repo weight reset): `legacy/` deleted (QNA-019); `PSEUDO FILE/`, `.playwright-mcp/` and
  `synthveda-data/` are gitignored; model weights and reference DBs live in `synthveda-data/`, never
  in git.
- Phases 1–2 (backend foundation, DB): MongoDB primary, Redis queue, object storage (local or
  S3/MinIO), Supabase for auth exchange plus a best-effort mirror that currently cannot reach its
  host.
- Phase 3 (Auth): implemented and tested; startup refuses a weak `JWT_SECRET` outside dev.
- Phase 5 (parser): Rust crate + Python fallback, unchanged.
- Phase 6 (router): **learned k-mer router v2 is the first stage** (canonical 9-mer LinearSVC,
  test 0.9155 on both strands, QNA-021/023); heuristic only as a recorded fallback.
- Phase 7 (models): all six routes run real DNABERT-2 heads (`inference_mode: "model"`); fish,
  animal, human, misc serve v2, plant and bacteria stay on v1 (QNA-023). A missing head now yields a
  labelled stub (`stub_reason`), never a random head labelled "model".
- Phase 8 (novelty/contamination): runs inside the orchestrator; centroid isolation computed but at
  weight 0; threshold 0.44 (QNA-038).
- Orchestrator (decision Q7, not in the original phase list): deterministic plan → evidence →
  combine with a stored decision trace; reference lookup gives species/genus/family names
  (QNA-020, QNA-024/025, QNA-033).
- Phase 9 (review workflow): review records (B9), route-correct batch membership, durable freeze
  (QNA-027, QNA-031).
- Phase 10 (Abyss Mode): offline learned-router copy, offline credentials not usable as API tokens,
  AbyssSetup create → licence → session → activate → triage → sync (QNA-015). Quantized offline
  models and the offline reference pack are cut to v1.1.
- Phase 11 (reports): taxa section, context block, FAIR ZIP, custody chain (QNA-029, QNA-032).
- Phase 12 (frontend): every routed page reads real data or shows an honest empty state; MockTag is
  deleted (QNA-039).
- Phase 13 (testing/security/CI): last measured on the merged tree 2026-10-27: worker 546 passed,
  API 751 passed / 3 skipped, Playwright 80/80 (QNA-038, QNA-039). CI now also runs the Playwright
  job; **not yet observed running on GitHub Actions** (nothing pushed, QNA-017).
- Phase 14 (training + release): datasets rebuilt, heads and router retrained and promoted through
  the API; the full loop upload → review → batch → freeze → register → promote passes as one opt-in
  test (QNA-031). No retrain has yet been run *from* a curated batch.
- Phase 15 (scaling): not started.

## Known gaps

- **Measured accuracy, as measured** (cite these, not the v1 registry numbers, which came from the
  leaky v0 test set — QNA-016):
  - Router: heuristic 24.1% (QNA-001) → learned v1 0.8644 on 1,800 protocol rows (QNA-010) →
    v2 0.9155 on the rebuilt 8,300-row test set, identical on reverse complement (QNA-021).
  - Route heads v2 on the rebuilt test split: fish .899, plant .916 (v1 .956 on the same rows, so
    plant stays on v1), bacteria .832 (tie with v1), animal .876 (overfits; likely_taxonomic_group
    F1 .410 on 27 rows), human .979, misc .936 (QNA-022).
  - Orchestrator final route .8898 vs router-only .8798 on 599 held-out rows; result_class agreement
    with dataset labels .773 vs .8631 for router+head, by the owner's reference-wins rule (QNA-025,
    QNA-030).
  - Taxon assignment on 8,668 held-out rows: species P/R 89.1/34.0, genus 95.2/58.4, family
    97.2/77.8 (QNA-033). Recall is low by design (precision-first thresholds, plant genus cap).
- Open issues (detail and sources in `architecture.md` → Known open issues): Supabase host does not
  resolve and migrations `20261018000001` / `20261019000001` are unapplied; no proxy rate limit in
  front of Cloud Run; `POST /reviews` accepts any user for any analysis; BOLD not downloaded; one
  `analysis_results` document hits the 16 MB Mongo limit at about 950 sequences.
- Not measured: any evaluation on real field eDNA reads. Every number above is on held-out splits of
  reference-database records.
- `scripts/seed_dev.py` still seeds mock analysis results (B20). Never run it against a database that
  feeds a demo or report.
- Full audit status: `docs/AUDIT_MOCKS_STUBS_TODOS.md` (each item marked resolved or open).
- `web_frontend/package-lock.json`'s modification (as of 2026-09-03) is npm removing
  stale `"peer": true` flags on ~5 packages — a lockfile-format normalization, not a
  real dependency change. Safe to commit standalone.
- Unused npm dependencies (`three`, `@react-three/*`, `chart.js`, `react-chartjs-2`, `axios`,
  `recharts`, `react-icons`, `lucide-react`) are still in `package.json` (QNA-002 Q6).

## Docs scaffold status

This file and its siblings (`decisions.md`, `flow.md`, `prd.md`, `architecture.md`,
`rules.md`, `phases.md`, `design.md`) were created 2026-09-03 per a standing
cross-project documentation convention. They were seeded from a repo scan. On 2026-10-27
`architecture.md`, `flow.md`, `phases.md` and this file were re-verified against the code at
`32f38ef`; `prd.md`, `rules.md`, `design.md` and `decisions.md` were not part of that pass.
