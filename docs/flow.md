# Synth Veda — Execution Flow & Session Change Log

Two jobs in this file: (1) map entry points and call order so a reader can trace how a
request actually moves through the system, (2) log what an AI-assisted session changed,
in plain language, scoped to that session. Append to the change log; don't rewrite it.

## Entry points

| Surface | Entry point | Notes |
|---|---|---|
| Backend API | `services/api/app/main.py` (`create_app()`) | FastAPI app; run via `uvicorn` (`make api-run`); registers 10 routers: auth, uploads, analysis, models, reviews, abyss, reports, field_log, environment, partner |
| Worker | `services/worker/app/dispatcher.py` (`_process_loop`) | long-running poll loop, not a per-request handler — see call order below |
| Frontend | `web_frontend/src/main.jsx` | Vite entry, mounts the React app and its 23 `<Route>` entries |
| Training / data | `services/worker/training/` (`build_dataset`, `check_leakage`, `build_reference_db`, `finetune`, `evaluate_checkpoint`, `train_router`, `novelty_centroids`, `eval_*`) | standalone, run manually; `make train-promote` registers + promotes through the API |
| Model promotion | `POST /models/register`, `POST /models/{id}/promote` (admin / company_owner) | rewrites `models/registry/*.json`; the worker picks it up within ~5 s, no restart |
| Full-loop test | `make test-loop` (`services/api/tests/test_full_loop_integration.py`) | opt-in (`SYNTHVEDA_LOOP_TEST=1`); needs the data root and the worker venv |
| E2E tests | `npm run test:e2e` in `web_frontend` (Playwright) | CI job `frontend-e2e` |

## Call order — analyze request (happy path)

Verified against `services/api/app/main.py`, `uploads/router.py`, `services/worker/app/dispatcher.py`,
`services/worker/app/job_runner.py` and `services/worker/app/orchestrator/engine.py` (2026-10-27,
`32f38ef`):

```text
web_frontend: user submits Upload/New Analysis form ("Auto · Orchestrator" is the only
processing option; it lists the served model per route from GET /models/status)
  -> web_frontend/src/lib/api.js posts to services/api
  -> app/uploads/router.py validates the optional metadata fields, writes the file
     through app/storage.py (STORAGE_BACKEND: local disk, or MinIO/S3 in compose),
     records storage_uri + sha256 + metadata in a MongoDB `uploads` doc, appends
     upload_created to the custody chain (best-effort) and, when lat/long +
     collected_at are given, schedules the environmental-context lookup as a
     background task (app/environment/service.run_lookup)
  -> POST /analysis/jobs: app/queue.py enqueues a job onto Redis
  -> services/worker/app/dispatcher.py: an always-on poll loop
     (dequeue_job() from Redis), NOT a per-request router -- caps concurrent
     jobs with asyncio.Semaphore(WORKER_CONCURRENCY), spawns one asyncio
     task per dequeued job calling job_runner.run_job()
  -> job_runner.run_job(): loads the job + upload docs from Mongo, then
     drives the state machine, persisting job.state to Mongo after each
     stage: queued -> parsing -> qc -> routing -> inferencing
     -> novelty_scoring -> reporting -> completed | failed
       - _stage_parse: storage.local_copy_for_upload (checksum verified), then
         packages/fastx_parser (Rust binary, Python fallback); no file -> job fails
       - _stage_qc: drops sequences by n_ratio / length / invalid chars
       - _stage_route: app/model_router -- learned k-mer router (registry entry
         "router", served kmer_router_v2) first, heuristic only as a recorded
         fallback (router_method / router_fallback_reason)
       - _stage_orchestrate: app/orchestrator.Orchestrator.run in the thread pool
         -- plan -> primary reference lookup (BLAST, reference v2) -> expand plan
         -> other lookups -> every planned route's head -> select_route ->
         contamination -> novelty -> combine; writes `decision` + `decision_trace`
         per sequence; job.state moves inferencing -> novelty_scoring through a
         callback
       - _stage_report: writes the `analysis_results` doc to Mongo and the auto
         reviews (_build_auto_reviews)
  -> app/analysis/router.py (GET /analysis/{id}, include_trace) and
     app/reports/router.py (report, summary, novelty, contamination, exports,
     custody) serve results; the report builder derives the taxa section and the
     context block at read time
  -> web_frontend polls GET /analysis/jobs/{id} (JobProgress), then AnalysisResults
     fetches the report and GET /analysis/{id}?include_trace=false; the decision
     trace is fetched once, on the first "Why this answer"
```

## Call order — review to promotion

```text
POST /reviews (any signed-in user; see architecture.md open issues)
  -> reviews/records.record_submission: result snapshot (decision + trace) as
     review_evidence; Supabase mirror best-effort
POST /reviews/{id}/decision (curator+) -> curation_decisions document
POST /reviews/batch/create -> accepted reviews join the batch of the sequence's
     final route (training_batch_items)
POST /reviews/batch/{id}/freeze -> items stamped frozen_at in Mongo
POST /models/register (artifact sha256 checked) -> registry entry, status candidate
POST /models/{id}/promote (dry_run first, then real) -> registry rewritten,
     model_eval_metrics + audit_logs written -> worker serves it within ~5 s
```

Full stage-by-stage reasoning: `docs/ml/THEORY_README.md` and `docs/qna.md`. Structural
layout this traces over: `architecture.md`.

## Session change log

Newest first. One entry per AI-assisted session with a summary of what actually
changed and where — for a reviewer who wasn't in the conversation.

### 2026-10-14 → 2026-10-27 (October v1 sprint)
Every change in this window has a contemporaneous entry in `docs/qna.md` (QNA-001 to
QNA-039), with commits, measured numbers and open issues; this is the index, not a copy.
- Real inference on all six routes via `data:` registry paths (QNA-001); dead frontend
  code and dead endpoints removed (QNA-002, QNA-003); `/models/status` from the registry
  (QNA-004).
- Upload metadata contract and per-result context block (QNA-005, QNA-008); one novelty
  threshold per service, read by the frontend (QNA-006, QNA-007).
- Object storage abstraction with MinIO in compose (QNA-009).
- Learned k-mer router replaces the heuristic as the first stage (QNA-010); strand-invariant
  router v2 (QNA-021).
- Data: supplementary NCBI/ENA sequences (QNA-011), reference DB v1 then v2 (QNA-012,
  QNA-016), `processed/` rebuilt with near-duplicate-aware splits (QNA-016).
- Six heads retrained (QNA-022); router v2 and four v2 heads promoted through the API
  (QNA-023); inference max_length aligned to training (QNA-026).
- Reference-lookup provider (QNA-020) and the deterministic orchestrator with stored
  decision traces (QNA-024, QNA-025, QNA-030); taxon assignment evaluated on held-out data
  (QNA-033); result taxon fields and report taxa section (QNA-032); Upload "Auto" and the
  decision-trace UI (QNA-034).
- Novelty centroid term computed but served at weight 0, threshold 0.45 → 0.44 (QNA-038).
- Review records (QNA-027), register/promote (QNA-014), full-loop integration test
  (QNA-031).
- FieldLog edits/attachments (QNA-013); environmental context service (QNA-018); partner
  API (QNA-028); FAIR ZIP + custody chain (QNA-029); Academia, Legislative and Industrial
  pages on real data (QNA-035, QNA-036, QNA-037); integrity sweep, MockTag deleted
  (QNA-039).
- Abyss offline router copy, offline credentials, AbyssSetup lifecycle (QNA-015);
  Playwright suite in CI (QNA-017); JWT secret startup check, nginx auth rate limits,
  `legacy/` removed (QNA-019).
- 2026-10-27 docs pass (t-1030-3): `architecture.md`, this file, `memory.md`, `phases.md`,
  the audit doc and the paper brought in line with the code at `32f38ef` and with the
  measured results in `docs/ml/results/`.

### 2026-09-03
Set up the documentation scaffold requested by the user (also saved as a standing
convention in Claude's cross-project memory, so this applies to future projects too):
created `docs/decisions.md`, `docs/flow.md` (this file), `docs/prd.md`,
`docs/architecture.md`, `docs/rules.md`, `docs/phases.md`, `docs/design.md`,
`docs/memory.md`. All seeded from the existing repo (README, package.json, `services/`
and `web_frontend/` structure, `docs/specs/`, `docs/architecture/SYNTH_VEDA_PHASE_PLAN.md`,
`docs/ml/THEORY_README.md`) rather than left as empty stubs. No application code changed
this session. Existing legacy docs (`docs/specs/`, `docs/architecture/`, `docs/ml/`) were
left untouched, not migrated — the new files point back to them for depth.

Follow-up same day: verified the scaffold's inferred claims against actual code
(`main.py`, `dispatcher.py`, `job_runner.py`, `config.py`, both `requirements.txt`
files, `.github/workflows/ci.yml`) instead of leaving them as guesses. Corrected:
the pipeline is 3 data stores (MongoDB for app data, Supabase for auth only, Redis
for the queue), not "Supabase" alone; the dispatcher polls/manages concurrency, it
doesn't route pipeline stages — `job_runner.py` owns the actual state machine; the
sequence parser is a real Rust crate (`packages/fastx_parser`) with a Python
fallback, not pyfastx/Biopython; inference has a live stub fallback
(`inference_mode: stub`) when no trained weights exist for a route. Also resolved
three previously-flagged unknowns: `package-lock.json`'s diff is npm normalizing
stale `"peer": true` flags (no real dependency change); `PSEUDO FILE/` is an
uncommitted design-reference mood board (images/videos, 81MB video included), never
tracked by git; `.playwright-mcp/` is Playwright MCP tool output (console/page logs
from an 2026-08-17 QA session) — neither is in `.gitignore` yet. See `architecture.md`,
`rules.md`, `phases.md`, `memory.md` for where each correction landed.
