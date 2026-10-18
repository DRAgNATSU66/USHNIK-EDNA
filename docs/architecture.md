# Synth Veda — Architecture

Living architecture doc. Canonical going forward for "how is this actually built" —
`docs/specs/SYNTHVEDA_TECH_STACK.md` was written pre-implementation and records the
*recommended* stack; this file records what's actually in the repo, and is updated as
the implementation moves. `docs/architecture/SYNTH_VEDA_PHASE_PLAN.md` is the fuller
execution roadmap this was built against.

## Repo layout

```text
services/
  api/            FastAPI backend — HTTP surface, auth, db, uploads, reviews, reports
    app/
      main.py       entry point
      auth/         auth (Supabase-backed, see app/db + app/auth)
      analysis/     analysis endpoints
      reviews/      expert/admin correction workflow
      reports/      report generation
      field_log/    Abyss Mode / offline field triage support
      abyss/        Abyss Mode backend pieces
      db/           persistence layer
      queue.py      job queueing
  worker/         processing/inference worker — the actual DNA pipeline
    app/
      dispatcher.py     routes jobs to the right pipeline stage
      job_runner.py     executes queued jobs
      model_router/     heuristic pre-model router (6 taxonomic routes)
      inference/         DNABERT-2 inference + classification heads
      novelty/            novelty/contamination scorer
      fastx_parser.py    FASTA/FASTQ parsing
    training/       fine-tuning pipeline (build_dataset, labeling, routing, finetune,
                     evaluate_checkpoint, taxonomy) — the DNA training pipeline
packages/         shared libraries used by api/worker
  edna_core/
  fastx_parser/
  model_router/
web_frontend/     React + Vite frontend
  src/
    App.jsx         app shell / routing
    api.js          backend API client
    pages/          route-level views (Upload/New Analysis, Researcher Mode, etc.)
    components/     shared UI components
    contexts/       React context providers
    lib/            frontend utilities
docs/             this documentation tree
```

## Data stores (verified from `services/api/app/config.py` + both `requirements.txt`)

Three separate stores, each with one job — don't blur these:

| Store | Used for | Client |
|---|---|---|
| **MongoDB** (`mongodb_db: "synthveda"`) | primary app data: uploads, `analysis_jobs`, results | `motor` (async) / `pymongo`, in both `services/api` and `services/worker` |
| **Supabase** | auth only (`app/auth`, `app/db/supabase_client.py`) | `supabase` Python client (API service only — worker has no Supabase dep) |
| **Redis** (`redis://localhost:6379/0`) | job queue between API and worker | `redis` client, `services/api/app/queue.py` + `services/worker/app/queue.py` |

## Pipeline (backend data flow) — verified against `job_runner.py` and `dispatcher.py`

```text
FASTA/FASTQ upload (web_frontend -> services/api)
  -> services/api/app/uploads writes the file through app/storage.py (local disk
     or an S3-compatible bucket -- MinIO in compose), writes a Mongo `uploads`
     doc carrying its storage_uri (local://<key> | s3://<bucket>/<key>) + sha256;
     the worker's _stage_parse reads it back through its copy of storage.py
  -> services/api enqueues a job (app/queue.py -> Redis)
  -> services/worker/app/dispatcher.py polls Redis (dequeue_job), caps concurrency
     with an asyncio.Semaphore (WORKER_CONCURRENCY), spawns a task per job that
     calls job_runner.run_job() -- dispatcher does NOT run pipeline logic itself,
     it only pulls jobs and manages concurrency/shutdown
  -> job_runner.run_job() loads the job + upload docs from Mongo, then runs each
     stage in sequence, writing job.state to Mongo after every stage:

       queued -> parsing -> qc -> routing -> inferencing
       -> novelty_scoring -> reporting -> completed | failed

     - parsing   (_stage_parse): packages/fastx_parser -- a real Rust crate
                 (`synthveda-parse` binary, Cargo.toml/src in packages/fastx_parser)
                 with a pure-Python fallback when the binary isn't available;
                 runs in a thread pool so it doesn't block the event loop
     - qc        (_stage_qc): drops sequences by n_ratio/length/invalid-chars;
                 the parser's own min_length filter already did a first pass
     - routing   (_stage_route): app/model_router -- heuristic router (marker-gene
                 pattern match + GC/CpG/length/habitat biophysical score), assigns
                 route + route_confidence + confidence_tier + fallback_routes,
                 no learned weights
     - inferencing (_stage_infer): app/inference -- picks the best available
                 model per route from a model registry; falls back to a stub
                 prediction (inference_mode: stub / low_quality) when torch isn't
                 installed or no trained weights exist for that route yet --
                 this fallback is real and observable in job output, not
                 hypothetical
     - novelty_scoring (_stage_novelty): app/novelty -- contamination is scored
                 first and gates novelty (a sequence flagged as contamination
                 cannot score high on novelty)
     - reporting (_stage_report): writes the final `analysis` doc to Mongo
  -> services/api/app/analysis + app/reports serve results to the frontend
  -> services/api/app/reviews lets an expert correct results
  -> corrections feed services/worker/training/ for monthly retraining
```

Full reasoning behind each stage (why DNABERT-2, why a heuristic pre-router instead of
a single end-to-end model, what the novelty formula's weights mean, what's a
placeholder vs. trained) lives in `docs/ml/THEORY_README.md` — read that before
changing anything in `model_router/`, `inference/`, or `novelty/`.

## Tech stack (actual, verified against requirements files / package.json / config)

| Layer | What's actually used |
|---|---|
| Backend API | Python, FastAPI 0.115, `services/api` — routers: auth, uploads, analysis, models, reviews, abyss, reports, field_log (all wired in `app/main.py`) |
| Worker/pipeline | Python, `services/worker`; DNABERT-2 (HF `zhihan1996/DNABERT-2-117M`) fine-tuned per route |
| Sequence parsing | Rust crate `packages/fastx_parser` (own binary), Python fallback — **not** pyfastx/Biopython as the old tech-stack doc recommended |
| Data store | MongoDB (`motor`/`pymongo`) — see table above |
| Auth | Supabase (`supabase` client), API service only |
| Job queue | Redis (`redis` client), both services |
| Frontend | React + Vite (`web_frontend`) |
| Maps | Leaflet + `react-leaflet` + `leaflet.heat` (heatmap for eDNA probability zones) — **not** Mapbox as the old tech-stack doc recommended |
| Routing (frontend) | `react-router-dom` v7 |
| Export | `dom-to-image-more` (report/chart export) |
| Security scanning | `bandit` (CI job, medium+ severity, see `.github/workflows/ci.yml`) |
| Deployment | Docker (Dockerfiles under `services/api`, `services/worker`, `web_frontend`), `deployment/`, `infra/` |

`docs/specs/SYNTHVEDA_TECH_STACK.md` is the original **pre-implementation**
recommendation (Tailwind, shadcn/ui, Recharts/Visx, Framer Motion, Mapbox, Zustand,
Celery+Redis, Auth0/Clerk, BLAST+/DIAMOND, VSEARCH/DADA2, pyfastx). Confirmed
divergences so far: Leaflet not Mapbox, a custom Rust parser not pyfastx/Biopython,
Redis-backed asyncio dispatch not Celery. Where this file and that one disagree, this
file (or the actual code) wins — update this table when another divergence is found
rather than trusting the old doc.

## Session-change log

See `flow.md` for what AI-assisted sessions have changed, mapped onto this structure.
