# Synth Veda — Real-Data Roadmap (mock removal → finished tool)

Written 2026-10-14. Supersedes `ROADMAP_TO_POLISHED_TOOL.md` (2026-09-03) as the working plan.
`AUDIT_MOCKS_STUBS_TODOS.md` is still the long-form evidence. Every item from it was re-checked
against the code on 2026-10-14: all are still present at the same lines, because no source file
has changed since 2026-08-27. Items marked **[NEW]** were found in this pass.

Part A is the full list of mock data and frontend↔backend differences. Part B is the day-by-day
plan to remove every one of them. Each task in Part B cites the Part A IDs it closes.

---

## The flexibility rule (read this first)

**Days are an order of work, not a calendar.** A day's work does not have to happen on that day.

- Finish early? Pull the next day's work forward, or any later day whose **Depends on** items are
  done. Running two days in parallel (one backend, one frontend) is encouraged.
- Fall behind? Let the dates slide. Do not cut a day's **Done when** check to stay on schedule.
- Only the **Depends on** column limits the order. If a day's dependencies are met, it can start,
  whatever its number.
- Tick the checkboxes in this file as tasks land, so progress can be read without asking anyone.

**Hard deadline: 2026-10-31, 23:59 IST.** Re-planned 2026-10-14 from the original 35-working-day
sequence into 18 calendar days (Oct 14–31, weekends included, two tracks a day). The deadline is
fixed; the dates inside it are not. **Cut line:** on Oct 25, if more than one day of work is
outstanding, the 4 stretch tasks (loader LRU, quantized models, reference pack, offline E2E) move
to v1.1. Abyss heuristic triage already works offline without them.

Live tracker (countdown, lock-in timer, calendar, shared task ticks):
https://claude.ai/artifact/UXQ4kYbjYfn1rtP84Q7HrK — tick tasks there; it is the source of truth for
progress. This file is the source of truth for scope.

## Working rules for the whole roadmap

1. **No new mock data.** No hardcoded numbers, sample rows or fake-success `setTimeout`s. If a
   panel has no real source yet, it shows an honest empty state ("No data source connected"),
   not a plausible-looking number.
2. **Removing a mock means replacing it or deleting it.** Never just remove the `MockTag` and
   leave the fake value in place.
3. **Real inference results are labelled as such.** Every result carries `inference_mode` and
   `model_version_used`, and the UI keeps showing provenance (see `rules.md`).
4. Changes that hit a `qna.md` trigger (more than 3 files, model-registry/routing, schema,
   anything claimed in the paper or demo) get a transcript entry when they land. This never
   blocks the work.

---

# Part A — Inventory: mock data and frontend↔backend differences

## A1. Frontend calls that do not match the backend (break or silently lose data)

| ID | Difference | Frontend | Backend | Effect |
|----|-----------|----------|---------|--------|
| F1 | Review queue calls `GET /reviews` | `lib/api.js:156-157`, `ReviewQueue.jsx` | only `GET /reviews/queue` (`reviews/router.py:121`) | **Review Queue page 404s on load** |
| F2 | Models page calls `GET /models` | `lib/api.js:198`, `ModelStatus.jsx` | only `GET /models/status`, `GET /models/registry` (`models/router.py:28,45`) | **Model Status page 404s on load** |
| F3 **[NEW]** | Abyss sync calls `POST /abyss/expeditions/{id}/sync` | `lib/api.js:224-227` | `POST /abyss/sync` with `expedition_id` in the body (`abyss/router.py:336`) | Would 404. Not called yet (no sync button), so it fails as soon as it is wired |
| F4 | Upload size limit | `Upload.jsx:29` → 500 MB | `config.py:50` → 100 MB | A 100–500 MB file uploads in full, then gets a 413 |
| F5 **[NEW]** | Collection **date/time** collected in the upload form | `Upload.jsx:38-40` (sent nowhere, `:195-198`) | no date/time field on `POST /uploads` (`uploads/router.py:26-40`) | What the user types is silently discarded |
| F6 **[NEW]** | `negative_control_included` read on results | `AnalysisResults.jsx:312` | no field captures it anywhere | The negative-control flag is always "unknown" |
| F7 | Methodology, negative control, collector, date/time shown in FieldLog | `FieldLog.jsx:264,270-272` (hardcoded "Metabarcoding", "Included", "M. Fernandes", "12 Aug 2026") | no such fields | Fake metadata shown next to real metadata. Same root cause as F5/F6 |
| F8 | "Processing Model" selector | `Upload.jsx:54-68` | `POST /analysis/jobs` only takes `mode` (`lib/api.js:112-113`) | Choosing a model does nothing, and nothing tells the user |
| F9 | Species name (`predicted_taxon`) | `SpeciesCorrection.jsx:186,508`, Academia "TAXA DETECTED" (`:553`) | always `null` (`predictor.py:204`) | Every row says "No taxonomic assignment yet". Taxon richness is meaningless |

## A2. Backend endpoints with no frontend caller

| ID | Endpoint | Note |
|----|----------|------|
| U1 | `GET /analysis/{id}` (`getAnalysis`) | Defined in `api.js`, used by no page |
| U2 | `GET /reports/{id}/summary`, `/novelty`, `/contamination` | Helpers exist. Pages fetch the whole report and filter it in the browser |
| U3 | `GET /reviews/{id}` (`getReview`), `GET /abyss/expeditions/{id}` (`getExpedition`) | Helpers unused |
| U4 | `POST /auth/expedition/session`, `POST /auth/expedition/verify` (`auth/router.py:354,421`) | Offline-expedition auth is built. `AbyssSetup.jsx` never calls it |
| U5 | `POST /auth/google/exchange` (`auth/router.py:152`) | Superseded by `/google/code-exchange` |
| U6 | `GET /analysis/{id}/report` (`analysis/router.py:104`) | Duplicates `GET /reports/{id}` |
| U7 | `GET /models/registry` | Real data, but no page reads it (see F2) |

## A3. Frontend mock / static data in routed pages

| ID | Page | What is fake |
|----|------|--------------|
| M1 | `partner/Industrial.jsx` | **Zero API imports.** 11 `MockTag` panels: incidents, impact score, pending audits, risk radar (`RADAR_VALS`), bio-impact metrics, audit trail, remediation plan, document hub, notes/tasks, biofouling threshold, remediation ROI. `scheduleAudit()` fakes success with `setTimeout` (`:308-311`) |
| M2 | `partner/Legislative.jsx` | **Zero API imports.** 6 `MockTag` panels: hotspot map, active alerts, indicator-species trend, habitat taxa decline, economic/compliance exposure, chain of custody. `runFeasibility()` fakes an async run (`:444-447`). Export buttons are honestly disabled |
| M3 | `partner/Academia.jsx` | API-backed, but 13 `MockTag` panels: dissolved O₂, toxicity index, temp-at-depth, pH, salinity (when not recorded), wind/current, multi-omics overlay, sonic activity, activity rhythms, co-occurrence network, FAIR ZIP export |
| M4 | `researcher/FieldLog.jsx` | `MOCK_NOTE` edit history, `MOCK_FILES` attachments (upload → `alert("File storage isn't wired up yet")`), 4 fake metadata fields (F7) |
| M5 | `ResearcherMode.jsx:16` | `PlaceholderScreen` fallback for any unknown section |

## A4. Dead frontend code (unreachable, but looks live)

| ID | File(s) | Why it is dangerous |
|----|---------|--------------------|
| D1 | `src/App.jsx` (1,388 lines), `src/App.css` | Posts to non-existent `/analyze`. "Demo mode" invents species. On failure it shows `Fallback_species_A/B` as real results |
| D2 **[NEW]** | `src/api.js` | A second axios client, also targeting `/analyze`. Easy to confuse with `src/lib/api.js` |
| D3 | `pages/stakeholders/*` (5 files, ~3,700 lines), `StakeholderDashboardPage.jsx` | Unrouted and fully mocked (`sampleMatches`, `sampleCSVRows`, fake `alert` buttons) |
| D4 **[NEW]** | `pages/Landing.jsx` | Not routed (`/` → Login). It is the only caller of `healthCheck` |
| D5 **[NEW]** | `components/DnaHelixViz.jsx`, `components/OrbitalVisualization.jsx` | Nothing imports them |
| D6 | `components/shared/ConfidenceChip.jsx`, `DetectionWindowBadge.jsx`, `DisclaimerBanner.jsx` **[NEW: DisclaimerBanner]** | Finished spec components with zero importers, so the scientific-integrity rules they encode are applied nowhere |

## A5. Backend stubs, hardcoded responses and unbuilt pieces

| ID | Where | What |
|----|-------|------|
| B1 | `models/router.py:28-42` | `GET /models/status` returns a hardcoded "unavailable" dict for all 6 routes, with a stale "after Phase 7" note |
| B2 **[status changed]** | `models/registry/*.json` | `base_model` and `artifact_uri` point to `E:\synthveda-data\...`. `loader._resolve_local` cannot find them, so every route falls back to **stub inference**. **However, the checkpoints now exist on this machine** at `synthveda-data/checkpoints/<route>/{backbone/, head.pt}` for all 6 routes. This is a path/config fix, not a training job |
| B3 **[NEW]** | local environment | `torch` is not installed (`requirements-ml.txt` is optional), so the worker runs in stub mode even with valid paths. An RTX 3070 (8 GB) is available |
| B4 **[NEW nuance]** | `predictor.py:204`, training data | `predicted_taxon=None` even on the real-model path. The trained heads are 3-class *result-class* classifiers (`known_species / possible_novelty / low_quality_unusable`), and `processed/*/train.csv` has only `sequence,label`. **Species names need a separate reference-lookup layer.** The model cannot provide them |
| B5 | `novelty/signals.py:184-189` | Embedding-isolation signal is a proxy: L2 norm vs hardcoded `typical_norm = 14.0` |
| B6 | `job_runner.py:88-89` | A job with no file path silently analyses a fake `seq_stub_001` / `ATCGATCGATCG` instead of failing |
| B7 | `uploads/router.py:81-86`, `config.py:32-33` | Uploads go to local disk. The object-storage config is unused |
| B8 | `db/supabase_client.py:400,406` | `register_model_version` / `promote_model` are never called. The retrain loop stops at "batch frozen" |
| B9 | migration `20260526000001` | Tables `review_evidence`, `curation_decisions`, `training_batch_items`, `model_eval_metrics` are never read or written |
| B10 | `field_log/router.py` | Only `POST`/`GET`. No `PATCH` (edits), no history, no attachments |
| B11 | `abyss/offline_pack.py:96-149` | `route_models_quantized: not_yet_trained`, `reference_pack_v1: not_yet_available` |
| B12 | `abyss/analysis.py:107-109`, `:243-245` | Dead import, plus a silent fallback to `_simple_gc_route` with the exception never logged |
| B13 | `models/router.py:51-54` | `GET /models/registry` drops malformed files with a bare `except: pass` |
| B14 | 10 literal sites | Novelty cutoff `0.45` hardcoded: `job_runner.py:252,282,338,375`, `reports/router.py:81,157`, `abyss/analysis.py:57,363`, `curation.py:323,359`. Only `reports/builder.py:39` names it, and nothing imports that name |
| B15 **[NEW]** | `models/registry/*.json` `notes` | Say "weights pending Phase 14" although metrics exist. They also contain mojibake (`â€”`). All entries are `experimental`, `promoted_by: null` |
| B16 | — | **No backend data source exists for the partner panels**: no incidents, audits, alerts, hotspots, environmental time series, documents or remediation endpoints |
| B17 | `inference/loader.py:67-70` | No LRU eviction (one model per route) |
| B18 | `config.py:13,27`, `infra/docker/nginx-lb.conf` | Dead `debug` flag; `jwt_secret` default with no startup check; no rate limit in the compose LB. *Deferred by owner: internal project* |

## A7. Found while executing (2026-10-14)

| ID | Where | What |
|----|-------|------|
| B19 **[NEW]** | `model_router/router.py` | **The heuristic router picks the correct route for 24.1% of held-out test sequences** (433/1,800; fish 0.3%, plant 0.0%, animal 1.7%, human 11.0%, misc 54.0%, bacteria 77.3%). The per-route head accuracies only hold when routing is right, so end-to-end results are mostly wrong today. A 10-second, untuned 6-mer logistic classifier reached 82.4% on the same test set. |
| B20 **[NEW]** | `scripts/seed_dev.py` | Seeds Mongo with mock analysis results. Must not be used on any database that feeds a demo or a report. |
| B21 **[NEW]** | `synthveda-data/raw/` | The ~44 GB raw reference set was lost in the Ubuntu migration; re-fetch in progress (`scripts/fetch_reference_data.sh`), BOLD/UNITE/MIDORI2 manual. |
| B22 **[NEW]** | `models/registry/dnabert2_bacteria_v1.json` | Registry described an older bacteria run (acc 0.8006, train 12,320) than the `head.pt` on disk (acc 0.842, train 37,832); checksum did not match. Corrected 2026-10-14. |
| B23 **[NEW 10-18]** | `model_router/learned.py`, router v1 | Learned router v1 (k=8, forward strand) scores 0.1655 on reverse-complemented test reads while reporting high confidence. Paired-end R2 / reverse-orientation uploads are misrouted. Fix: strand invariance is a stated requirement of the router retrain with t-1021-1 (QNA-010) |
| B24 **[NEW 10-18]** | `infra/docker/docker-compose.yml` | The compose worker does not mount `synthveda-data`, so in Docker every result falls back to the heuristic router (`artifact_missing`) and the heads are unavailable. Visible, not silent. **Fixed 10-18:** read-only `/data` mount + `SYNTHVEDA_DATA_ROOT` |
| B25 **[NEW 10-18]** | `services/api/app/abyss/analysis.py` | The Abyss path imports `app.model_router`, which collides with the API's own `app` package (`ModuleNotFoundError`), so Abyss always uses GC-only routing (`router_error_fallback`). Predates B19; B12 made it visible |
| B26 **[NEW 10-18]** | `models/registry/kmer_router_v1.json` | The registry now holds a non-taxonomic `route: "router"` entry. `/models/status` skips it, but `/models/registry` and the Model Status page list it. **Kept as intended 10-18:** it is a registered model and its card shows its real metrics, reverse-complement accuracy included |

## A6. Open product decisions — resolve on Day 1 (recommended defaults given)

| ID | Decision | Recommended default | Blocks |
|----|----------|---------------------|--------|
| Q1 | Reference DB for species names | Reuse what `training/sources.py` already ingests: MIDORI2 (mito: fish/animal), SILVA (16S/18S: bacteria/plant), UNITE (fungi → misc), BOLD (COI) | Days 11–15 |
| Q2 | Is upload metadata mandatory? | File only is required. Collection date and lat/long are *required for a partner report*. Reports flag incomplete provenance | Day 7 |
| Q3 | Do expert corrections feed retraining? | Yes, through the existing monthly frozen batches (B8 closes the loop) | Days 18–19 |
| Q4 | Negative control | Optional but flagged (`NegativeControlFlag` already handles `null`) | Day 7 |
| Q5 | Panels needing external feeds (wind/current, sonic, multi-omics, toxicity, ROI, biofouling, economic exposure) | **Remove for v1** and list them under "v2: external data" in `prd.md`. User-entered measurements (DO, pH) become optional upload metadata | Days 21–25 |
| Q6 | Co-occurrence network scale | Server-side top-50 taxa by detection count, plus a minimum co-occurrence threshold | Day 22 |
| Q7 | Upload "Processing Model" selector | Replace it with a read-only "models that will run" list from `/models/registry` | Day 5 |

**Owner decisions, 2026-10-14** (full reasoning in `decisions.md`):
Q1 reuse the existing sources plus the local BLAST DB, gather more through official APIs/bulk
downloads, then retrain · Q2 file required; partner report needs date + coordinates; every other
field optional, but each result states what was and was not provided · Q3 yes · Q4 **open** ·
Q5 try to gather real data / train first, fall back to removal at the Day 11 time-box · Q6 (a) ·
Q7 own orchestration layer choosing models and evidence per input. Q4 then answered: no blank is run in the team's workflow, so the field stays optional and results
flag its absence (option a). Q7 interpretation confirmed. Part B below is the re-plan.

---

## Part A status (2026-10-27, Day 17 docs pass, code at `32f38ef`)

Each Part A ID, checked against the code and `docs/qna.md`. The tables above are left as written on
2026-10-14 (their file:line citations describe the code as it was then). Commits are on
`LATEST_USHNIK`; a merge commit is given where the work landed through a sprint branch.

| ID | Status | Resolved by / reason open |
|----|--------|---------------------------|
| F1, F2, F4 | Resolved | `14cc931` (review queue and models routes, upload limit from `/health`); contract test `test_api_contract.py` |
| F3 | Resolved | route fixed `14cc931`; Sync now button wired `4ad24ed` (QNA-015) |
| F5, F6, F7 | Resolved | backend `3abbd1c` (QNA-005), frontend `c5e988f` (QNA-008) |
| F8 | Resolved | `d59be3a` (QNA-034): "Auto · Orchestrator" plus the served model per route |
| F9 | Resolved | reference lookup + orchestrator (QNA-020, QNA-024/025), flat taxon fields and report taxa (QNA-032), Species Correction shows names (QNA-034) |
| U1 | Resolved | helper deleted in QNA-007, re-added and used by AnalysisResults (QNA-034) and Novelty DNA (QNA-039) |
| U2 | Resolved | Novelty DNA uses `/summary`, `/novelty`, `/contamination` (QNA-007) |
| U3 | Resolved | `getReview` deleted, `getExpedition` used by AbyssSetup (QNA-007) |
| U4 | Resolved | `b341c7a` (QNA-015) |
| U5, U6 | Resolved | `bc540ae` (QNA-003): both routes deleted |
| U7 | Resolved | Model Status reads `/models/registry` (`14cc931`, QNA-004 Q3) |
| M1 | Resolved | `baf1238` (QNA-037) on the partner API (QNA-028) |
| M2 | Resolved | `4a0ef9c` (QNA-036); indicator-species panel is an explicit pending state |
| M3 | Resolved | `5c29038` (QNA-035) with the environmental context service (QNA-018) |
| M4 | Resolved | `f2bb868` (QNA-013) |
| M5 | Resolved | `902a029` (QNA-007): `PlaceholderScreen` deleted |
| D1–D5 | Resolved | `fedaf57` (QNA-002); shipped JS byte-identical before and after |
| D6 | Resolved | DisclaimerBanner `ff19f15`; ConfidenceChip/ProvenanceTag on results (QNA-034); chips on every model score, DetectionWindowBadge, MockTag deleted (QNA-039) |
| B1, B13 | Resolved | `38e6f4e` (QNA-004) |
| B2, B15, B22 | Resolved | `14cc931` (QNA-001): `data:` paths, notes rewritten, bacteria entry corrected |
| B3 | Resolved (local) | worker venv with CUDA torch; inference measured on the RTX 3070 (QNA-001 Q4). CI has no GPU or data root by design |
| B4 | Resolved | reference DB v1/v2 (QNA-012, QNA-016), lookup provider (QNA-020), orchestrator (QNA-024/025), evaluated (QNA-033) |
| B5 | Partly resolved | centroid distance replaces the proxy and is recorded, served at weight 0 by the dev criterion; owner decision open (QNA-038) |
| B6 | Resolved | `14cc931`: a job with no file fails |
| B7 | Resolved | `05d0fb1` (QNA-009) |
| B8 | Resolved | `d7726f0` (QNA-014), first live use QNA-023, full loop `bd8f550` (QNA-031). Open: "frozen before register" not enforced |
| B9 | Resolved in code | `10b2570` (QNA-027): Mongo records written first, Supabase mirror best-effort; no table dropped (all 12 in use). Open: migration `20261019000001` unapplied, Supabase host does not resolve (QNA-023 Q4) |
| B10 | Resolved | `f2bb868` (QNA-013) |
| B11 | Open — v1.1 | cut line: quantized models and offline reference pack not built |
| B12 | Resolved | dead import `bc540ae` (QNA-003); fallback logged `9391181`; learned-router copy (QNA-015) |
| B14 | Resolved | `a388fff` (QNA-006); 0.44 since QNA-038 |
| B16 | Resolved | partner API `8653d87` (QNA-028), hotspots/alerts (QNA-036), incidents/tasks (QNA-037), environment (QNA-018) |
| B17 | Open — v1.1 | cut line: loader LRU not built |
| B18 | Resolved / partly | `debug` removed `9391181`; JWT startup check and nginx limits `55dc8de` (QNA-019). Open: no proxy rate limit on Cloud Run (QNA-019 Q4) |
| B19 | Resolved | learned router v1 `4d02a2b` (QNA-010), v2 `1c2cab7` (QNA-021), promoted (QNA-023) |
| B20 | Open | `scripts/seed_dev.py` still writes mock analysis results; never run it on a demo or report database |
| B21 | Partly resolved | all scripted sources re-fetched and used in the rebuild (QNA-016); BOLD still not downloaded (owner task t-1014-3) |
| B23 | Resolved | router v2 is strand-invariant by construction, test accuracy 0.9155 on both strands (QNA-021), promoted (QNA-023) |
| B24 | Resolved | `233cf11`: compose mounts `synthveda-data` read-only at `/data` |
| B25 | Resolved | `9db53ce` (QNA-015) |
| B26 | Kept as intended | the `router` registry entry is a real model with real metrics |
| Q1–Q7 | Decided 2026-10-14 | `decisions.md`; Q5 sources checked live (`617576d`) and served (QNA-018); Q6 top-50 server-side (QNA-035); Q7 orchestrator (QNA-024) |

---

# Part B — Day-wise roadmap (October sprint, re-planned 2026-10-14 with owner decisions)

Legend: **YOU** = owner-only manual task · **BE** backend · **FE** frontend · **ML** model/data · **ALL**
whole team. IDs refer to Part A. Generated from the same plan file as the tracker page and the
calendar events, so the three agree.

**Scope changes from the owner decisions:** added data gathering + retraining (Q1), an
orchestration layer (Q7), an environmental-context service (Q5), and the "provided vs missing
metadata" statement on every result (Q2). **Cut to v1.1 now** to make room: loader LRU, quantized
offline models, offline reference pack, offline end-to-end run. Abyss heuristic triage already
works offline without them. **Q5 time-box:** Day 12 (25 Oct). A panel with no real source by then is
removed.

| Date | Day | Focus | Tasks (closes) | Done when | Depends on |
|------|-----|-------|----------------|-----------|------------|
| Wed 14 Oct | 1 | Decide, boot, start downloads | ALL: Decisions Q1–Q7 answered and logged in decisions.md (Q1–Q7) · ML: Re-download scriptable raw data (NCBI BLAST DBs, SILVA, UniVec, GRCh38) with scripts/fetch_reference_data.sh (Q1) · YOU: Log in to BOLD, accept the data terms, download the BOLD_Public Parquet package into synthveda-data/raw/bold/ (UNITE and MIDORI2 are now scripted) (Q1) · BE: Worker venv (Python 3.11) with requirements-dev + requirements-ml, CUDA torch (B3) · ALL: make up: Mongo, Redis, API, worker, frontend; login round-trip | Decisions recorded; reference downloads running; worker venv imports torch with CUDA; make up serves a login. | — |
| Thu 15 Oct | 2 | Quick wins: broken calls, real inference | FE: Fix getReviewQueue, getModels, syncExpedition to the real routes (F1, F2, F3) · FE: One upload size limit, served by the API and read by Upload.jsx (F4) · ALL: API contract test: every lib/api.js path is a registered FastAPI route · BE: Portable paths via SYNTHVEDA_DATA_ROOT: registry entries, build_dataset data dir, Linux blastdbcmd (B2, B15) · BE: A job with no file path fails clearly instead of parsing the fake ATCG sequence (B6) | inference_mode "model" on all 6 routes; Review Queue and Model Status load with no 404; contract test green. | 1 |
| Fri 16 Oct | 3 | Live model status, dead code out | BE: GET /models/status from registry + loader state; log malformed registry files (B1, B13) · FE: Model Status page on real registry metrics (U7) · FE: Delete App.jsx, App.css, src/api.js, stakeholders/*, StakeholderDashboardPage, Landing, DnaHelixViz, OrbitalVisualization (D1, D2, D3, D4, D5) · BE: Delete /auth/google/exchange, /analysis/{id}/report and the dead Abyss import (U5, U6, B12) | npm run build and both pytest suites green; nothing references the deleted files. | 2 |
| Sat 17 Oct | 4 | Learned router, one threshold, loud failures | ML: Learned k-mer router replaces the heuristic as the orchestrator's first stage (measured 24.1% → 82.4% on held-out tests); tune, calibrate, keep heuristic as fallback (B19) · BE: Shared NOVELTY_THRESHOLD replaces all 10 literals, plus a grep test (B14) · BE: Abyss fallback logs the exception (router_error_fallback); audit every except-pass; drop dead debug flag (B12, B18) · FE: NoveltyDNA slider reads the threshold; use /reports/{id}/novelty and /contamination; remove PlaceholderScreen (U1, U2, U3, M5) | Router accuracy on held-out tests measured and recorded (baseline 24.1%); no bare 0.45 novelty comparisons remain. | 3 |
| Sun 18 Oct | 5 | Metadata contract | BE: Upload fields collected_at, methodology, negative_control_included, collector, DO, pH; partner report requires date + coordinates (F5, F6, F7) · BE: Results carry a context block: optional fields provided vs missing, with an accuracy note (F5) · FE: Upload sends the fields; FieldLog and NegativeControlFlag render real values; results show the provided/missing context (F5, F6, F7) | Values typed at upload appear on Results and FieldLog, and every result states which optional fields were provided or missing. | 1 |
| Mon 19 Oct | 6 | More training data, object storage | ML: Gather extra sequences through official APIs (NCBI E-utilities, ENA, MGnify) for thin classes: animal possible_novelty, human contamination (Q1) · BE: Storage abstraction (local + S3-compatible), MinIO in compose, worker reads through it (B7) · FE: DisclaimerBanner on Results, Novelty DNA and Species Correction (D6) | New sequences gathered with accession IDs and licence noted; uploads land in MinIO. | 1 |
| Tue 20 Oct | 7 | Rebuild dataset and reference DB | ML: Rebuild processed/ on Linux from all sources; rerun the dedup/leakage check from THEORY_README (Q1) · ML: Per-route reference FASTA keeping taxonomy, versioned; vsearch + BLAST indexes (B4) | Expanded train/dev/test with zero cross-split duplicates; versioned per-route reference FASTA with taxonomy. | 1, 6 |
| Wed 21 Oct | 8 | Retrain heads, reference lookup | ML: Retrain the 6 route heads on the expanded set; record old vs new metrics as measured (Q1) · ML: Reference-lookup evidence provider: vsearch/BLAST top hits, rank by identity (97/95/90 provisional) (B4) | Six retrained heads with old-vs-new metrics recorded as measured; reference lookup returns taxon + rank + identity. | 2, 7 |
| Thu 22 Oct | 9 | Orchestrator core | ML: Evidence-provider interface: route heads, reference lookup, novelty, contamination (Q7) · BE: Orchestrator: per-sequence plan (top routes when router is unsure), run providers, combine evidence, write decision trace (Q7, B4) · ALL: qna.md transcript entry for the orchestration change | Each sequence gets a plan, evidence from several providers, one combined answer and a stored decision trace. | 8 |
| Fri 23 Oct | 10 | Orchestrator in results and UI | BE: Result fields predicted_taxon, taxon_rank, percent_identity, reference_db(_version), trace; report richness + top taxa (F9) · FE: Upload shows "Auto" with the planned models; results show the decision trace; real taxa with ConfidenceChip + ProvenanceTag (F8, F9, D6) · ML: Evaluate taxon assignment on held-out splits; record per route as measured | Species Correction shows real names; results page shows why each answer was chosen; taxon accuracy recorded. | 9 |
| Sat 24 Oct | 11 | Novelty, review tables, FieldLog | ML: Per-route centroid cosine distance replaces the typical_norm proxy; low identity feeds novelty; recalibrate threshold (B5) · BE: Write review_evidence, curation_decisions, training_batch_items; drop any table still unused (B9) · BE: FieldLog PATCH with edit history; attachments on the storage layer (B10) · FE: FieldLog real history and attachments; delete MOCK_NOTE and MOCK_FILES (M4) | Novelty uses centroid distance; review evidence persisted; FieldLog edits and attachments are real. | 4, 9 |
| Sun 25 Oct | 12 | Retrain loop, environmental data check | BE: POST /models/register and /models/{id}/promote writing model_eval_metrics; make train-promote calls it (B8) · FE: Admin page: promote button with in-page confirmation (B8) · ALL: Integration test for the full loop on a fresh clone · ML: Q5 checkpoint: confirm a real source per panel (Copernicus Marine, NOAA ERDDAP, MGnify); no source = remove (Q5) | Upload → orchestrator → review → batch → freeze → promote passes as one test; each external-data panel has a source or is marked for removal. | 3, 11 |
| Mon 26 Oct | 13 | Environmental context + partner API | BE: Environmental context service: Copernicus Marine / ERDDAP lookup by lat/long/date, cached per upload, source + timestamp stored (Q5) · BE: GET /partner/summary aggregation over uploads, results, reviews and environmental context (B16) | Each upload with coordinates + date gets cached temperature, salinity, DO, pH, currents and wind from a named public source. | 5, 12 |
| Tue 27 Oct | 14 | Academia and Legislative | FE: Academia: environmental panels from the context service, co-occurrence top-50, activity rhythms; FAIR ZIP export (M3) · BE: FAIR ZIP export endpoint; hash-chained custody at /reports/{id}/custody (M3, M2) · FE: Legislative: hotspot map, alerts, indicator trends from real data; enable exports; remove panels with no source (M2) | Academia and Legislative have no MockTag left. | 10, 13 |
| Wed 28 Oct | 15 | Industrial and integrity sweep | BE: audits collection with POST /partner/audits; field-log entries of kind "task" (M1) · FE: Industrial: incidents, impact score, audit trail, document hub from real data; remove panels with no source (M1) · FE: ConfidenceChip on every computed number; DetectionWindowBadge on Legislative; delete MockTag.jsx (D6) | grep -r MockTag web_frontend/src finds nothing; no setTimeout fake success anywhere. | 13, 14 |
| Thu 29 Oct | 16 | Abyss online pieces, E2E tests | FE: AbyssSetup calls /auth/expedition/session; add Sync now on the fixed route (U4, F3) · FE: Playwright suite covering every routed page, added to ci.yml | An expedition activates and syncs back; Playwright runs in CI. | 2 |
| Fri 30 Oct | 17 | Harden and document | BE: jwt_secret startup check outside dev; nginx limit_req on admin-key redeem (B18) · ALL: Remove legacy/; gitignore PSEUDO FILE, .playwright-mcp, synthveda-data; move root PNGs · ALL: Update memory, phases, architecture, flow; paper numbers as measured; mark the audit resolved | Security scan clean at medium+; docs and paper match the code and the measured numbers. | 15 |
| Sat 31 Oct | 18 | Release candidate | ALL: Fresh clone → make up → full flow passes; tag v1.0.0-rc1 · ALL: Walk the exit-criteria checklist and tick each one | Every exit criterion in ROADMAP_REAL_DATA.md holds. | 17 |

## Exit criteria (the project is "finished" for v1 when all are true)

- [ ] `grep -r MockTag web_frontend/src` → nothing; no `setTimeout`-faked success anywhere
- [ ] The API-contract test passes: every `lib/api.js` call maps to a real route
- [ ] Real uploads return `inference_mode: "model"` on all 6 routes, plus `predicted_taxon` with rank, identity and reference DB version
- [ ] No hardcoded novelty threshold; one constant, imported everywhere
- [ ] A trained model can be registered and promoted through the app
- [ ] FieldLog edits and attachments persist; uploads live in object storage
- [ ] Partner pages show only computed data or honest empty states
- [ ] Abyss offline flow works with the network off
- [ ] CI is green: pytest (both services), frontend build, Playwright, bandit
- [ ] The measured accuracy numbers in the paper match `checkpoints/*/eval_report.json` and the Day 14 evaluation

## Dependency overview

The **Depends on** column above is the full graph. Days 5 and 6 depend only on Day 1, and Day 15
only on Day 2, so any of them can be pulled forward whenever a track is free.
