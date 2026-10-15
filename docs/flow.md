# Synth Veda — Execution Flow & Session Change Log

Two jobs in this file: (1) map entry points and call order so a reader can trace how a
request actually moves through the system, (2) log what an AI-assisted session changed,
in plain language, scoped to that session. Append to the change log; don't rewrite it.

## Entry points

| Surface | Entry point | Notes |
|---|---|---|
| Backend API | `services/api/app/main.py` (`create_app()`) | FastAPI app; run via `uvicorn` (see root `README.md`); registers 8 routers: auth, uploads, analysis, models, reviews, abyss, reports, field_log |
| Worker | `services/worker/app/dispatcher.py` (`_process_loop`) | long-running poll loop, not a per-request handler — see call order below |
| Frontend | `web_frontend/src/main.jsx` -> `App.jsx` | Vite entry, mounts React app + router |
| Training pipeline | `services/worker/training/finetune.py` | standalone, not triggered by the live API — run manually/via monthly job |
| Inference smoke test | `src/species_identification/nt_inference.py` (per root `README.md`) | legacy/local validation path, predates the `services/` split — verify it still matches current code before relying on it |

## Call order — analyze request (happy path)

Verified against `services/api/app/main.py`, `services/worker/app/dispatcher.py`, and
`services/worker/app/job_runner.py` (2026-09-03):

```text
web_frontend: user submits Upload/New Analysis form
  -> web_frontend/src/api.js posts to services/api
  -> app/uploads/router.py saves the file, writes a MongoDB `uploads` doc,
     app/queue.py enqueues a job onto Redis
  -> services/worker/app/dispatcher.py: an always-on poll loop
     (dequeue_job() from Redis), NOT a per-request router -- caps concurrent
     jobs with asyncio.Semaphore(WORKER_CONCURRENCY), spawns one asyncio
     task per dequeued job calling job_runner.run_job()
  -> job_runner.run_job(): loads the job + upload docs from Mongo, then
     drives the state machine, persisting job.state to Mongo after each
     stage: queued -> parsing -> qc -> routing -> inferencing
     -> novelty_scoring -> reporting -> completed | failed
       - _stage_parse: packages/fastx_parser (Rust binary, Python fallback)
       - _stage_qc: drops sequences by n_ratio / length / invalid chars
       - _stage_route: app/model_router (heuristic, no learned weights)
       - _stage_infer: app/inference -- real model if trained weights exist
         for that route, else a stub prediction (inference_mode: stub) --
         this fallback path is live code, not a TODO
       - _stage_novelty: app/novelty -- contamination scored first, gates
         the novelty score
       - _stage_report: writes the final `analysis` doc to Mongo
  -> app/main.py's analysis_router / reports_router serve results
  -> web_frontend polls/fetches result via api.js, renders in pages/
```

Full stage-by-stage reasoning: `docs/ml/THEORY_README.md`. Structural layout this
traces over: `architecture.md`.

## Session change log

Newest first. One entry per AI-assisted session with a summary of what actually
changed and where — for a reviewer who wasn't in the conversation.

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
