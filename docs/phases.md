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
| 6 | Taxonomic Router | Learned k-mer router (served: `kmer_router_v2`), heuristic as fallback, 6 routes |
| 7 | Foundation DNA Model Strategy | DNABERT-2 backbone, per-route fine-tuning (v2 heads on fish/animal/human/misc, v1 on plant/bacteria) |
| 8 | Novelty And Contamination Scoring | `novelty/scorer.py` weighted-sum scorer, run per sequence by the orchestrator |
| 9 | Human-In-The-Loop Review | Expert/admin correction workflow |
| 10 | Abyss Mode | Offline field triage mode |
| 11 | Backend Reports And Export | Report generation/export |
| 12 | Frontend Rebuild | `web_frontend` React/Vite app |
| 13 | Testing, Security, And CI | Test suites, CI, security hardening |
| 14 | Model Training And Monthly Release Process | `services/worker/training/` fine-tuning pipeline, retraining cadence |
| 15 | Planned Scaling After Funding | Post-funding scale-out — not yet started as of 2026-10-27 |
| — | Orchestrator (decision Q7, added 2026-10-14) | Per-sequence plan, evidence providers (route heads, reference lookup, novelty, contamination), combined decision + stored trace |

## Reading this against the repo (re-verified 2026-10-27 at `32f38ef`, not just file presence)

- Phases 1–2 (backend/DB): confirmed. `services/api/app/main.py` wires MongoDB as the primary
  store, Redis as the job queue, `app/storage.py` for uploads (local or S3/MinIO, QNA-009), and
  Supabase for auth exchange plus a best-effort mirror — see `architecture.md`'s data-stores table.
- Phase 3 (Auth): confirmed — `app/auth` router; Google code-exchange, Supabase exchange, admin-key
  redeem, expedition session tokens (rejected as API bearer tokens, QNA-015); `APP_ENV` startup
  check on `JWT_SECRET` (QNA-019). Tests `test_auth*.py`, `test_jwt_secret_check.py`.
- Phase 5 (Parser): confirmed real — `packages/fastx_parser` Rust crate with a Python fallback,
  called from `job_runner._stage_parse` after `storage.local_copy_for_upload`.
- Phase 6 (Router): confirmed live and **learned** — `job_runner._stage_route` →
  `app/model_router` runs the registry's `router` entry (served `kmer_router_v2`) first; the
  heuristic runs only as a recorded fallback (`router_method`, `router_fallback_reason`)
  (QNA-010, QNA-021, QNA-023).
- Phase 7 (Model strategy): confirmed live with real weights on all six routes. The registry decides
  what is served (production > staging > experimental; `candidate` never served). A route with no
  runnable head returns a labelled stub (`inference_mode: "stub"`, `stub_reason`), never a random
  head labelled "model" (`9391181`). Heads tokenise at their training max_length (QNA-026).
- Orchestrator (Q7): confirmed — `job_runner._stage_orchestrate` → `app/orchestrator` plans routes,
  collects evidence from `app/evidence` (route heads, BLAST/vsearch reference lookup over reference
  v2, contamination, novelty), selects the route, combines, and stores `decision` +
  `decision_trace` (orchestrator-1.3.0). Tests `test_orchestrator_*.py`, `test_evidence_providers.py`.
- Phase 8 (Novelty/contamination): confirmed live inside the orchestrator; contamination gates
  novelty; centroid embedding isolation computed and recorded, weight 0; threshold 0.44 (QNA-038).
- Phase 9 (Review workflow): confirmed — `app/reviews` with `records.py` (review_evidence,
  curation_decisions, training_batch_items), batch create/freeze; `test_review_records.py`,
  `test_full_loop_integration.py` (opt-in).
- Phase 10 (Abyss Mode): confirmed — `app/abyss` (learned-router copy with a parity test), field
  log, AbyssSetup lifecycle and `/abyss/sync` (QNA-015). Offline quantized models and reference pack:
  cut to v1.1.
- Phase 11 (Reports): confirmed — `app/reports` (taxa section, context block, JSON/CSV/FAIR
  exports) and `app/custody` hash chain (QNA-029, QNA-032).
- Phase 12 (Frontend): every routed page is on real data or an honest empty state; partner pages on
  the partner API (QNA-035–037); MockTag deleted (QNA-039).
- Phase 13 (Testing/Security/CI): `.github/workflows/ci.yml` runs pytest+coverage for both services,
  frontend lint (non-blocking, `continue-on-error`) + build, the Playwright job, `bandit`, a tracked-`.env` guard and the Docker build
  check. Last local run on the merged tree (2026-10-27): worker 546, API 751 / 3 skipped,
  Playwright 80/80. Not verified: a green run on GitHub Actions (nothing pushed yet).
- Phase 14 (Training pipeline): run-verified this sprint — dataset rebuild, leakage check, reference
  DB, head and router retrains, register and promote through the API (QNA-016, QNA-021–023, QNA-031).
- Phase 0 (Repo weight reset): `legacy/` deleted, design/tool output folders gitignored, weights and
  reference data in `synthveda-data/` only.
- Phase 15 (Scaling): no evidence, not started.

Update `memory.md` — not this file — as phases actually complete or stall.
