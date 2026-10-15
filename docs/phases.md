# Synth Veda — Phases

Summary index of the development phases. Full detail (goals, why, done-criteria) for
each phase lives in `docs/architecture/SYNTH_VEDA_PHASE_PLAN.md` — this file is the
quick-reference map; `memory.md` tracks actual current progress against it.

| # | Phase | Covers |
|---|---|---|
| 0 | Repository Weight Reset | Strip generated/large-binary cruft from the repo, decide where model artifacts live outside Git |
| 1 | Backend Foundation | Real backend contract (`services/api`) before touching the frontend |
| 2 | Database Architecture | Data model/schema |
| 3 | Auth And Roles | Auth system, role-based access |
| 4 | Hosting And Runtime Strategy | Deployment/runtime approach |
| 5 | Fast FASTA/JSON Parser And Batching Engine | `fastx_parser`, JSONL batching |
| 6 | Taxonomic Router | Heuristic pre-model router, 6 routes |
| 7 | Foundation DNA Model Strategy | DNABERT-2 backbone, per-route fine-tuning |
| 8 | Novelty And Contamination Scoring | `novelty/scorer.py` weighted-sum scorer |
| 9 | Human-In-The-Loop Review | Expert/admin correction workflow |
| 10 | Abyss Mode | Offline field triage mode |
| 11 | Backend Reports And Export | Report generation/export |
| 12 | Frontend Rebuild | `web_frontend` React/Vite app |
| 13 | Testing, Security, And CI | Test suites, CI, security hardening |
| 14 | Model Training And Monthly Release Process | `services/worker/training/` fine-tuning pipeline, retraining cadence |
| 15 | Planned Scaling After Funding | Post-funding scale-out — not yet started as of 2026-09-03 |

## Reading this against the repo (verified 2026-09-03, not just file presence)

- Phases 1–2 (backend/DB): confirmed. `services/api/app/main.py` wires MongoDB
  (`motor`/`pymongo`, db `synthveda`) as the primary store, Redis as the job queue,
  Supabase for auth only — see `architecture.md`'s data-stores table.
- Phase 3 (Auth): confirmed implemented — `app/auth` router registered in `main.py`,
  tests `test_auth.py`, `test_auth_phase3.py`, `test_auth_supabase.py`.
- Phase 5 (Parser): confirmed real, not a stub — `packages/fastx_parser` is a Rust
  crate with its own binary and a Python fallback, called from
  `job_runner._stage_parse`.
- Phase 6 (Router): confirmed live — `job_runner._stage_route` calls
  `app/model_router.route_batch` for every job, heuristic (marker-gene + biophysical
  score), no learned weights.
- Phase 7 (Model strategy): confirmed live but with a real fallback —
  `job_runner._stage_infer` runs the trained DNABERT-2 classifier when weights exist
  for a route, else returns a stub prediction (`inference_mode: "stub"`). Treat "Phase
  7 done" as "the pipeline plumbing is done", not "every route has trained weights."
- Phase 8 (Novelty/contamination): confirmed live — `job_runner._stage_novelty` runs on
  every job; contamination is scored first and gates the novelty score.
- Phase 9 (Review workflow): confirmed — `app/reviews` router registered, tests
  `test_reviews.py`, `test_reviews_phase9.py`.
- Phase 10 (Abyss Mode): confirmed — `app/abyss` and `app/field_log` routers
  registered, tests `test_abyss_phase10.py`, `test_field_log.py`.
- Phase 11 (Reports): confirmed — `app/reports` router registered, tests
  `test_reports_phase11.py`.
- Phase 12 (Frontend): in active iteration, not a stable "done" state — most recent
  commits are redesigns of the Upload/New Analysis page and the shared "liquid glass"
  material (see `design.md`).
- Phase 13 (Testing/Security/CI): confirmed substantial, not just "present" —
  `.github/workflows/ci.yml` runs pytest+coverage for both Python services, frontend
  lint+build, `bandit` security scan on both services, a tracked-`.env` guard, and a
  3-image Docker build validation on push. Not verified: whether it's actually green on
  the current branch — that needs a CI run, not a repo read.
- Phase 14 (Training pipeline): present (`services/worker/training/`), not run-verified
  this session — didn't execute it, only confirmed the files exist and job_runner
  references the trained-model path it produces.
- Phase 0 (Repo weight reset): partially — `.git` is 44M (not alarmingly large), no
  `git lfs` in use. Model binaries policy (keep out of git) not independently verified.
- Phase 15 (Scaling): no evidence, not started.

Update `memory.md` — not this file — as phases actually complete or stall.
