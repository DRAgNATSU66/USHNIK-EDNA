# Synth Veda — Mock Data, Unbuilt Backends & Undecided Logic Audit

Snapshot date: 2026-09-03. Companion to `docs/architecture/SYNTH_VEDA_PHASE_PLAN.md` (the
15-phase build plan) and `docs/specs/SYNTHVEDA_MISSING_FEATURES.md` (UI/UX gap checklist).
This document is the code-level reality check: every place the running app currently fakes,
stubs, or leaves undecided something a "fully polished working tool" needs. Every item has a
file:line citation so it can be re-verified — the codebase moves fast, treat line numbers as
approximate once other work lands.

Each item is tagged with a **Fix Phase** (see `ROADMAP_TO_POLISHED_TOOL.md` for what each phase
means) so this doc and the roadmap stay in sync.

This document has two passes. **Sections 1-3** are things the code itself flags — a `MockTag`
component, or a comment/name containing "mock", "TODO", "stub", "not yet," etc. **Section 4** is
the more dangerous set: the same categories of problem, but with *no* self-flagging — nothing in
the code warns a reader these are fake, unfinished, or silently risky. A keyword search will never
find Section 4's items; they were found by reading the surrounding logic and checking whether it
does what it appears to do.

---

## Quick-reference index

| # | Item | Category | Subsystem | Fix Phase |
|---|------|----------|-----------|-----------|
| 1 | Review Queue page 404s (`GET /reviews` vs `/reviews/queue`) | Unbuilt backend (bug) | Curation | P1 |
| 2 | Model Registry page 404s (`GET /models` vs `/models/status`) | Unbuilt backend (bug) | ML ops | P1 |
| 3 | Broken import in Abyss analysis engine | Undecided/dead code | Abyss | P1 |
| 4 | `App.jsx` orphaned prototype app | Mock data / dead code | Legacy UI | P1 |
| 5 | `stakeholders/` dashboard tree unreachable | Mock data / dead code | Dashboards | P1 |
| 6 | Industrial partner report — zero API integration | Mock data | Partner/Industrial | P3 |
| 7 | Legislative partner report — zero API integration | Mock data | Partner/Legislative | P3 |
| 8 | Academia partner report — tagged mock panels | Mock data | Partner/Academia | P3 |
| 9 | FieldLog edit history / attachments mocked, no PATCH endpoint | Mock data + unbuilt backend | Field Log | P3 |
| 10 | `GET /models/status` returns hardcoded dict | Mock data (server-side) | ML ops | P2 |
| 11 | All inference is stub (`predicted_taxon=None` everywhere) | Undecided/unbuilt | ML inference | P2 |
| 12 | Model registry points at dev-only Windows paths | Unbuilt backend | ML inference | P2 |
| 13 | Object storage configured but unused (uploads go to local disk) | Unbuilt backend | Uploads | P2 |
| 14 | Retrain/promotion loop stops at "batch frozen" | Undecided/unbuilt | Training pipeline | P2 |
| 15 | Novelty embedding-isolation signal is a weak proxy | Undecided (TODO) | Novelty scoring | P2 |
| 16 | Loader has no LRU eviction (single-model-per-route only) | Undecided (acknowledged limitation) | ML inference | P4 |
| 17 | Unused Supabase tables (`review_evidence`, `curation_decisions`, `training_batch_items`, `model_eval_metrics`) | Unbuilt backend | Data model | P2/P4 |
| 18 | Abyss offline pack: quantized models + reference pack not yet available | Unbuilt backend | Abyss | P4 |
| 19 | Expedition offline-auth endpoints implemented but unused by frontend | Unbuilt backend (unwired) | Abyss/Auth | P3 |
| 20 | Redundant `GET /analysis/{id}/report` vs `/reports/{id}` | Undecided/dead code | Reports | P4 |
| 21 | Product decisions left open (reference DB, metadata required?, corrections→retraining?) | Undecided logic | Product/cross-cutting | P0 |
| 22 | `jwt_secret` defaults to a public string, no startup check | Undecided/security risk (unflagged) | Auth/security | P5 (deferred — internal project) |
| 23 | Upload size limit mismatch: frontend 500MB vs backend 100MB | Undecided logic (unflagged) | Uploads | P1 |
| 24 | Novelty threshold (0.45) hardcoded independently in 9+ places | Undecided logic (unflagged) | Novelty scoring | P2 |
| 25 | Malformed model registry files silently dropped, no log | Unbuilt backend (unflagged) | ML ops | P2 |
| 26 | Abyss router falls back to cruder heuristic on any exception, silently | Unbuilt backend (unflagged) | Abyss | P2 |
| 27 | Docker Compose has no rate limiting despite code assuming infra handles it | Undecided/unbuilt (unflagged) | Auth/security | P5 (deferred — internal project) |
| 28 | `debug` config flag defined, never read anywhere | Dead code (unflagged) | Config | P4 |
| 29 | `ConfidenceChip`/`DetectionWindowBadge` built, never rendered anywhere | Unbuilt backend/UI (unflagged) | Cross-cutting UI | P3/P5 |
| 30 | Upload page's model selector doesn't affect the actual analysis request | Mock data (unflagged, but comment-documented) | Upload | P3 |

---

## 1. Mock Data

### 1.1 Self-tagged mock panels (`MockTag` component)
The team already flags known-fake UI with a shared `MockTag` component
(`web_frontend/src/components/shared/MockTag.jsx:1-25`), so these are self-documented, not hidden:

- **Academia report** (`web_frontend/src/pages/partner/Academia.jsx`) — otherwise a real,
  API-backed page, but these panels are mock: dissolved oxygen (560), toxicity index (566),
  temperature-at-depth (576), pH (604), salinity-when-not-recorded (609), wind/current speed by
  day (621), multi-omics overlay (628), sonic activity (637), activity rhythms (652), species
  co-occurrence network (665), FAIR ZIP bundle export (676, 713).
- **FieldLog** (`web_frontend/src/pages/researcher/FieldLog.jsx`) — `MOCK_NOTE` (21-27),
  `MOCK_FILES` (29-33), edit-history preview (374), file-attachment UI (436, 451), per-field mock
  flags for DATE/TIME, METHODOLOGY, NEGATIVE CONTROL, COLLECTOR (264, 270-272). Uploading a file
  triggers `alert("File storage isn't wired up yet — this is a mock preview...")` (471).

### 1.2 Fully static pages — no API calls at all
- **Industrial** (`web_frontend/src/pages/partner/Industrial.jsx`) — confirmed zero imports from
  `lib/api`. Every number is a hardcoded constant, e.g. `RADAR_VALS = [0.62, 0.74, 0.48, 0.66,
  0.35]` (line 43). Fake panels: active incidents, avg impact score, pending audits (332, 342,
  347), environmental risk radar (359), biological impact metrics (370), audit trail (399),
  remediation plan (406), document hub (415), quick notes/tasks (426), predictive biofouling
  threshold (466), remediation ROI (473).
- **Legislative** (`web_frontend/src/pages/partner/Legislative.jsx`) — also zero API calls.
  Biodiversity hotspot map (467), active alerts (480), indicator species trend (508),
  habitat-associated taxa decline (515), economic risk/compliance exposure (524), cryptographic
  chain of custody (588).

### 1.3 Fake-success buttons (local state only, no backend call)
- `Industrial.jsx:308-311` — `scheduleAudit()` just flips `setScheduled(true)` then resets after
  1.6s via `setTimeout`; comment at 303-307 self-admits "no real audit-scheduling backend."
- `Legislative.jsx:444-447` — `runFeasibility()` fakes an async economic-feasibility run the same
  way (`setTimeout` → `"done"` after 1.4s).
- `Legislative.jsx:529-530` — Export Report/CSV buttons are at least honestly disabled
  (`inertBtnStyle`, tooltip "No live regional feed connected yet") rather than fake-succeeding.

### 1.4 Dead mock dashboard suite (unreachable — not in the router)
`web_frontend/src/pages/stakeholders/*` (ResearcherDashboard.jsx, PolicymakerDashboard.jsx,
IndustryDashboard.jsx, DashboardSelectionScreen.jsx, DashboardSwitcher.jsx) plus
`StakeholderDashboardPage.jsx` — **confirmed not imported/routed anywhere in `main.jsx`**. ~150KB
of dead code full of hardcoded data: `sampleMatches`/`sampleNovels`
(`ResearcherDashboard.jsx:13-21`), hardcoded KPI `124` (line 236); `sampleCSVRows` and fake-success
`alert(...placeholder...)` buttons in `IndustryDashboard.jsx:15,35,327,473,483`; permanently-stuck
"Loading chart…" / "Full viewer placeholder" (400, 449, 520); `sampleCSVRows` and a "dummy economic
feasibility simulation (async fake)" plus hardcoded Indian-Ocean coordinates in
`PolicymakerDashboard.jsx:38,60,1014`. Only inbound reference is from `App.jsx` (also dead, see next).

### 1.5 Orphaned prototype app (`App.jsx`, not imported by `main.jsx`)
1389-line Three.js DNA-helix prototype that does not run in the shipped app, but is easy to
mistake for live code:
- `App.jsx:12-46` — `analyzeFastaFile()` POSTs to `http://127.0.0.1:8000/analyze`, an endpoint
  **that does not exist** in `services/api/app` (only `/abyss/analyze` exists, a different route).
- `App.jsx:705-717` — "demo mode" hardcodes fixed species/confidences (S. cerevisiae, E. coli,
  H. sapiens, G. gallus, O. sativa).
- `App.jsx:728-735` — on backend failure, silently falls back to `mock-fallback` species
  (`Fallback_species_A/B`) and tells the user "Showing demo data instead" — i.e. presents fake
  results as if from a real run.
- `App.jsx:981-1004` — `generateStakeholderReport()` just logs, toasts, and navigates to the dead
  `/stakeholder` route from 1.4.

### 1.6 Server-side hardcoded response (production code, not a test fixture)
`services/api/app/models/router.py:29-40` — `GET /models/status` returns a static dict for all 6
routes (`fish`, `plant`, ... all `"status": "unavailable"`), not a live registry/loader query.
Nothing in the frontend currently calls this exact function (`ModelStatus.jsx` hits a different,
broken path — see Item 2 below) but it's real endpoint code, not test-only.

### 1.7 Inference results are placeholder data by design (not a UI bug)
Every `PredictionResult` in production today has `predicted_taxon=None`, `confidence=0.0`,
`label_scores={}` (`services/worker/app/inference/predictor.py:108-134`), and the report builder
explicitly documents this (`services/api/app/reports/models.py:67-71`). The frontend correctly
hides the `"stub_none"` pipeline version rather than displaying it as real
(`AnalysisResults.jsx:501`, `SpeciesCorrection.jsx:541`, `NoveltyDNA.jsx:528`) — so this is honestly
surfaced, but it means **the entire DNA classification result set delivered to users today is
placeholder**, not a cosmetic mock. See Item 11.

---

## 2. Unbuilt / Stubbed Backends

### 2.1 Confirmed broken wiring (cheap, high-value fixes)
1. **Review Queue 404s.** `web_frontend/src/lib/api.js:156-157` calls `getReviewQueue() → GET
   /reviews`, but the backend only exposes `GET /reviews/queue`
   (`services/api/app/reviews/router.py:121`). `ReviewQueue.jsx:221-222` calls this on page load —
   **the entire curator review page is broken in production.** Backend logic exists; it's a URL fix.
2. **Model Registry page 404s.** `web_frontend/src/lib/api.js:198` calls `getModels() → GET
   /models`, but the backend only defines `GET /models/status` and `GET /models/registry`.
   `ModelStatus.jsx:34` calls this on mount — **`/models` route also 404s.**

### 2.2 Implemented backend, never wired to frontend
- `POST /auth/expedition/session` and `POST /auth/expedition/verify`
  (`services/api/app/auth/router.py:354,421`) — full offline-expedition JWT logic exists; no page
  (including `AbyssSetup.jsx`) calls either endpoint.
- `POST /auth/google/exchange` (`auth/router.py:152`) — ID-token flow exists but unused; frontend
  only uses `POST /auth/google/code-exchange`.
- `GET /analysis/{analysis_id}/report` (`analysis/router.py:104-134`) — duplicates
  `GET /reports/{analysis_id}` (what `getReport` actually calls). Dead/redundant, not broken.
- `SupabaseClient.register_model_version` / `promote_model`
  (`services/api/app/db/supabase_client.py:400,406`) — fully implemented, **never called from any
  router** — there is no API endpoint to actually promote a trained model. This is the missing
  link that keeps the retrain loop open (see Item 14).

### 2.3 Schema exists, nothing reads or writes it
Confirmed via repo-wide grep — none of these appear outside their migration file:
`review_evidence`, `curation_decisions`, `training_batch_items`, `model_eval_metrics`
(`supabase/migrations/20260526000001_initial_schema.sql:192,208,273,314`). Tables that *are* used:
`user_profiles`, `admin_invite_keys`, `role_assignments`, `expert_reviews`, `curated_sequences`,
`training_batches`, `model_versions`, `audit_logs`.

### 2.4 Explicitly not-yet-available (self-documented)
`services/api/app/abyss/offline_pack.py:96-149` — `route_models_quantized`
(`"status": "not_yet_trained"`) and `reference_pack_v1` (`"status": "not_yet_available"`). Only
license, a hardcoded contaminant motif list, and metadata stubs ship today.

### 2.5 Object storage configured, never used
`services/api/app/config.py:31-33` defines `object_storage_url` / `object_storage_bucket`, but
`services/api/app/uploads/router.py:80-87` writes every upload to local disk with an explicit
comment: *"In production this would upload to S3/GCS instead."* Confirmed unused elsewhere.

### 2.6 Broken/vestigial import
`services/api/app/abyss/analysis.py:107-109` — a malformed `from ..app.model_router import ...`
inside `try/except ImportError: pass` always fails silently; the real (correct) import happens
later via manual `sys.path` manipulation in `_heuristic_route()` (line 222). Dead, confusing code.

---

## 3. Undecided / TODO Logic

### 3.1 Inference is stub-mode almost everywhere it will actually run
- `services/worker/app/inference/predictor.py:55-76` — falls back to `_stub_prediction()` on
  low-quality route, missing torch, no runnable model, or load failure.
- Every model in `models/registry/*.json` is `"status": "experimental"` with `artifact_uri`
  pointing at a **Windows-only local path** (e.g. `E:\synthveda-data\checkpoints\...` in
  `dnabert2_fish_v1.json`). `services/worker/app/inference/loader.py:188-198` will fail to resolve
  these on any other machine — **stub inference is effectively the only path that runs in any
  deployed/Docker/CI environment today.**
- `predictor.py:204` — `predicted_taxon=None` even on the real-model path, marked
  `# Phase 14: taxonomy lookup from label index` (not yet built).
- `services/worker/app/job_runner.py:10` — module docstring: "Phases 7–8 stubs remain until those
  phases are implemented." `_stage_parse` (84-97) falls back to a hardcoded `seq_stub_001` /
  `"ATCGATCGATCG"` sequence when no file path is present.
- `services/worker/app/novelty/signals.py:168-193` — `signal_embedding_isolation()`:
  `# TODO Phase 14: compute cosine distance to nearest cluster centre.` Currently a weak proxy
  (embedding L2 norm vs. hardcoded `typical_norm = 14.0`).
- `services/api/app/abyss/analysis.py:11-13,120-145,291-335` — Abyss Mode's `_stub_result_class`,
  `_stub_label_scores`, `_StubNoveltyScore`, `_StubContaminationScore` are **intentional permanent**
  heuristics for field triage, not TODOs — distinct from the worker's "not yet trained" stub state.
  Don't conflate the two when planning fixes.

### 3.2 Retraining pipeline half-wired
`services/api/app/reviews/curation.py:169-192` (`create_monthly_training_batch`) and
`reviews/router.py:309-328` assemble and freeze training batches
(`curation.py:264-279,186-189`: *"the actual model retrain is a manual step (Phase 14)"*), but
nothing calls `register_model_version`/`promote_model` afterward — the loop stops at "batch frozen."

### 3.3 Acknowledged engineering limitations
- `services/worker/app/inference/loader.py:67-70` — no LRU eviction; single-model-per-route is the
  deliberate MVP strategy, not a bug, but will need revisiting before multi-tenant scale.
- `loader.py:34-42` — `sys.modules.setdefault("triton", None)` workaround for a training-host bug,
  fragile but intentional (see `services/worker/training/finetune.py`).

### 3.4 Frontend half-built escape hatches
- `web_frontend/src/pages/ResearcherMode.jsx:16` — falls back to a `PlaceholderScreen` ("This
  section isn't available yet.") for any `section` other than `novelty-dna`, `species-correction`,
  `comments`. No current route triggers it, but the escape hatch signals more sections were planned.
- `FieldLog.jsx:591` — explicit note that edit history/attachments are mock previews, "backend
  support is coming later"; confirmed no `PATCH /field-log/entries/{id}` exists
  (`services/api/app/field_log/router.py` only has `POST /entries`, `GET /entries`).

### 3.5 Open product decisions (from `SYNTHVEDA_MISSING_FEATURES.md`, still unresolved)
These block correct implementation of several sections above and are tracked there in detail —
listed here because they're the root cause of some "mock" items (e.g. Industrial/Legislative
can't be un-mocked until the underlying data-source decisions are made):
- Which reference database(s) — NCBI / SILVA / BOLD / custom.
- Metadata mandatory vs. optional at upload (mockup says optional, conflicts with chain-of-custody).
- Live-streaming vs. render-at-completion for Upload Analysis.
- Species Correction: does a correction feed model retraining, or is it audit-only?
- Industrial predictive/financial figures: real trend-model backing, or single-point extrapolation
  needing softer framing?
- Negative control: required per run, or optional-but-flagged?
- Co-occurrence network scale-handling for Academia (thousands of nodes).

### 3.6 Minor / cosmetic
- `services/api/app/reports/builder.py:222` — sort order chosen "to mirror the mockup," not a spec.
- `reports/builder.py:311` — `version = ... or "stub_none"`, consistent with 1.7/3.1.

---

## 4. Unflagged — no comment, tag, or name warns a reader these are fake, unfinished, or risky

Found by reading logic directly rather than grepping for "mock"/"TODO"/etc. Most pages checked in
this pass — Landing, Login, Signup, Upload's core flow, JobProgress, AbyssSetup, NoveltyDNA,
SpeciesCorrection, `lib/api.js`, `AuthContext.jsx` — turned out clean: real API calls, real
polling, errors surfaced to the user. These items are the exceptions.

### 4.1 Silent config default with real security consequences

`services/api/app/config.py:27` — `jwt_secret: str = "change-me-in-production"`. This single key
signs **every** token type in the system: normal user access tokens (`auth/jwt.py:13`), the
session equivalent (`auth/session.py:45`), the **45-day offline Abyss expedition session tokens**
(`auth/session.py:24,41,45` — designed to validate entirely without contacting the server), and
the **90-day offline analysis license tokens** (`abyss/offline_pack.py:67`). Nowhere in
`services/api/app/main.py`'s startup (`lifespan()`, lines 19-49) — or anywhere else — is there a
check or warning if this default is still active at boot. A deployment that forgets to set
`JWT_SECRET` silently runs with a publicly-known signing key for both regular auth and long-lived
offline field-device credentials. Worst case: forging a 90-day Abyss offline license or a
role-elevated access token. This is the single highest-severity item in the whole audit.

### 4.2 Silently swallowed errors → response looks like success

- `services/api/app/models/router.py:51-54` — `GET /models/registry` does `except Exception: pass`
  when parsing a registry JSON file, silently dropping any malformed model file from the returned
  list, with no log line. A curator sees fewer models than actually exist on disk with no
  indication why.
- `services/api/app/abyss/analysis.py:243-245` — if the real heuristic router (`route_sequence`)
  throws for any reason, Abyss analysis silently falls back to `_simple_gc_route()` (a cruder,
  GC-ratio-only heuristic, lines 248-288) with **no logging of the exception**. The response shape
  is identical to a real routing result — the only tell is a generic reason code like
  `"gc_fallback_misc"`, easy to miss, and there's no way to distinguish "the heuristic legitimately
  produced this" from "the real router crashed."

### 4.3 Duplicated magic numbers with no shared source of truth

- **The 0.45 novelty-flagging cutoff is independently hardcoded in at least 9 places**, with no
  shared import: `services/worker/app/job_runner.py:252,282,338,359,375`,
  `services/api/app/reviews/curation.py:323,359`, `services/api/app/reports/router.py:81,157`,
  `services/api/app/abyss/analysis.py:57,363`. Only `services/api/app/reports/builder.py:39` names
  it as a constant (`_NOVELTY_THRESHOLD = 0.45`), and that constant is never imported anywhere
  else. Tuning this threshold would require six-plus manual edits across two services — a missed
  spot silently diverges (e.g. a sequence could be auto-queued for review under one cutoff while
  the report/UI shows a different flagged set).
- **Upload size limit mismatch.** Backend default is `max_upload_size_mb: int = 100`
  (`services/api/app/config.py:50`, matching `.env.example:26`), but the frontend hardcodes
  `MAX_SIZE_MB = 500` (`web_frontend/src/pages/Upload.jsx:29`) and tells the user "up to 500 MB"
  (line 308). A 200-499MB file passes client-side validation, uploads in full, and only then gets
  rejected with an HTTP 413 from `services/api/app/uploads/router.py:59-63` — a large, slow,
  entirely wasted upload for the user. Nothing cross-references the two values.
- `services/api/app/auth/router.py:263` — a comment asserts rate limiting "must be enforced at the
  infra/proxy layer" for the invite-key redemption endpoint (a brute-forceable 8-char alphanumeric
  key, hashed lookup only). See 4.4 — that's only true for one of the two deployment paths this
  repo actually ships.

### 4.4 Infra gap the code assumes is covered

Rate limiting is real for the GCP path (`infra/terraform/main.tf:95-122` configures Cloud Armor
per-IP limits), but the Docker Compose load balancer actually shipped in the repo,
`infra/docker/nginx-lb.conf`, has **zero** `limit_req`/`limit_conn` directives. Anyone running the
documented docker-compose stack gets no rate limiting anywhere — including on admin-key redemption
— directly contradicting the assumption in 4.3's `auth/router.py:263` comment, with nothing
surfacing the gap.

### 4.5 Dead config flag

`services/api/app/config.py:13` — `debug: bool = False` is defined but never read anywhere in
`services/api/app` (confirmed by repo-wide grep). Looks like a real environment toggle; does
nothing regardless of its value.

### 4.6 Built components that enforce nothing because they're never rendered

`web_frontend/src/components/shared/DetectionWindowBadge.jsx` and
`web_frontend/src/components/shared/ConfidenceChip.jsx` are fully written, correctly implemented,
and have **zero import sites anywhere else in the repo** (confirmed by grep). Both are explicitly
documented in their own JSDoc as shared spec components — `ConfidenceChip.jsx:6-8` states its own
purpose is to ensure "no number appears as unqualified fact" — but since nothing imports them, that
guarantee isn't enforced anywhere in the shipped UI. This is easy to miss in review because the
component itself looks complete; only a repo-wide reference search reveals it's dead. Directly
relevant to `SYNTHVEDA_MISSING_FEATURES.md`'s cross-cutting "Confidence/Source Citation chip"
item — the component this item needs already exists, it's just not wired to anything.

### 4.7 UI control that doesn't affect what it appears to control

`web_frontend/src/pages/Upload.jsx:59-68` — the `MODELS_BY_MODE` selector lets a user pick between
named "Processing Models" (e.g. "AbyssNet v3", "MetaGen Lite"). A comment at lines 54-58 explains
this is "a design-only concept for now" that doesn't affect the analysis run — and indeed
`POST /analysis/jobs` (`web_frontend/src/lib/api.js:112-113`) only ever sends `mode`, never a model
field. Not silent in the sense of hiding a comment, but the UI itself gives no in-context signal to
the user clicking through it — a real user has no way to know their model choice is inert.

---

## Also flagged (cleanup, not build work)

- **`legacy/`** — a separate, older sklearn-based prototype (`legacy/src/species_identification`,
  `legacy/src/web_api`, etc.), clearly superseded by `services/api` + `services/worker`. Candidate
  for deletion once nobody needs to reference it.
- **`frontend_zips_claude_design/`** — static design mockups/screenshots, not app code. Fine to
  keep as design reference but shouldn't be confused with the live frontend.
