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
