# Synth Veda — QNA transcript

A stenographic record of major changes, written as they happen. It never blocks a merge,
commit or push. Entries are append-only: a wrong entry is superseded by a new one that says so,
and the original stays. Numbers are recorded as measured, including unflattering ones.

Recorded: changes over 3 files · routing, orchestration, agent or model-registry changes · model
or dataset swaps · schema and migrations · anything claimed in the paper or a demo.

---

## QNA-001 — 2026-10-14 — Portable model registry, bacteria entry correction, router accuracy measured

**Commit:** uncommitted working tree on `LATEST_USHNIK` (base `492b20a`). Update this line with the
commit hash once it lands.

**Q1. Mechanism: what changed in how models are found and loaded?**
Registry entries now say `"base_model": "data:checkpoints/<route>/backbone"` and
`"artifact_uri": "data:checkpoints/<route>/head.pt"`.
`services/worker/app/inference/registry.py` expands the `data:` prefix against
`$SYNTHVEDA_DATA_ROOT`. Without that variable it walks up from the module to the first
`synthveda-data/` directory, and in Docker it falls back to `/data`. Values without the prefix
(Hugging Face ids) pass through unchanged. Before this, every entry hardcoded
`E:\synthveda-data\...`, so `_resolve_local` failed on every machine except the old Windows laptop
and all six routes ran stub inference.

**Q2. Rationale: why a `data:` prefix and not plain relative paths?**
`base_model` legitimately holds Hugging Face ids such as `zhihan1996/DNABERT-2-117M`, which look
identical to a relative path. The prefix makes the intent explicit, and an HF id can never be
mistaken for a local file.

**Q3. Blast radius: what else changed, and what breaks if it is wrong?**
- `models/registry/dnabert2_bacteria_v1.json` described an older run (test acc 0.8006, macro-F1
  0.8468, train 12,320) than the `head.pt` on disk. The file is a 4-class head whose
  `eval_report.json` and `metrics.json` give acc 0.842, macro-F1 0.8529, train 37,832. Its
  SHA-256 matched neither the registry checksum nor anything else on record. The entry now
  describes the weights that actually run. The other five checksums matched.
- If the data root resolves wrong, the loader returns `None` and the predictor falls back to stub
  mode. That is visible as `inference_mode: "stub"` on every result, not a silent wrong answer.

**Q4. Verification: what proves it works?**
- `run_inference` on 20 held-out test sequences per route: `inference_mode=model` on all six
  routes, on the RTX 3070. Predicted class matched the label for fish 20/20, plant 16/20,
  bacteria 17/20, animal 20/20, human 20/20, misc 19/20. A smoke test, not an evaluation.
- Full pipeline through the API and worker (upload `upl_593a3f5bae874205`, job
  `job_08439d04b5844a0c`): completed in about 1.1 s with real model ids on every result.
- Test suites: API 269 passed (including the new `tests/test_api_contract.py`), worker 142 passed.

**Q5. Defence: "your per-route models are 94–99% accurate, so the system works", right?**
No, and this is the most important number recorded today. The end-to-end run routed fish and
plant sequences to the wrong model. Measured on 300 held-out non-low-quality test sequences per
route, **the heuristic router picks the correct route for 24.1% (433/1,800)**: fish 0.3%,
plant 0.0%, animal 1.7%, human 11.0%, misc 54.0%, bacteria 77.3%. The per-route head metrics
hold only when routing is right, so any end-to-end claim built on them is overstated until
routing is fixed. A 10-second, untuned 6-mer hashed logistic classifier, trained on up to 4,000
sequences per route from the same `train.csv` files, reached **82.4%** on the same test set
(macro-F1 0.824; animal 0.714 and misc 0.753 are the weak classes). Not yet wired in: scheduled
for Day 4. The paper must not report per-route accuracy as system accuracy.

**Q6. What is still unverified?**
- The 82.4% has had no leakage check across routes (the existing dedup is per route) and no
  calibration.
- The Google-login round-trip in the browser was not exercised. The API was driven with a locally
  minted dev JWT.

---

## QNA-002 — 2026-10-15 — Dead frontend code removed (roadmap D1–D5, tracker t-1016-3)

**Commit:** this commit on `sprint/d3-dead-frontend` (base `14cc931`, `LATEST_USHNIK`).

**Q1. Mechanism: what was removed?**
12 files under `web_frontend/src/`, 5,624 lines in total: `App.jsx` (1,388) and `App.css` (42) (D1),
`api.js` (95) (D2), `pages/stakeholders/*` (5 files, 3,723) and `pages/StakeholderDashboardPage.jsx`
(40) (D3), `pages/Landing.jsx` (174) (D4), and `components/DnaHelixViz.jsx` (103) and
`components/OrbitalVisualization.jsx` (59) (D5). No live file was edited. `healthCheck` in
`src/lib/api.js:233` was **kept**, because `pages/Upload.jsx:6,155` still calls it. The D6 components
(`components/shared/ConfidenceChip`, `DetectionWindowBadge`, `DisclaimerBanner`) were not touched.

**Q2. Rationale: why delete rather than leave or quarantine them?**
They were unreachable, and they looked like real product code. `App.jsx` and `src/api.js` post to a
`/analyze` endpoint that does not exist, and on failure they display invented species
(`Fallback_species_A/B`). The stakeholder dashboards run entirely on mocked data. Anyone reading
the source, including reviewers, could take them for live behaviour. Git history keeps them if
they are ever needed (`git show 14cc931:web_frontend/src/App.jsx`).

**Q3. Blast radius: what breaks if this is wrong?**
Only a route or import that pointed at a deleted file, and the build would have failed on that.
`src/main.jsx` routes `/` to `Login`, and nothing routes `Landing`, `App` or `StakeholderDashboardPage`.
After the deletion, `grep -rnE` for every deleted filename and component name over
`web_frontend/src` finds nothing. npm packages were **not** changed. See Q6.

**Q4. Verification: what proves it?**
- `npm run build` passes on this commit.
- I built base `14cc931` from a clean `git archive` with the same `node_modules`. The JS bundle is
  **byte-identical** (sha256 `8016c53d…500f`, 771,241 B in both builds). So none of the deleted code
  was ever shipped. CSS went from 34.99 kB to 33.36 kB, because Tailwind v4 had been picking up
  utility classes from the dead files.
- `services/api` `pytest tests/test_api_contract.py -q` gives 38 passed. That test parses
  `src/lib/api.js`, which is unchanged.

**Q5. Defence: "deleting 5.6k lines right before a demo is risky"?**
The shipped JS is the same bytes as before (Q4), so the running app cannot behave differently. The
only output change is 1.63 kB of Tailwind CSS that nothing live used. What the change removes is the
risk that someone quotes or demos mocked results as if they were real.

**Q6. What is still open?**
These npm dependencies now have no importer in `src/`: `three`, `@react-three/fiber`,
`@react-three/drei`, `chart.js`, `react-chartjs-2`, `axios`. Three more already had no importer
before this change: `recharts`, `react-icons`, `lucide-react`. `package.json` and the lockfile were
deliberately left unchanged. Removing them needs an `npm uninstall` against the real `node_modules`,
which is a separate step. `src/assets/react.svg` is a Vite-template leftover with no references, and
it was out of scope here. `leaflet` and `react-leaflet` are still used by `pages/partner/Legislative.jsx`.

---

## QNA-003 — 2026-10-15 — Dead API endpoints removed (roadmap U5, U6, B12 dead import; tracker t-1016-4)

**Commit:** `bc540ae` on `sprint/d3-dead-endpoints`, merged into `LATEST_USHNIK` as `1d7e7bf`.
(QNA-001 describes commit `14cc931`.)

**Q1. Mechanism: what was removed?**
`POST /auth/google/exchange` and its `GoogleExchangeRequest` model (`services/api/app/auth/router.py`);
`GET /analysis/{id}/report` (`services/api/app/analysis/router.py`, 32 lines); and the
`from ..app.model_router import ...` block in `services/api/app/abyss/analysis.py` (old :106-109).
Every Google sign-in now goes through `/auth/google/code-exchange` →
`_token_response_for_google_claims`. 6 files, +47/−146.

**Q2. Rationale: why delete rather than keep for compatibility?**
The frontend never called either route: `lib/api.js` uses only `/auth/google/code-exchange`
(`:81`) and `/reports/...`. The `/analysis/{id}/report` handler duplicated `GET /reports/{id}`.
The Abyss import pointed at `app.app.model_router`, a module that has never existed, so it always
raised `ImportError` and was swallowed. Removing unused auth surface also removes an untested way
in.

**Q3. Blast radius: what breaks if this is wrong?**
Any external client still posting a Google `id_token` to `/auth/google/exchange` now gets a 404.
None is known; the web frontend uses the code flow. The account-linking rules (keep role, link by
email, create a new row, sign-in while Supabase is down) are unchanged and are now tested only
through the code-exchange endpoint. `verify_google_id_token` stays in `auth/google.py`, where
`exchange_code_for_claims` uses it. The Abyss fallback logging at `abyss/analysis.py` ~:239 is
untouched (Day 4 task).

**Q4. Verification: what proves it?**
API suite on merged `LATEST_USHNIK` (`1d7e7bf`): **267 passed**. That is 269 − 4 removed + 2 added
tests. The two new tests assert the routes are absent from the app's route table, not just that
they return 404. The old `/analysis/{id}/report` test checked for a 404 on an unknown id, so it
would have passed even with the route deleted. The new tests fail on `14cc931`, where both paths
are registered.

**Q5. Defence: "you deleted tests to make the suite pass"?**
Three id_token tests that duplicated code-exchange tests were removed, and their extra assertions
(`role == researcher`, the linked `user_id`) were folded into the surviving code-exchange tests.
Three tests that covered behaviour no code-exchange test had were moved onto the code-exchange
endpoint rather than dropped.

**Q6. What is still open?**
Historical docs still name `/auth/google/exchange`: `docs/AUDIT_MOCKS_STUBS_TODOS.md:151`,
`docs/architecture/SYNTH_VEDA_PHASE_PLAN.md:210` and the July auth spec/plan under
`docs/superpowers/`. Left as written, because they are records of earlier states. The Day 17 docs
pass will mark them superseded.

---

## QNA-004 — 2026-10-15 — `/models/status` built from the registry; malformed registry files reported (B1, B13; tracker t-1016-1)

**Commit:** `38e6f4e` on `sprint/d3-models-status`, merged into `LATEST_USHNIK` as `60a86ed`, plus
the follow-up commit carrying this entry (absolute `data_root` replaced by `data_root_found`).

**Q1. Mechanism: what does the endpoint do now?**
`services/api/app/models/router.py` loads `models/registry/*.json` and, for each of the six routes,
picks the entry the worker would pick. It copies `best_available` from
`services/worker/app/inference/registry.py`: production > staging > experimental, newest
`created_at` wins, and only non-retired entries with an `artifact_uri` count. It resolves `data:`
paths the way the worker does (`$SYNTHVEDA_DATA_ROOT`, then walk up to `synthveda-data/`, then
`/data`). Per route it returns a status: `ready` (backbone and head on disk), `missing_artifacts`,
`unverified` (backbone is a Hub id) or `no_model`. It also returns the inference mode the worker
would use and the registry metrics, passed through unchanged. Before this, the endpoint returned a
hardcoded "unavailable" for every route.

**Q2. Rationale: why not report "loaded"?**
The API is a separate process and the worker publishes no state (no Redis heartbeat was found).
Saying "loaded" would be a claim nothing measures. The response says `worker_state:
"not_observable"` instead, and explains what `ready` does and does not mean. The resolution logic
is duplicated rather than shared, because the API and worker are separate images with no common
package. The module docstring says to keep the two in step.

**Q3. Blast radius: what breaks if this is wrong?**
- A wrong status shows on an informational endpoint. No inference path reads it, and the frontend
  does not call `/models/status`: `ModelStatus.jsx` reads `/models/registry`, whose `models`/`count`
  keys are unchanged.
- B13: a malformed registry file (bad JSON, not an object, or missing `model_id`/`route`/
  `base_model`) is now logged and listed under `errors` on both endpoints, instead of silently
  dropped.
- **Integrity gap found:** if `head.pt` is missing, `services/worker/app/inference/heads.py`
  `get_head` builds a randomly initialised head and still labels results `inference_mode: "model"`.
  The status endpoint flags this case (`missing_artifacts` + warning). The worker fix is scheduled
  with the Day 4 loud-failures task.
- In `infra/docker/docker-compose.yml` neither container mounts `synthveda-data`, so under compose
  the endpoint would honestly report `missing_artifacts`.

**Q4. Verification: what proves it?**
- `tests/test_models_status.py`: 7 tests, covering missing backbone/head, no entry, priority
  order, and malformed files on both endpoints. Full API suite on the merged tree: **274 passed**.
  Contract test: 38 passed.
- Live on this machine (`curl localhost:8000/models/status`): all six routes `ready` /
  `inference_mode: model`, `errors: []`, `data_root_found: true`.

**Q5. Defence: "the endpoint says ready, but are the models any good?"**
`ready` is about whether the artifacts exist. Accuracy is the registry metrics, passed through as
recorded: fish acc 0.998 / macro-F1 0.8328, plant 0.9703 / 0.9422, bacteria 0.842 / 0.8529,
animal 0.9471 / 0.8542, human 1.0 / 1.0, misc 0.936 / 0.935. These are per-route head metrics on
correctly routed input. End to end, the heuristic router is right for 24.1% of held-out sequences
(QNA-001), so these numbers do not describe system accuracy.

**Q6. What is still open?**
`ready` cannot see whether torch is installed in the worker, or whether the worker's data root
matches the API's. A worker heartbeat would close that. It is not scheduled; candidate for Day 17
hardening.

---

## QNA-005 — 2026-10-15 — Upload metadata contract and per-result `context` block (F5, F6, F7; tracker t-1018-1, t-1018-2)

**Commit:** `3abbd1c` on `sprint/d5-metadata-backend`, merged into `LATEST_USHNIK` as `6808ee0`.

**Q1. Mechanism: what changed?**
`POST /uploads` (`services/api/app/uploads/router.py`) accepts six new optional form fields:
`collected_at` (ISO datetime; rejected if more than 1 day in the future), `methodology`,
`negative_control_included` (bool, omitted when not recorded), `collector`,
`dissolved_oxygen_mg_l` (≥ 0) and `ph` (0–14). It also adds range checks to existing fields
(lat −90..90 and long −180..180, sent together; depth ≥ 0). The new
`services/api/app/uploads/context.py` computes a `context` block every time a result is read. It
holds the `provided`/`missing` field lists, `negative_control` (`included` / `not_included` /
`not_recorded`), `partner_report.available` (needs `collected_at` + lat + long), `flags` and an
`accuracy_note`. It is returned on `GET /reports/{id}`, `/reports/{id}/summary`,
`/reports/{id}/export/json` and `GET /analysis/{id}`. `report.metadata` now carries all 14 fields.

**Q2. Rationale: why compute context at read time instead of storing it on the result?**
Existing analyses get it with no backfill, and it cannot drift from the upload document it
describes. The reasoning is in `docs/decisions.md` (2026-10-15). One list,
`OPTIONAL_METADATA_FIELDS` in `services/api/app/models/upload.py`, is the source of truth, and
tests check that the POST parameters, `UploadDoc` and `SampleMetadata` match it. The duplicate
`UploadMetadataForm` was deleted. The partner report is **flagged, not refused**: partner pages
render the same `GET /reports/{id}` as researchers, so refusing it would break the researcher view.
Day 13's `/partner/summary` must refuse on `context.partner_report.available`.

**Q3. Blast radius: what breaks if this is wrong?**
- Upload documents gain 6 nullable fields. There is no index, migration or Supabase change.
- An empty string `""` sent for a number or date field now returns 422. That was already true for
  `depth_meters`, and the frontend must omit empty fields.
- `GET /uploads/{id}` returns 403 to curators, so FieldLog must read `report.metadata`, not
  `getUpload`.
- `report.metadata.created_at` is still the analysis time. The collection date is `collected_at`.

**Q4. Verification: what proves it?**
`services/api/tests/test_upload_metadata.py` adds 40 tests: field validation, context shape,
negative-control states, partner-report availability, and that the field list stays in sync. API
suite on the merged tree: **314 passed**. Worker suite: 142 passed, unchanged; no worker code was
touched.

**Q5. Defence: "your accuracy note says missing metadata reduces accuracy — measured how?"**
It is not measured. None of these fields feeds inference today. The wording follows the owner's
Q2 decision (`docs/decisions.md`, 2026-10-14): every result states what was and was not provided.
It must not be cited as a measured effect in the paper. If Day 13's environmental context is later
used as a model input, re-word it from a measurement.

**Q6. What is still open?**
The frontend half (t-1018-3): Upload sends the fields, FieldLog drops its hardcoded
"Metabarcoding / Included / M. Fernandes / 12 Aug 2026", and results render the context.
`docs/flow.md` has not been updated since 2026-09-03 (Day 17 docs pass).

---

## QNA-006 — 2026-10-15 — One named novelty threshold per service, exposed on `/health` (B14; tracker t-1017-2)

**Commit:** `a388fff` on `sprint/d4-novelty-threshold`, merged into `LATEST_USHNIK` as `fcc879f`.

**Q1. Mechanism: what changed?**
`DEFAULT_NOVELTY_THRESHOLD = 0.45` and a `novelty_threshold` settings field (bounded 0 < x < 1,
overridable with the `NOVELTY_THRESHOLD` env var) now live in `services/api/app/config.py` and
`services/worker/app/config.py`. Each module exports `NOVELTY_THRESHOLD`. Every former literal
imports it: `worker/app/job_runner.py` (4 sites), `api/app/reports/router.py` (2),
`api/app/abyss/analysis.py` (2), `api/app/reviews/curation.py` (2) and `api/app/reports/builder.py`
(its private `_NOVELTY_THRESHOLD` was removed). One site beyond the audited 10 was also changed:
the low/medium level boundary in `worker/app/novelty/scorer.py:53-54`. `GET /health` now returns
`novelty_threshold` (`api/app/main.py:88`).

**Q2. Rationale: why one constant per service and not a shared module?**
The API and worker are separate images with no common package. A test pins the two defaults
together instead: `api/tests/test_novelty_threshold.py` reads the worker's `config.py` source and
compares the values. Both read the same root `.env` under compose, so one override moves both.
Changing the scorer boundary keeps "flagged as possible novelty" and "level ≥ medium" identical
even when the value is overridden.

**Q3. Blast radius: what breaks if this is wrong?**
A mismatch between the services would make the worker create review items at a different score
than the reports flag. The equality test guards that. The value is read at import, so an override
needs a restart. Four other 0.45s are deliberately untouched because they are not the novelty
cutoff: the GC band in `worker/app/model_router/router.py:219`, `gc_mean` in `reference.py:55`, a
signal value in `novelty/signals.py:52`, and `route_confidence` in the Abyss fallback.

**Q4. Verification: what proves it?**
16 new tests: equality, env override, out-of-range rejection, `/health` field, a boundary test
(a review is created at exactly the threshold and not just below it), and a source scan in each
service that fails on a bare 0.45 next to novelty/score logic. The scan includes a self-check
that it still catches the old literals. Merged tree: API **324 passed**, worker **148 passed**.

**Q5. Defence: "is 0.45 a calibrated threshold?"**
No. It is the value the code already used, now named in one place. Calibration is the Day 11 task
(B5: centroid distance replaces the `typical_norm` proxy, then recalibrate). Nothing in the paper
should present 0.45 as tuned.

**Q6. What is still open?**
The frontend still has to read `/health.novelty_threshold` (t-1017-4, in progress).

---

## QNA-007 — 2026-10-15 — Frontend reads the threshold from the API; targeted report calls; placeholder removed (U1, U2, U3, M5; tracker t-1017-4)

**Commit:** `902a029` on `sprint/d4-frontend-novelty`, merged into `LATEST_USHNIK` as `1efe046`;
follow-up `3a54623` (ReviewQueue decision values, found during this task).

**Q1. Mechanism: what changed?**
The new `web_frontend/src/lib/noveltyThreshold.js` hook reads `novelty_threshold` from `/health`
(QNA-006) and returns `null` when it is absent. NoveltyDNA, AnalysisResults and Academia use it,
so no novelty 0.45 is left in `src/`. NoveltyDNA now loads `/reports/{id}/summary`, `/novelty` and
`/contamination` in parallel instead of the full report. Its contamination colouring comes from
the server's contamination list instead of a browser-side `>= 0.5`. AbyssSetup re-reads one
expedition through `getExpedition`. ResearcherMode redirects unknown sections to `novelty-dna`,
and `PlaceholderScreen.jsx` was deleted. The `getAnalysis` and `getReview` helpers were deleted,
because no page needs them.

**Q2. Rationale: why delete `getAnalysis`/`getReview` instead of using them (U1, U3)?**
`GET /analysis/{id}` returns the raw stored result. Every page that shows an analysis needs the
assembled report. The review queue already returns full reviews, and triage/decision change state
so the queue reloads anyway. An unused helper is a false signal that something calls the
endpoint. The endpoints stay on the API.

**Q3. Blast radius: what breaks if this is wrong?**
If `/health` lacks the field, the pages say "threshold unavailable" and the slider starts at 0.
That was checked by stripping the field in the browser. While verifying, the agent found that
**ReviewQueue sent review state names (`accepted`/`rejected`/`duplicate`) as decisions**, which
the `ReviewDecision` enum (`services/api/app/models/review.py:19`: `accept`/`reject`/
`mark_duplicate`) rejects with 422. Every curator decision from the UI was failing. It is fixed in
`3a54623`. Not exercised in the browser: there is no review in a decidable state in dev data.

**Q4. Verification: what proves it?**
`npm run build` is green. Contract test: 36 passed (38 − 2 deleted helpers). API suite on the
merged tree: 322 passed. Browser check on `ana_464b4220a9774415` as a researcher: NoveltyDNA made
no full-report call and showed "45%" with 4/4 candidates; AnalysisResults showed "≥45%"; Academia
showed "≥ 0.45". With the field stripped, all three said "unavailable". `/researcher-mode/bogus`
and `/researcher-mode` landed on `novelty-dna` with `analysis_id` kept.

**Q5. Defence: "why does the slider minimum equal the threshold?"**
The server only returns rows at or above `min_score`, which defaults to the threshold. A lower
slider minimum would imply rows the API never sent.

**Q6. What is still open?**
- **Abyss activation deadlock:** the backend refuses activation until a licence is issued, but the
  UI shows the licence button only for an already-active expedition. This goes to Day 16
  (t-1029-1, AbyssSetup).
- ESLint reports a pre-existing fast-refresh error at `main.jsx:31`.
- The AbyssSetup refresh path was not exercised: the dev user has no expeditions.

---

## QNA-008 — 2026-10-18 — Upload sends the metadata fields; FieldLog and NegativeControlFlag render real values; results show the API's provided/missing context (F5, F6, F7; tracker t-1018-3)

**Commit:** `c5e988f` (feature) and `300d5a8` (noValidate fix) on `sprint/d5-metadata-frontend`, with `ec47d59` merging `LATEST_USHNIK` (at `0c1a9b6`) into the branch. Merged into `LATEST_USHNIK` as `019dcff`. This is the frontend half of QNA-005 (backend `3abbd1c`).

**Q1. Mechanism: what does the frontend now do, step by step?**
- **Upload** (`web_frontend/src/pages/Upload.jsx`): `buildMetadata` (line 135) turns the form state into `{ fields, errors }`, using the API's field names from `OPTIONAL_METADATA_FIELDS`.
  - Empty inputs are left out, never sent as `""`. The API returns 422 for `""` in a number or date field (QNA-005 Q3).
  - Date and time become one `collected_at` value with the browser's UTC offset (line 173), e.g. `2026-10-16T09:15:00+05:30`. A date with no time is recorded as 00:00 local, and the form says so.
  - The "lat, long" text is split and sent only as a pair (line 160).
  - The negative control is a three-way choice: Included / Not included / Not recorded (line 61). It sends `negative_control_included=true|false`, or leaves the field out when "Not recorded" (line 177).
  - Range checks match `services/api/app/uploads/router.py:36-49` and show inline. Line 299 appends only the fields that were built. The form uses `noValidate` (line 385); see Q4.
- **Results** (`pages/AnalysisResults.jsx`): `SampleContextPanel` (line 173, rendered at line 609) shows `report.context` exactly as the API sends it:
  - the `provided` and `missing` lists, with the API's `labels`;
  - `partner_report.available` and `missing_required`;
  - `flags` as pills, with the full message on hover;
  - the `accuracy_note`.

  Values for the provided fields come from `report.metadata` through `lib/sampleMetadata.js:44`. The header link reads "Sample context: N of 14 optional fields provided · Partner report available/not available", using the API's list lengths.
- **NegativeControlFlag** (`components/shared/NegativeControlFlag.jsx:34-53`) accepts the API's three-state value or the raw boolean: `true` → included, `false` → not included, `null` → not recorded, `undefined` → pending (still loading). Both warning states show the API's `no_negative_control` message (`AnalysisResults.jsx:302-303, 413`).
- **FieldLog** (`pages/researcher/FieldLog.jsx:256-270`) reads all 12 Run Context rows from `report.metadata`. It no longer calls `getUpload`, and the hardcoded mock rows are gone ("12 Aug 2026 · 06:40 IST", "Metabarcoding", "Included", "M. Fernandes"). A `null` value shows "Not recorded".

**Q2. Rationale: why render the API's context instead of working out provided/missing in the browser?**
QNA-005 Q2 makes `OPTIONAL_METADATA_FIELDS` the single source of truth. `build_metadata_context` (`services/api/app/uploads/context.py:67`) builds the block at read time. If the browser recomputed it, the field list would exist in two places, and the page could disagree with the JSON export a partner downloads. The browser only formats values and never decides what counts as "provided".

The browser does map the raw boolean to a state in one place: `ncState` uses it only if a report arrives without `context`. The API always returns `context` on `GET /reports/{id}`, so in practice the API value is used. The fallback means the flag still shows a warning rather than a wrong "pending".

FieldLog reads `report.metadata` instead of `GET /uploads/{id}` because curators get a 403 on the upload endpoint (QNA-005 Q3).

The offset is attached to `collected_at` because MongoDB stores naive UTC. A plain local time would be read as UTC and come back shifted. `lib/sampleMetadata.js:12` treats a stored value with no offset as UTC when displaying it.

**Q3. Blast radius: what breaks if this is wrong?**
- **Field-name mismatch.** FastAPI silently ignores unknown form fields, so a typo would drop the value without any error. The browser e2e run in Q4 shows every typed value coming back under the API's names, which rules this out for the fields tested.
- **Wrong offset.** The stored collection time would be off by the browser's UTC offset. Q4 shows 06:40+05:30 stored as `01:10:00` UTC and displayed again as 06:40 GMT+5:30.
- **`NegativeControlFlag` props changed** from `included` to `state`. The only caller is `AnalysisResults.jsx:413`; a grep of `web_frontend/src` finds no other use.
- **Merge.** `LATEST_USHNIK`'s threshold-from-/health change (QNA-007) auto-merged into `AnalysisResults.jsx`. `useNoveltyThreshold()` at line 247 and the threshold text both survive alongside the context panel.
- **Not changed:** Supabase, API code, worker code.

**Q4. Verification: what proves it?**
- **Build:** `npm run build` in `web_frontend` → `✓ 163 modules transformed. ✓ built` after the merge and after the final commit. The >500 kB chunk-size warning was already there.
- **Lint:** `npx eslint` on the five touched files reported nothing.
- **API tests:** `services/api/.venv/bin/python -m pytest -q` → **325 passed**. `tests/test_api_contract.py` alone → **36 passed**, so every `lib/api.js` path is still a real route.
- **Auth for the e2e runs:** there is no password login (Google, Supabase or admin-key OAuth only). I minted a researcher JWT for synthetic user `e2e-t1018-3` with the project's `app.auth.jwt.create_access_token`, as `tests/conftest.py` does. All runs went against the live API on :8000 and worker.
- **curl:** `POST /uploads` with 12 fields, `negative_control_included=false`, `source_type` and `temperature_celsius` left out → `upl_548aa1c761234023` → job `job_16a4d77ea7e6445c` → `ana_c24fe3c3e0a74218`.
  - `GET /reports/{id}`, `/summary`, `/export/json` and `GET /analysis/{id}` all returned 200 with the same `context.provided` (12 fields).
  - `missing` was `["source_type","temperature_celsius"]`, `negative_control` was `"not_included"`, and `partner_report.available` was `true`.
  - The one flag was `no_negative_control` with "No negative control, contamination not ruled out."
  - `metadata.collected_at` came back as `"2026-10-17T01:10:00"` (sent as `06:40:00+05:30`).
- **Browser:** this worktree's Vite on :3000 (CORS allows `localhost:3000` and `localhost:5173` only, and rejects :5174), in Playwright, timezone Asia/Calcutta. I filled the real Upload form with: location, date 2026-10-16, time 09:15, "12.5, -45.25", temperature 4.5, pH 7.9, methodology qPCR, collector "Browser tester", negative control Included.
  - The `POST /uploads` response (`upl_05c2a8d377994289`) echoed `collected_at "2026-10-16T09:15:00+05:30"`, `latitude 12.5`, `longitude -45.25`, `temperature_celsius 4.5`, `ph 7.9`, `methodology "qPCR"`, `negative_control_included true`, `collector "Browser tester"`. All untouched fields were `null`.
  - Results `ana_c7ccae609f8c4e1c` showed "Negative control: Included", "PROVIDED · 9 of 14", values such as "16 Oct 2026 · 09:15 GMT+5:30" and "45.2500° W", "MISSING · 5 of 14" (Depth, Source type, Habitat, Salinity, Dissolved oxygen) and "PARTNER REPORT Available".
  - FieldLog for the same analysis showed the same values, with "Not recorded" for depth, habitat/source, salinity and dissolved O₂.
- **Browser, other states:**
  - A file-only upload (`ana_4e6da59238a943f6`) showed the pill "Negative control not recorded, contamination not ruled out.", "PROVIDED · 0 of 14", "Not available · Needs collection date/time, latitude, longitude", and flag pills "Partner report unavailable" and "Contamination not ruled out".
  - The curl analysis showed the pill "No negative control, contamination not ruled out." So true, false and null were each seen rendered.
- **Bug found in the browser and fixed in `300d5a8`.** With pH 15, "95, 10" and depth −3, native validation (`max=14`) stopped the submit with a browser tooltip before `buildMetadata` ran, so the lat/long error never appeared. After `noValidate`, all three inline errors render, plus "Some metadata values are out of range…", and no `POST /uploads` was sent.
- **Left behind:** the e2e runs left three uploads and analyses for user `e2e-t1018-3` in the dev database.

**Q5. Defence: "the subtitle used to say metadata improves classification accuracy. Why did you change it?"**
None of these fields feeds inference (QNA-005 Q5), so that claim was never measured. The subtitle now says only what the code enforces: "Optional — a partner report needs the collection date and coordinates" (Q2 decision). The results page passes through the API's `accuracy_note`, which says missing context "can reduce accuracy". That wording comes from the owner's decision, not from a measurement, and must not be cited as a measured effect.

**Q6. What is still open?**
- No frontend unit tests: `web_frontend` has no test runner (no vitest or jest in `package.json`). `buildMetadata` and `sampleMetadata.js` are covered only by the manual browser run above.
- FieldLog still shows two labelled mock previews with no backend: Edit history (`MOCK_NOTE`) and Attachments (`MOCK_FILES`, which still contains "M. Fernandes"). They are tagged MOCK and are out of scope for t-1018-3.
- FieldLog does not show the provided/missing summary. It shows values only, and Results is where the context block lives.
- Day 13's `/partner/summary` must still refuse on `context.partner_report.available` (QNA-005 Q2).

---

## QNA-009 — 2026-10-18 — Upload storage abstraction (local + S3-compatible), MinIO in compose, worker reads through it (B7; tracker t-1019-2)

**Commit:** `10dca60` (storage module, route, worker, compose, tests) and `12eb69b` (s3 temp copy keeps
the stored name; docs) on `sprint/d6-object-storage`, with `LATEST_USHNIK` merged in as `9782f59` and
`45222bc`. Merged into `LATEST_USHNIK` as `05d0fb1`.

**Q1. Mechanism: what happens to an uploaded file now, step by step?**
`POST /uploads` builds the backend from settings (`services/api/app/uploads/router.py:119`,
`storage_from_settings`, `services/api/app/storage.py:297`). It makes a key `<upload_id>_<filename>`
with directories and unsafe characters stripped and the extension kept (`storage.py:80`). It writes the
bytes in the threadpool, because boto3 blocks (`router.py:122`). `put()` hashes and counts the bytes as
they stream. `LocalStorage` writes a temp file and `os.replace`s it into place, so a reader never sees
half a file (`storage.py:157`). `S3Storage` calls `upload_fileobj`, which goes multipart above 8 MiB
(`storage.py:182`). The doc then records `storage_uri` (`local://<key>` or `s3://<bucket>/<key>`),
`storage_key` and `checksum_sha256` (`router.py:129`, `models/upload.py:49-51`). New docs leave
`file_path` as `None`. If the write fails, the route returns 503 and no doc is inserted (`router.py:126`).
On the worker side, `_stage_parse` (`services/worker/app/job_runner.py:74`) calls
`local_copy_for_upload(upload, settings)` (`storage.py:342`) in an executor and parses the path it
yields (`job_runner.py:94`). A `local://` key is read in place under `UPLOAD_STORAGE_DIR`. An `s3://`
object is streamed into a temp directory under the key's basename and removed afterwards
(`storage.py:383-396`). A pre-B7 doc with only `file_path` is read from that path (`storage.py:360`).
When the doc has a sha256, the bytes are checked against it before parsing (`storage.py:332`).

**Q2. Rationale: why a duplicated module instead of a shared package, and why URIs instead of paths?**
The API and the worker are separate images. Each Dockerfile copies only its own `app/`, and neither
installs a shared package. The B14 threshold faced the same constraint and solved it the same way
(QNA-006). Sharing the module would mean changing both build contexts, both Dockerfiles and both venv
install paths for one ~400-line module. Instead the worker holds a byte-identical copy.
`services/api/tests/test_storage.py:101` fails the suite if the two copies differ, and `:124` fails it if
`WorkerSettings` and the API `Settings` disagree on any storage field or default. The cost is that
someone has to remember to copy the file after editing it, and that test is the reminder.
URIs: the old `file_path` was an absolute path on the API's disk. It only worked because compose
mounted `uploads_data` at the same `/app/uploads` path in both containers, and `GET /uploads/{id}`
returned it to clients. A URI names the backend, so the worker reads from wherever the API wrote,
whatever the worker's own `STORAGE_BACKEND` is (`storage_for_uri`, `storage.py:307`; test
`services/worker/tests/test_upload_storage.py:86`). `local://` keys are relative, so the two services'
mount points no longer have to match. Rejected alternative: keep `file_path` and add an `s3_key` field
next to it. The worker would then have to guess which field wins, and a third backend would mean a
third field.

**Q3. Blast radius: what breaks if this is wrong (legacy uploads, a misconfigured worker)?**
- *Legacy uploads.* Docs written before B7 have no `storage_uri`. They are read through `file_path`
  exactly as before (`storage.py:360`; test `test_upload_storage.py:94`). If that path is gone, the job
  fails with `legacy file_path ... not found` and is never stubbed. These docs have no checksum, so
  nothing is verified for them.
- *Worker with the wrong `UPLOAD_STORAGE_DIR`.* `local://` reads fail with a `StorageError` naming the
  URI, the resolved directory and the setting (`LocalStorage.missing`, `storage.py:163`; test
  `test_upload_storage.py:106`). Compose now sets `UPLOAD_STORAGE_DIR=/app/uploads` on the worker too.
  The default `uploads` resolves to the same path in the image, because the WORKDIR is `/app`.
- *Worker with the wrong or missing S3 settings.* The URI fixes the bucket but not the endpoint or the
  credentials, which come from the worker's own `OBJECT_STORAGE_*`. A worker with a blank
  `OBJECT_STORAGE_URL` would send the request to AWS for a bucket that exists only in MinIO. The job
  then fails with botocore's error (`NoCredentialsError`, AccessDenied or NoSuchBucket), passed through
  as raised. Only 404s are turned into `StorageError("... not found")` (`S3Storage.open`, `storage.py:241-250`). So the
  job fails loudly but the message is less specific than the local case. Not fixed in this change.
- *A bad `STORAGE_BACKEND` value* (for example `gcs`) fails when settings load (`Literal["local","s3"]`,
  `services/api/app/config.py:60`, `services/worker/app/config.py:35`), not on the first upload.
- *Behaviour change for clients.* New upload responses carry `storage_uri`/`storage_key`/
  `checksum_sha256`, and `file_path` is `null`. Nothing in `web_frontend/src` reads any of these
  fields (grep found no hits).
- *Per-sequence `source_file`.* The first end-to-end run showed it holding the worker's temp name
  (`synthveda-upload-dagclyhd.fasta`). `12eb69b` fixed that, and it is now `<upload_id>_<filename>` for
  both backends (test `test_upload_storage.py:75`).

**Q4. Verification: what was actually run and what was seen?**
- Suites at `45222bc`: API `362 passed, 1 warning` (37 of them in `tests/test_storage.py`), worker
  `168 passed` (8 in `tests/test_upload_storage.py`). Commands: `.venv/bin/python -m pytest -q` in each
  service, using the main checkout's venvs. S3 is faked with moto 5.0.28 (`mock_aws`). That covers
  multipart above 8 MiB (`test_storage.py:243`), checksum mismatch on both backends (`:323`), the route
  writing to the bucket (`:392`) and the 503 path (`:407`). `bandit -ll` on the changed modules was clean.
- `docker compose -f infra/docker/docker-compose.yml config` exits 0 (run with a temporary empty `.env`
  because the file is gitignored). api and worker resolve `STORAGE_BACKEND: s3`,
  `OBJECT_STORAGE_URL: http://minio:9000` and `depends_on minio-init: service_completed_successfully`.
- Bucket step: the `minio-init` command (`mc alias set ... && mc mb --ignore-existing
  synthveda/synthveda-uploads`) was run twice against the already-running `synthveda-minio`, with
  `--network container:synthveda-minio` and `localhost` in place of the `minio` hostname. Both runs
  exited 0, which shows the step is idempotent. Before that, the server had no buckets at all
  (`list_buckets` → `[]`).
- End to end with `STORAGE_BACKEND=s3` against `http://localhost:9000`: the worktree API ran on
  `127.0.0.1:8017` and the worktree worker ran alongside it. Both used Mongo DB `synthveda_e2e_b7` and
  Redis db 7, so the main stack was not touched. A 124-byte, 2-record FASTA with sha256 `84a1f90d...0968`
  was uploaded → `upl_d762e62e26894ce3`, `storage_uri
  s3://synthveda-uploads/upl_d762e62e26894ce3_b7-e2e.fasta`, `file_path null`, same checksum.
  `mc ls` showed `124B STANDARD upl_d762e62e26894ce3_b7-e2e.fasta`, and `mc cat | sha256sum` printed
  `84a1f90d...0968`. A boto3 `list_objects_v2` showed the same key with size 124. Nothing was written
  to the local upload dir. `POST /analysis/jobs` → `job_c814242e10944211 completed` →
  `ana_3009896ee1744e13`, and the worker logged `parsed 2 sequences via Python parser (b7-e2e.fasta)`.
  After `12eb69b` a second run gave `job_6230d4d848034bbc completed`, with `source_file` equal to
  `upl_1e780729547140c0_b7-e2e.fasta` for both sequences and no `/tmp/synthveda-upload-*` left behind.
  Negative case: one object was deleted from MinIO after its upload, and the job then failed with
  `s3://synthveda-uploads/upl_230c923661e8462d_b7-e2e.fasta not found`.
- Not verified: `docker compose up` of the full stack, because the main checkout's containers already
  hold the names and ports. The compose wiring is therefore checked only by `config` and by the init
  command run on its own.

**Q5. Defence: "Two copies of the same file is a maintenance smell. Why not one package?"**
It is a smell, and the test exists to contain it. The copies cannot drift without the API suite failing
(`test_storage.py:101`), and CI already runs that suite (`docs/rules.md`, ci.yml). A shared package is
the better end state once there is more than one shared module: B14's threshold and this module are
both candidates. At that point the build-context change pays for itself, and it should go into
decisions.md as its own decision. Follow-up: "Then why not just mount one volume and keep paths?"
Because that ties the worker to the API's filesystem layout and to a single host. That rules out the
Cloud Run deployment in `infra/deployment/`, where the API has no shared disk. It also means a
client-visible absolute path. The URI separates "where the bytes are" from "how this process reaches
them". The checksum then proves the worker parsed exactly the bytes the user uploaded, which is the
claim a report makes.

---

## QNA-010 — 2026-10-18 — Learned k-mer router replaces the heuristic as the first routing stage (B19; tracker t-1017-1)

**Commit:** `91264ec` on `sprint/d4-learned-router`. It sits on top of WIP commit `937ac2f` and the merge
`deb7c46`, which brings in `LATEST_USHNIK` at `0c1a9b6`. Merged into `LATEST_USHNIK` as `4d02a2b`
(conflicts only in `.env.example` and the worker requirements files; both sides kept). The
artifact lives outside git, at `$SYNTHVEDA_DATA_ROOT/checkpoints/router/v1/router.npz`, SHA-256
`f335be9afab5707b9f827172cf00457393a18f73fe9c050d73ed33fad1d93a8c`, 1,466,743 bytes.

**Q1. Mechanism: what does the router do now, step by step?**
`route_sequence()` (`services/worker/app/model_router/router.py:41`) runs these steps in order:
1. The unchanged low-quality gate (`router.py:52`).
2. `get_learned_router()` (`router.py:55`, `learned.py:165`). It loads the registry entry with
   `"route": "router"` through `best_available` (`learned.py:150`), which is now
   `models/registry/kmer_router_v1.json`. It verifies the `.npz` SHA-256 against the entry's
   checksum (`learned.py:99-113`), opens the file with `allow_pickle=False` (`learned.py:116`), and
   caches the model, or the failure reason, once per process.
3. `predict_proba` (`learned.py:75`) counts the sequence's exact 8-mers. Windows that contain
   non-ACGT characters are skipped (`kmer.py:34-58`). The counts are L2-normalised, scored as
   `x·W + b` (LinearSVC weights, 65,536 × 6), divided by the dev-fitted temperature T = 0.4471
   (`learned.py:82`) and passed through a softmax.
4. `_learned_result` (`router.py:209`) keeps the existing contract: `route_confidence` is the top
   probability, and the 0.70/0.40 tier cut-offs are unchanged. It adds `router_method="learned"`,
   `router_version`, and `route_probabilities` with `probabilities_calibrated=True`.

When there is no model, the checksum is wrong, numpy is missing, a prediction raises, or the
sequence has no valid k-mer, the heuristic routes the sequence instead. The result then carries
`router_method="heuristic_fallback"`, a `router_fallback_reason` and the reason code
`router_heuristic_fallback` (`router.py:57-74`). `SYNTHVEDA_ROUTER=heuristic` is the kill switch
(`learned.py:36,167`). It yields `router_method="heuristic"` and no fallback code.
`job_runner._stage_route` writes all five fields onto each result and prints a WARNING line
whenever any sequence fell back (`job_runner.py:168-183`). The API `SequenceResult` declares them
next to B12's `inference_mode`/`stub_reason` (`services/api/app/models/analysis.py:43-54`). That
file was the only merge conflict, and both sides were kept.

**Q2. Rationale: why a linear model on k-mer counts, and not DNABERT embeddings, a GBM or a CNN?**
- The router runs on every sequence before any model, and on the CPU-only worker image.
  Inference needs only numpy and costs **0.144 ms per sequence**, against 7.403 ms for the
  heuristic on the same rows (`eval_report.json`, `protocol_qna001.*.seconds_per_sequence`).
  A transformer embedding would put a GPU-sized forward pass in front of every route model.
- The features are exact (4^8 = 65,536 columns), so nothing is hashed. One function does the
  featurisation for both training and inference (`kmer.py`), so the two cannot drift apart.
  The artifact is weights plus a JSON config, with no pickle and no sklearn at runtime.
- The dev sweep shows where the remaining gains are. Going from k=4 to k=8 moves dev balanced
  accuracy from 0.7579 to 0.8722. LinearSVC versus logistic regression at the same k differs by
  ≤0.004 (k=8: 0.8722 vs 0.8686). Model class is not the bottleneck; feature length is.
  Everything was selected on dev only, by balanced accuracy, over k ∈ {4..8} ×
  {forward, canonical} × {svm C=0.1, svm C=1.0, logreg C=10} (30 fits). The winner was
  **k=8, forward strand, LinearSVC C=1.0**: dev acc 0.8985, macro-F1 0.8561, balanced 0.8722.
  k=8 is the edge of the grid, so a larger k might score higher. That is untested.

**Q3. Blast radius: what breaks if this is wrong?**
- Every downstream stage trusts `route`. A wrong route sends the sequence to the wrong DNABERT head,
  so a router error quietly lowers end-to-end accuracy. That was already true of the heuristic, at a
  much higher error rate.
- **Strand: the deployed v1 is not strand-invariant.** On the reverse complement of every
  non-low-quality test row, accuracy is **0.1655** (macro-F1 0.1589; misc_unknown 0.9534,
  bacteria 0.001). The forward-only features won on dev by 0.0064 balanced accuracy over
  canonical (0.8722 vs 0.8658). The processed CSVs appear to be in one orientation, but uploaded
  FASTQ reads (for example paired-end R2) may not be. Reverse-strand reads will be routed badly,
  and the result will still say `router_method="learned"` with a confident probability.
- The calibration fixes the mean, not every bin. On the 1,800 protocol rows, tier accuracy is
  high 0.9175 (n=1,515), medium 0.5933 (n=268) and low 0.4118 (n=17).
- Docker: the worker image now installs numpy (`requirements.txt`). But `docker-compose.yml`
  mounts `models/` and not the data root, so in compose the artifact is missing. Every result
  will then say `heuristic_fallback / artifact_missing`. It is visible, not silent.
- Abyss mode in the API does not reach the worker router at all. `abyss/analysis.py` imports
  `app.model_router` while the API's own `app` package is already loaded, so it raises
  `ModuleNotFoundError` and uses GC-only routing. B12 made this visible
  (`router_error_fallback=True`). This is a pre-existing bug and B19 does not change it.
- The registry now has a 7th route value, `"router"`. `/models/status` iterates only the six
  taxonomic routes, so it is unaffected. `/models/registry` and the ModelStatus page will list
  the entry.

**Q4. Verification: what proves it, exactly?**
- Commands, from `services/worker/` with
  `SYNTHVEDA_DATA_ROOT=/home/natsu/dev/synth-veda/synthveda-data`:
  `python -m training.train_router --version v1 --sweep` (dev only, writes nothing), then
  `python -m training.train_router --version v1 --k 8 --model svm --C 1.0`. Training took
  28.0 s in total: 3.5 s featurising and 7.6 s fitting.
- Training data: 34,707 rows. These are train rows minus the `low_quality_unusable` label, minus
  exact duplicates, minus sequences that also occur in another route or in any dev/test file,
  capped at 8,000 per route. Per route: fish 3,990, plant 4,395, bacteria 8,000 (of 32,726
  eligible), animal 6,862, human 3,527, misc 7,933.
- **QNA-001 protocol.** 300 non-low-quality test rows per route (`random.Random(0).sample`,
  `train_router.py:381`) go through the full `route_sequence()` path, gate included. The learned
  router and the heuristic score the same 1,800 rows:

  | route | heuristic acc | learned acc | learned F1 |
  |---|---|---|---|
  | fish | 0.000 (0/300) | 0.830 (249/300) | 0.854 |
  | plant | 0.000 (0/300) | 0.873 (262/300) | 0.929 |
  | bacteria_pathogen | 0.830 (249/300) | 0.967 (290/300) | 0.954 |
  | animal_general | 0.013 (4/300) | 0.813 (244/300) | 0.797 |
  | human_domestic_contamination | 0.113 (34/300) | 0.850 (255/300) | 0.866 |
  | misc_unknown | 0.567 (170/300) | 0.853 (256/300) | 0.799 |
  | **overall** | **0.2539 (457/1,800)** | **0.8644 (1,556/1,800)** | macro-F1 **0.8665** (heuristic 0.1667) |

  3 of the 1,800 rows were caught by the low-quality gate and count as wrong for both routers.
  Top-2 accuracy is 0.9683. The largest confusions are fish→animal 47, animal→fish 34,
  human→misc 42, animal→misc 21 and plant→human 20. On the clean subset (1,664 rows with no copy
  in another route or split), learned scores 0.8756 and the heuristic 0.2716. The heuristic
  scores 25.4% here, not QNA-001's 24.1%. QNA-001 did not record its seed, so this is a
  different sample of 1,800 rows.
- Calibration (15-bin top-label ECE):

  | split | ECE before T | ECE after T | other |
  |---|---|---|---|
  | dev | 0.2802 | 0.0220 | NLL 0.6200 → 0.3655 |
  | test, all non-low-quality rows | 0.2825 | 0.0191 | |
  | protocol rows scored by the learned model (1,797) | 0.2692 | 0.0244 | |

- Full test set (7,705 non-low-quality rows): acc 0.8999, macro-F1 0.8553, balanced 0.8717.
  The clean subset (7,359 rows) scores 0.9077. The 346 rows that also occur in another route or
  split score 0.7341.
- Tests: worker **187 passed, 0 skipped**. The two real-artifact integration tests in
  `tests/test_learned_router.py:286`, skipped before training, now run and pass. API **325
  passed**. Both runs used the merged tree.

**Q5. Defence: "86% is inflated by leakage", and "you tuned on test".**
- Leakage audit, exact sequence match over all 82,219 rows (79,493 unique):
  - 568 unique sequences occur in more than one route. The biggest group is human+plant (386),
    then bacteria+human (140).
  - Within a route, unique train∩test overlap is fish 0, plant 23, bacteria 0, animal 131,
    human 9 and misc 47.
  - Test rows whose sequence occurs in another route's train file: plant 28, human 50, misc 28,
    bacteria 8, animal 1, fish 0.

  None of these sequences were trained on, because cross-route and train/dev/test-overlapping
  sequences are removed from training (`train_router.py:135-159`). The clean-subset numbers above
  (0.9077 on the full test set, 0.8756 on the protocol rows) are the leakage-free figures. They
  are higher than the all-rows figures, not lower.
- Test was not used for selection. k, strand mode, model and C were chosen on dev
  (`train_router.py:288-307`), and T was fitted on dev (`train_router.py:196`). Test was read once,
  in the single training run. The reverse-complement failure was found on test. Switching v1 to
  canonical features after seeing that number would be a test-informed choice, so v1 ships as
  selected and the failure is recorded here.
- One caveat on scoring cuts against the router. Route labels come from the folder, so the 40
  plant and 156 bacteria test rows labelled `possible_contamination` count as errors (0.0
  accuracy). The model sends 36/40 and 126/156 of them to `human_domestic_contamination`.
  Whether that is right is a labelling question, and it is not claimed as a win here.
- Not claimable: QNA-001's "82.4%" and this "86.4%" come from different samples and features, so
  the difference is not a measured improvement from tuning. The paper must say the router is
  trained and evaluated on the same 6-route processed corpus, with no external or
  real-upload test set.

**Q6. What is still open?**
- **Strand invariance (highest priority):** a v2 with `--canonical`. A strand-invariance
  requirement should be declared before training, and the model selected on dev against it. A
  canonical model scores both strands identically by construction. Its dev balanced accuracy
  was 0.8658.
- k > 8 was not explored, and k=8 won at the edge of the grid.
- The compose data-root mount and the Abyss import path (Q3) need separate tasks.
- Medium-tier routes (n=268, accuracy 0.59) should keep sending their top fallback model in
  parallel. Nobody has checked that the orchestrator actually does this for learned results.

**Follow-up decision (orchestrator, 2026-10-18).** v1 ships despite the reverse-strand result
(0.1655 on reverse-complemented test reads, still reported with high confidence), because on
forward reads it is 0.8644 against the heuristic's 0.2539 on the same 1,800 rows. Switching v1 to
`--canonical` now would be choosing a configuration on the test set, so v1 stays as selected on
dev. Strand invariance becomes a stated requirement for the router retrain that runs with the Day 8
head retrain (t-1021-1) on the rebuilt Day 7 splits. That retrain's selection must report
forward and reverse-complement accuracy side by side. Until then, a reverse-orientation upload
(for example paired-end R2) is routed badly by v1. This is a known, recorded defect, not a hidden one.


---

## QNA-011 — 2026-10-18 — Supplementary sequences for thin classes from NCBI E-utilities and ENA; UniVec relabelled possible_contamination (Q1; tracker t-1019-1)

**Commit:** `29cb8cf` (fetcher, `iter_supplementary`, build_dataset hook, UniVec relabel, 44 tests),
`d35ad8d` (human control-region / nuclear-rRNA queries, all NCBI fish hits, ENA fish) and `c49f887`
(drop the redundant human mito 12S/16S query) on `sprint/d6-supplementary-data`, with `LATEST_USHNIK`
merged in as `9fb0e19` and `0792f68`. Merged into `LATEST_USHNIK` as `003eae2`. `processed/` was **not** rebuilt.
That is Day 7. The data lives in `synthveda-data/raw/supplementary/` (gitignored, 22 MB).

**Q1. Mechanism: how does a fetched sequence get into the dataset, step by step?**
`training/fetch_supplementary.py` defines 10 queries in `QUERIES` (`:137`). Each query does the
following:

1. Runs an Entrez `esearch` (NCBI) or an ENA Portal `search` with a length clause.
2. Draws a seeded sample of the full hit list (`sample_candidates`, seed `20261019`).
3. Fetches the sample in batches of 200 (NCBI) or 100 (ENA).
4. Labels each record (`label_candidate`, `:383`), in one of two ways:
   - *Taxonomy-labelled* (animal and fish novelty, human known_species): the taxid is resolved with
     the local taxdump, then put through the same `lineage_to_route` (`:404`) and `assign_label`
     (`:407`) as every other source. The record is kept only if that path lands on the query's
     target independently. The query narrows the search; it never assigns the label.
   - *Provenance-labelled* (cloning vectors, PhiX174): labelled
     `human_domestic_contamination/possible_contamination`.
5. Drops accessions already held for the same class by another query (`already_gathered`, `:543`;
   check at `:567`), because ENA and NCBI mirror the same INSDC data.

Every kept record writes a manifest row with: accession, versionless accession, source, query_id,
taxid, organism, title, length, route, label, label_basis, retrieved_at, the full licence text and
sha256.

`sources.iter_supplementary` (`training/sources.py:284`) reads the manifests and FASTA back into
`Record`s:
- Taxonomy rows carry their lineage, and build_dataset re-derives route and label from it.
- Provenance rows carry a fixed route and label, which `ingest` honours
  (`build_dataset.py:77-82`); low-quality windows are dropped rather than given that label.

build_dataset calls `iter_supplementary` after UniVec (`build_dataset.py:229-233`;
`--skip-supplementary` opts out). Dedup against the existing sources is the existing one:
`write_splits` collapses identical sequences within a route before shuffling. A sequence that
carries two labels is dropped (`build_dataset.py:135-144`). UniVec now yields
`possible_contamination` (`sources.py:276`) instead of falling through to known_species.
`inject_contamination` draws from both human pools (`build_dataset.py:107`), so UniVec still reaches
plant and bacteria as injected contamination.

**Q2. What was gathered, per source and class, under what licence?** (measured; "unique" means
unique 400 bp windows or whole sequences after `chunk_long_sequence`, which is what the Collector sees)

| Source | Query | Target class | Hits | Records kept | Unique after chunking |
|---|---|---|---:|---:|---:|
| NCBI | `ncbi_animal_env_coi` | animal_general / possible_novelty | 16071 | 2000 | 1945 |
| NCBI | `ncbi_animal_env_18s` | same | 2569 | 1500 | 1291 |
| NCBI | `ncbi_animal_env_16s` | same | 229 | 225 | 146 |
| ENA | `ena_animal_env_any` | same | 72848 | 1500 | 1492 |
| | **animal novelty total** | | | **5225** | **4857** (was 17/1/4 train/dev/test) |
| NCBI | `ncbi_fish_env` | fish / possible_novelty | 3453 | 872 | 836 |
| ENA | `ena_fish_env` | same | 3189 (after accession dedup) | 4 | 4 |
| | **fish novelty total** | | | **876** | **840** (was 0/0/0) |
| NCBI | `ncbi_human_mito_control_region` | human_domestic_contamination / known_species | 132233 | 800 | 779 |
| NCBI | `ncbi_human_nuclear_rrna` | same | 358 | 358 | 138 |
| | **human known_species total** | | | **1158** | **917** (class already at 5000 cap) |
| NCBI | `ncbi_cloning_vectors` | human_domestic_contamination / possible_contamination | 30955 | 1500 | 5243 windows (of 7123) |
| NCBI | `ncbi_phix174` | same | 157 | 157 | 316 windows (of 785) |
| | **human possible_contamination total** | | | **1657** | **5559** (was 0/0/0) |

Licences, stored per row in each manifest (`fetch_supplementary.py:85`):
- **NCBI/GenBank**, including the RefSeq XR_ "PREDICTED" 18S models among the nuclear-rRNA hits: NCBI
  places no restrictions on use or redistribution, though submitters may claim IP in their own
  records. Access is under the E-utilities guidelines.
- **ENA/INSDC**: free and unrestricted under the INSDC policy, with the EMBL-EBI Terms of Use applying.

Requests sent `tool=synthveda`, no email and no API key (`:72`), spaced at least 0.40 s apart (`:75`,
under NCBI's 3 req/s), and ENA at 0.5 s. Bytes downloaded this session (2026-10-18): about 14.0 MB.
The 2026-10-15 runs downloaded 39.3 MB (`index.json`).

**Q3. Rationale: why these queries, and why were MGnify, kitome bacteria and human mito 12S/16S not used?**
- *Human queries.* processed/`human_domestic_contamination/known_species` is full (5000), so these
  queries change what the class holds rather than fill it. Measured: 1732 of its 5000 rows are
  400 bp windows. The rest are gene-length mito records, with top lengths 1141, 1542, 1558 and 954
  (cytb, COI, 16S, 12S).
- *How "new coverage" was measured.* A fetched record counts as already covered if it shares at
  least one 32-mer with an existing row: nuclear rRNA 1/358, control region 110/800. So both add
  loci the head has not seen.
- *Human mito 12S/16S was fetched and then dropped* (`c49f887`). 400 records, of which 390 already
  shared a 32-mer with existing rows, so they would have added near-duplicates rather than coverage.
  The files were deleted and the `index.json` entry removed.
- *Nuclear rRNA query excludes PDB* (`:231`, `NOT srcdb_pdb[PROP]`). 78 of 436 first-run hits were
  PDB cryo-EM ribosome chains. These are not INSDC records and have no taxid in esummary, and they
  had been rejected only by accident, as `no_taxid`.
- *MGnify was probed* (`/metagenomics/api/v1/`, 2026-10-18; 1922 aquatic studies listed). The API
  serves studies, runs, analyses, assemblies and prokaryotic MAGs. It has no endpoint that returns a
  sequence with a curated organism identification. Its OTU and contig taxonomy is its own pipeline's
  SILVA/PR2 prediction, so labelling from it would train the heads on another classifier's output.
- *Kitome genera* (Ralstonia, Bradyrhizobium) are also real environmental organisms, and no single
  record shows that it is a contaminant.
- *Lambda phage* has 7 complete genomes. `chunk_long_sequence` keeps the first 3.6 kb of each, so they
  would add a handful of near-identical windows.

**Q4. Blast radius, including leakage: what breaks if this is wrong?**
- *Near-duplicate leakage (the main risk).* write_splits removes exact duplicates only. Within each
  supplementary class, the share of unique sequences that have a near-identical partner (16-mer
  Jaccard ≥ 0.8; MinHash with 64 hashes in 16 LSH bands, so a lower bound) is:
  - animal novelty 949/4857 = **19.5%**
  - fish novelty 449/840 = **53.5%**
  - human known_species 513/917 = **55.9%** (human mtDNA haplotypes)
  - human possible_contamination 2150/5559 = **38.7%** (shared vector backbones, PhiX variants)

  A random 80/10/10 split will put many of these partners on both sides of the train/test line and
  inflate test scores for these classes. The Day 7 rebuild should split these classes by cluster (or
  by accession group), or report test scores split into near-duplicate and truly-unseen subsets, as
  was done for the exact-duplicate leak (`build_dataset.py:127-133` comment: 84.88% vs 82.41%).
- *Exact overlap with the current `processed/`* (`--check-overlap`, `overlap_report.json`): 34 train,
  3 dev and 7 test chunks out of 12173.
- *Cross-route duplicates*, which write_splits does not catch because it dedups per route. 31 fish
  novelty sequences are identical to `animal_general/likely_taxonomic_group` rows (23 train, 3 dev,
  5 test), 2 animal novelty sequences are in `misc_unknown`, and 7 vector windows are in other
  routes. The learned router (QNA-010) takes the route from the folder (`train_router.py:11`), so
  these 40 sequences become contradictory router supervision and can leak between router splits.
- *Label noise in vectors.* 3 vector windows (backbones of pAT153, pGETS109, pXtale) are identical
  to current human known_species rows. Those rows are UniVec windows under the old label. After the
  rebuild, UniVec is possible_contamination too, so these conflicts disappear. Vectors that carry
  human or other inserts would label insert windows as lab reagent. Only these 3 exact clashes were
  measured, so that risk is not quantified.
- *Fish routing gap.* 2581 of the 3453 NCBI fish hits are "Actinopterygii environmental sample". In
  NCBI, Actinopterygii is a superclass, so the lineage has no class rank, `routing.py:57` falls
  through to animal_general, and the record is rejected (`run.json` reasons). The same gap already
  places real fish in animal_general: the 31 cross-route duplicates above. The fix belongs in
  `routing.py`, and none was made.

**Q5. Verification: what proves it?**
- `cd services/worker && python -m pytest -q`: **252 passed** after merging `LATEST_USHNIK`
  (`0792f68`). `tests/test_supplementary_fetch.py` has 57 tests, among them:
  - human queries label through taxonomy, and a non-human record is rejected (`:207`)
  - superclass-only fish is rejected (`:200`)
  - manifest to FASTA to `iter_supplementary` to `ingest` round trip (`:257`)
  - UniVec is possible_contamination (`:296`)
- Dry run (ingest of the supplementary data only into an uncapped Collector, read-only against
  `processed/`; script in the session scratchpad, not committed): 0 label conflicts and 0
  cross-route sequences inside the supplementary set. Against `processed/`, 3 same-label exact
  duplicates (animal) and 3 conflicts (the UniVec rows above).
- `python -m training.fetch_supplementary --check-overlap` gives totals of 12173 unique chunks
  (34/3/7 in train/dev/test).
- `index.json` matches the files on disk: 10 queries, 30 files.

**Q6. Defence: "a query for 'environmental samples' just hands you the novelty label. Isn't that circular?"**
No. The query only shrinks the candidate pool. The label comes from `assign_label`, the same rule that
labels every BOLD, MIDORI2, SILVA and BLAST DB record (`fetch_supplementary.py:404-407`). Records that
the rule labels otherwise are rejected and counted, for example:
- `labelled:known_species`: 147 in ENA animal, 492 in ENA fish
- `routed_to:animal_general`: 2581 in NCBI fish

On rebuild, build_dataset re-derives the label from the stored lineage rather than trusting the
manifest. The honest limits:
- possible_novelty here means "INSDC submitter could not name it". That is the operational definition
  the project already uses, not proof of a new species.
- The near-duplicate rates in Q4 mean test scores on these classes after Day 7 are not trustworthy
  until the split is cluster-aware.
