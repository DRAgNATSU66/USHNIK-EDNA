# Synth Veda — Architecture

Living architecture doc. Canonical going forward for "how is this actually built" —
`docs/specs/SYNTHVEDA_TECH_STACK.md` was written pre-implementation and records the
*recommended* stack; this file records what's actually in the repo, and is updated as
the implementation moves. `docs/architecture/SYNTH_VEDA_PHASE_PLAN.md` is the fuller
execution roadmap this was built against. `docs/qna.md` (QNA-001…) is the contemporaneous
record of every major change and what was measured; where this file cites a number, the
QNA entry is the source.

Last re-verified against the code: 2026-10-27 (`LATEST_USHNIK` at `32f38ef`, Day 17 docs pass).

## Repo layout

```text
services/
  api/            FastAPI backend — HTTP surface, auth, uploads, reviews, reports, partner API
    app/
      main.py         entry point (create_app); registers 10 routers, GET /health
      config.py       settings; APP_ENV startup check on JWT_SECRET (QNA-019);
                      DEFAULT_NOVELTY_THRESHOLD = 0.44 (QNA-038)
      storage.py      upload/attachment storage: local disk or S3-compatible (MinIO);
                      byte-identical copy in services/worker/app/storage.py, pinned by a test
      auth/           Google code-exchange, Supabase exchange, admin-key redeem, JWT,
                      expedition (offline) session tokens — rejected as API bearer tokens
      uploads/        POST /uploads (metadata contract, storage, sha256), per-result
                      `context` block (provided/missing fields) in context.py
      analysis/       POST /analysis/jobs, GET /analysis/{id}[?include_trace=]
      models/         /models/status, /registry, /register, /{id}/promote, /promotions;
                      Pydantic models for uploads, analyses (decision + trace), reviews
      reviews/        review workflow + B9 records (review_evidence, curation_decisions,
                      training_batch_items) and monthly batch create/freeze
      reports/        report builder (taxa section, report_version 1.1), JSON/CSV export,
                      FAIR ZIP export (fair.py), GET /reports/{id}/custody
      custody/        hash-chained chain of custody per sample (chain.py, events.py)
      environment/    environmental context service: Copernicus Marine / NOAA ERDDAP /
                      Open-Meteo point lookups, cached per upload
      partner/        partner API: summary, audits, co-occurrence, rhythms, hotspots,
                      alerts, incidents, tasks
      field_log/      field-log entries (note/comment/task), PATCH with append-only edit
                      history, attachments on the storage layer
      abyss/          Abyss Mode: expeditions, licence, offline pack manifest, field triage
                      (analysis.py) with an inference-only copy of the learned router
                      (learned_router.py), /abyss/sync
      db/             Mongo client + indexes, best-effort Supabase client
      queue.py        Redis job enqueue
    scripts/gen_e2e_fixtures.py   records Playwright fixtures from the real FastAPI app
  worker/         processing/inference worker — the actual DNA pipeline
    app/
      dispatcher.py      polls Redis, caps concurrency, calls job_runner.run_job()
      job_runner.py      the job state machine (parse → qc → route → orchestrate → report)
      fastx_parser.py    wrapper over packages/fastx_parser (Rust) with a Python fallback
      storage.py         same module as the API's (reads local:// or s3:// uploads)
      model_router/      learned k-mer router (learned.py, kmer.py) as the first stage;
                         heuristic marker + biophysical router (router.py) as the fallback
      orchestrator/      deterministic per-sequence planner, combiner, engine, lineage
      evidence/          evidence providers: route_head, reference_lookup (BLAST/vsearch),
                         contamination, novelty
      inference/         DNABERT-2 heads, registry (data: paths, promotion reload),
                         max_length resolution (QNA-026)
      novelty/           scorer, signals, per-head known-class centroids (centroids.py)
    training/       data + model pipeline: build_dataset, near_dup, check_leakage,
                    fetch_supplementary, build_reference_db, finetune, evaluate_checkpoint,
                    train_router, novelty_centroids, and eval_* scripts that produce
                    docs/ml/results/*
packages/
  fastx_parser/   Rust crate (`synthveda-parse` binary) — the only shared package today
models/registry/  one JSON per registered model (routes + the "router" entry); the
                  source of truth for what the worker serves
supabase/migrations/   Postgres schema for auth + the best-effort mirror tables
web_frontend/     React + Vite frontend
  src/
    main.jsx        router (23 <Route> entries) and app shell
    lib/api.js      the only backend API client (a contract test checks every path)
    pages/          Upload, JobProgress, AnalysisResults, researcher/*, partner/*,
                    ReviewQueue, ModelStatus, Admin, AbyssSetup, auth pages
    components/     shared UI (ConfidenceChip, DetectionWindowBadge, DisclaimerBanner,
                    ProvenanceTag, NegativeControlFlag, results/DecisionTrace, ...)
    contexts/       React context providers
    lib/            frontend utilities (decision readers, score chips, Abyss device store)
  e2e/            Playwright suite (Chromium, recorded fixtures), run in CI job frontend-e2e
infra/            docker compose (+ MinIO, scale profile with nginx LB), Cloud Run YAML,
                  terraform
docs/             this documentation tree
```

The data root `synthveda-data/` (gitignored, outside the repo's tracked files) holds
`checkpoints/` (route heads, router `.npz`, novelty centroid artefacts), `processed/`
(train/dev/test splits), `reference/` (versioned per-route reference DBs, `CURRENT` → `v2`),
`raw/` and `logs/`. Registry entries point into it with `data:` URIs resolved against
`$SYNTHVEDA_DATA_ROOT` (QNA-001).

## Data stores (verified from both `config.py` files, `db/`, `storage.py`, compose)

| Store | Used for | Client |
|---|---|---|
| **MongoDB** (`mongodb_db: "synthveda"`) | primary app data: `uploads`, `analysis_jobs`, `analysis_results` (one doc per analysis, results with `decision` + `decision_trace`), `reviews`, `review_evidence`, `curation_decisions`, `training_batch_items`, `custody_events`, `environment_contexts` / `environment_cache`, `field_log_entries` / `field_log_attachments`, partner `audits`, `abyss_expeditions` / `abyss_analyses` / `abyss_expedition_logs`, `audit_logs`, `model_eval_metrics` | `motor` (async) / `pymongo`, in both services |
| **Supabase** | auth exchange (`/auth/supabase/exchange`) and a **best-effort mirror** of reviews, review records, training batches, `model_versions` / `model_eval_metrics`. Mongo writes first; the mirror outcome is returned (`written` / `not_configured` / `failed`) and never fails a request (QNA-014, QNA-027) | `supabase` Python client, API only |
| **Redis** (`redis://localhost:6379/0`) | job queue between API and worker | `redis` client, both `queue.py` files |
| **Object storage** | uploaded files and field-log attachments. `STORAGE_BACKEND=local` (default; files under `UPLOAD_STORAGE_DIR`) or `s3` (any S3-compatible endpoint; MinIO bucket `synthveda-uploads` in compose). Upload docs carry `storage_uri` (`local://<key>` / `s3://<bucket>/<key>`) + `checksum_sha256`; the worker re-verifies the bytes before parsing (QNA-009) | `boto3` in `app/storage.py` |
| **Registry + data root** (files) | `models/registry/*.json` decides what is served; `synthveda-data/` holds the weights and reference DBs. Promotion rewrites registry files; the worker re-reads them within `SYNTHVEDA_REGISTRY_RECHECK_S` (default 5 s) (QNA-014) | plain files |

## Pipeline (backend data flow) — verified against `job_runner.py`, `orchestrator/engine.py`, `dispatcher.py`

```text
FASTA/FASTQ upload (web_frontend -> services/api)
  -> POST /uploads writes the file through app/storage.py (local disk or S3/MinIO),
     records storage_uri + sha256 and the optional metadata fields (collected_at,
     lat/long, depth, methodology, negative_control_included, collector, DO, pH, ...)
     in a Mongo `uploads` doc; appends upload_created to the custody chain
     (best-effort); schedules the environmental-context lookup as a background
     task when lat/long + collected_at are present
  -> POST /analysis/jobs enqueues a job (app/queue.py -> Redis)
  -> services/worker/app/dispatcher.py polls Redis (dequeue_job), caps concurrency
     with an asyncio.Semaphore (WORKER_CONCURRENCY), spawns a task per job that
     calls job_runner.run_job() -- dispatcher does NOT run pipeline logic itself
  -> job_runner.run_job() loads the job + upload docs from Mongo, then runs each
     stage in sequence, writing job.state to Mongo after every stage:

       queued -> parsing -> qc -> routing -> inferencing
       -> novelty_scoring -> reporting -> completed | failed

     - parsing   (_stage_parse): reads the upload through storage.py
                 (local_copy_for_upload; checksum verified), then
                 packages/fastx_parser (Rust `synthveda-parse` binary, pure-Python
                 fallback). An upload with no file, a missing object or a checksum
                 mismatch fails the job -- the old fake ATCGATCGATCG stub is gone (B6)
     - qc        (_stage_qc): drops sequences by n_ratio/length/invalid chars
     - routing   (_stage_route): app/model_router. The LEARNED k-mer router runs
                 first: the registry entry with route "router" (served:
                 kmer_router_v2, canonical 9-mer LinearSVC, strand-invariant,
                 temperature-calibrated), sha256-verified .npz, numpy only. It
                 returns calibrated route_probabilities for all six routes. The
                 heuristic marker + biophysical router is the FALLBACK only
                 (router_method "heuristic_fallback" + router_fallback_reason, and a
                 WARNING line); SYNTHVEDA_ROUTER=heuristic is the kill switch
     - inferencing + novelty_scoring (_stage_orchestrate): app/orchestrator, run
                 in the thread pool. Per sequence:
                   1. plan     top route alone if the router is confident; up to 3
                               routes when low_confidence (< 0.70), narrow_margin
                               (< 0.6) or weak_route (human / misc) fires
                   2. reference primary route's reference lookup -- one batched
                               BLAST (default) or vsearch call per route against
                               reference v2, under a host-wide search lock;
                               species/genus/family at 97/95/90 % identity with
                               >= 80 % coverage over >= 50 bp, LCA over hits within
                               0.5 points; GRCh38 screen on the human route
                   3. expand   reference_miss / reference_lineage_route add routes
                   4. reference lookups for the other planned routes
                   5. heads    every planned route's DNABERT-2 head (served: v2 for
                               fish/animal/human/misc, v1 for plant/bacteria),
                               tokenised at the head's training max_length (256)
                   6. route    select_route(): only reference identity can move the
                               route; heads never pick it
                   7. contamination, then novelty, on the final route. Novelty
                               weights 0.35/0.25/0.07 (class/low confidence/entropy);
                               the centroid embedding-isolation and reference
                               low-identity terms are computed and recorded but
                               served at weight 0; threshold 0.44 (QNA-038)
                   8. combine  class rules (qc gate, GRCh38 contamination,
                               contamination gates novelty, novelty suppressed /
                               downgraded by a >= 97 % reference hit, head class,
                               ...), plant species capped at genus
                 Output per sequence: `decision` {final_route, result_class,
                 predicted_taxon, taxon_rank, percent_identity, reference_db(_version),
                 confidence, rule} and `decision_trace` {orchestrator_version
                 (orchestrator-1.3.0), plan, evidence, combine}; legacy fields
                 (route, result_class, novelty_score, contamination_*) are filled
                 from the decision
     - reporting (_stage_report): writes ONE `analysis_results` doc with all
                 results, then auto reviews (novelty >= threshold, or contamination
                 not expected on its route -- human_dna on the human route is
                 flagged but not queued, QNA-030)
  -> services/api serves results: GET /analysis/{id} (decision + optional trace,
     flat taxon fields derived on read), /reports/* (taxa section, context block,
     JSON/CSV/FAIR exports, custody), /partner/* aggregates
  -> services/api/app/reviews lets an expert correct results; every review stores
     a result snapshot (decision + trace) as review_evidence
  -> accepted reviews join the monthly training batch of the sequence's final route;
     the batch is frozen in Mongo; a retrained model is registered and promoted
     through POST /models/register and /models/{id}/promote (or make train-promote)
```

Full reasoning behind the ML stages (why DNABERT-2, why a router before the heads, the
leakage history) lives in `docs/ml/THEORY_README.md`; the orchestration rules, thresholds
and their measured effect are in QNA-020, QNA-024/025, QNA-030 and QNA-033; the novelty
calibration in QNA-038 and `docs/ml/results/novelty_centroid_2026-10-27.md`.

## Tech stack (actual, verified against requirements files / package.json / config)

| Layer | What's actually used |
|---|---|
| Backend API | Python, FastAPI 0.115, `services/api` — routers: auth, uploads, analysis, models, reviews, abyss, reports, field_log, environment, partner (all wired in `app/main.py`) |
| Worker/pipeline | Python, `services/worker`; DNABERT-2 (HF `zhihan1996/DNABERT-2-117M`) fine-tuned per route; numpy-only learned k-mer router; deterministic orchestrator (no LLM) |
| Reference lookup | NCBI BLAST+ (default) and vsearch over versioned per-route reference DBs (`synthveda-data/reference/v2`), built from MIDORI2, SILVA, UNITE, NCBI BLAST DBs, UniVec and supplementary NCBI/ENA records; GRCh38 BLAST index on the human route. BOLD is supported by the builders but `raw/bold/` is empty, so it is not in v2 |
| Sequence parsing | Rust crate `packages/fastx_parser` (own binary), Python fallback — **not** pyfastx/Biopython as the old tech-stack doc recommended |
| Data store | MongoDB (`motor`/`pymongo`) — see table above |
| Object storage | local disk or S3-compatible via `boto3`; MinIO in compose |
| Auth | API-issued JWTs after Google code-exchange / Supabase exchange / admin-key redeem; `APP_ENV` outside dev refuses the default or a < 32-byte `JWT_SECRET` |
| Job queue | Redis (`redis` client), both services |
| Environmental context | Copernicus Marine Zarr point reads (`blosc`), NOAA ERDDAP (OISST), Open-Meteo (marine + ERA5 wind) |
| Frontend | React 18 + Vite (`web_frontend`), `react-router-dom` v6 |
| Maps | Leaflet + `react-leaflet` (Legislative sampling grid) — **not** Mapbox as the old tech-stack doc recommended |
| Frontend tests | Playwright (`@playwright/test` 1.64.1), Chromium, fixtures recorded from the real API; no unit-test runner |
| Security scanning | `bandit` (CI job, medium+ severity, see `.github/workflows/ci.yml`) |
| Deployment | Docker (Dockerfiles under `services/api`, `services/worker`, `web_frontend`), `infra/docker` compose (Mongo, Redis, MinIO, API, worker; scale profile adds an nginx LB with `limit_req` on auth endpoints), `infra/deployment` Cloud Run YAML, `infra/terraform` |

`docs/specs/SYNTHVEDA_TECH_STACK.md` is the original **pre-implementation**
recommendation (Tailwind, shadcn/ui, Recharts/Visx, Framer Motion, Mapbox, Zustand,
Celery+Redis, Auth0/Clerk, BLAST+/DIAMOND, VSEARCH/DADA2, pyfastx). Confirmed
divergences so far: Leaflet not Mapbox, a custom Rust parser not pyfastx/Biopython,
Redis-backed asyncio dispatch not Celery, no DIAMOND or DADA2. BLAST+ and VSEARCH are now
actually used (reference lookup, QNA-012/020). Where this file and that one disagree, this
file (or the actual code) wins — update this table when another divergence is found
rather than trusting the old doc.

Some npm packages are declared but have no importer in `src/` (`three`, `@react-three/*`,
`chart.js`, `react-chartjs-2`, `axios`, `recharts`, `react-icons`, `lucide-react`;
QNA-002 Q6). Removing them is an `npm uninstall` that has not been done.

## Known open issues (as of 2026-10-27; each is recorded, none is hidden in the UI)

- **Supabase mirror does not reach a database.** The Supabase hostname in
  `services/api/.env` does not resolve, so every mirror write reports `failed`
  (QNA-023 Q4), and migrations `20261018000001_model_promotion.sql` and
  `20261019000001_review_records.sql` are unapplied (QNA-014, QNA-027). Mongo and the
  registry files are authoritative; the mirror is best-effort by design. Owner action:
  check the project URL.
- **No proxy rate limit in front of Cloud Run.** The nginx `limit_req` rules exist only in
  the compose scale profile (QNA-019). `infra/terraform/main.tf` defines a Cloud Armor
  policy, but nothing in the repo attaches it to a load balancer, and the Cloud Run
  services are not behind one.
- **`POST /reviews` accepts any authenticated user for any analysis.** The route checks
  authentication only; since `e83274d` such a review writes nothing to the owner's custody
  chain, but the review itself is stored (QNA-029 Q5).
- **BOLD data not downloaded.** `raw/bold/` is empty; the processed splits and reference v2
  were built without it (QNA-016). Owner action: BOLD login + data terms.
- **Analysis document size.** All results of one analysis live in one `analysis_results`
  document. Measured at 17.5 KB per sequence with the decision trace and embeddings, one
  document reaches MongoDB's 16 MB limit at about 950 sequences (QNA-024 Q4); there is no
  guard or split yet. `include_trace=false` only shrinks responses, not the stored doc.
- Novelty centroid term at weight 0 (owner decision open, QNA-038); plant_v2 / bacteria_v2
  candidates have no centroid artefact, and nothing in the promote flow builds one.
- Abyss offline pack: quantized route models and the offline reference pack are cut to
  v1.1 (`offline_pack.py` reports `not_yet_trained` / `not_yet_available`).

## Session-change log

See `flow.md` for what AI-assisted sessions have changed, mapped onto this structure.
