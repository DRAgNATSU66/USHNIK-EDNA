> **Superseded 2026-10-14 by `ROADMAP_REAL_DATA.md`** (re-verified inventory + day-wise plan). Kept as the 2026-09-03 snapshot.

# Roadmap: Current State → Fully Polished Working Tool

Snapshot date: 2026-09-03. This is the gap-closing roadmap: given where the code actually stands
today (see `docs/AUDIT_MOCKS_STUBS_TODOS.md` for the evidence), what's the shortest honest path to
a tool with no mock data, no unbuilt-but-called backends, and no undecided logic left blocking a
feature? It sits underneath `docs/architecture/SYNTH_VEDA_PHASE_PLAN.md` (the original 15-phase
rebuild plan) — that document says what the target architecture is; this one says what's left to
actually get there from the code as it exists right now.

Where a phase below corresponds to a numbered phase in the master plan, that's noted. Items are
ordered by dependency and cost/value, not by master-plan numbering — some "Phase 14" work
(taxonomy lookup, model promotion) is cheap and should happen before some "Phase 4" polish work.

Legend: 🐛 bug fix · 🔌 wiring · 🧠 model/ML · 🗑️ cleanup · ❓ decision needed

---

## Phase 0 — Decisions that unblock everything else

Nothing in Phase 3 (partner reports) or parts of Phase 2 can be honestly finished until these are
answered. They're product/scientific calls, not engineering ones — flagging them first so they're
not accidentally decided by default (e.g. "optional" metadata staying optional because no one
revisited it).

- ❓ Reference database(s) to standardize on: NCBI / SILVA / BOLD / custom blend.
- ❓ Metadata at upload: mandatory or optional? (Current mockup says optional; conflicts with the
  chain-of-custody requirement already implied by Legislative's "Cryptographic Chain of Custody"
  widget.)
- ❓ Do expert corrections (Species Correction page) feed model retraining, or are they audit-only?
  This determines whether `curation.py`'s frozen batches are the real training input or just a log.
- ❓ Negative control: required per run, or optional-but-flagged?
- ❓ Industrial's predictive/financial figures (biofouling threshold, remediation ROI): backed by a
  real trend model, or an explicitly-labeled single-point extrapolation?
- ❓ Co-occurrence network (Academia) at scale: filtering, clustering, or pagination approach,
  before building it against real data.

**Exit:** every open decision above has an owner and an answer written down (even "defer to v2,
show disabled with reason").

---

## Phase 1 — Stop the bleeding: fix broken paths, close security gaps, remove dead code

Cheapest, highest-value pass. No new features — just make what claims to exist actually work,
close silent risks that ship in on defaults, and delete what's actively confusing (dead code that
*looks* live).

**Functional bug, fix now:**

- 🐛 Reconcile the upload size limit: frontend `Upload.jsx:29` says 500MB, backend
  `config.py:50`/`.env.example:26` enforces 100MB. Either raise the backend limit or fix the
  frontend constant — right now a 200-499MB upload wastes the user's full upload time before a 413.

**Broken wiring:**

- 🐛 Fix `getReviewQueue()` in `web_frontend/src/lib/api.js:156-157` to call `GET /reviews/queue`
  instead of `GET /reviews` — Review Queue page currently 404s on load.
- 🐛 Fix `getModels()` in `web_frontend/src/lib/api.js:198` to call `GET /models/status` and/or
  `GET /models/registry` instead of `GET /models` — Model Status page currently 404s on load.
- 🗑️ Remove the dead import block in `services/api/app/abyss/analysis.py:107-109`
  (`from ..app.model_router import ...` inside a swallowed `try/except`).
- 🗑️ Delete or explicitly archive `web_frontend/src/App.jsx` (orphaned Three.js prototype that
  POSTs to a non-existent `/analyze` endpoint and fakes results on failure) — decide: is the DNA
  helix visualization worth salvaging into a real page, or is this pure scratch work?
- 🗑️ Delete or wire up `web_frontend/src/pages/stakeholders/*` and `StakeholderDashboardPage.jsx`
  (~150KB, fully unreachable, fully mocked). If any of these dashboards represent a real planned
  feature, re-scope them under Phase 3 against real data; otherwise remove.
- 🗑️ Remove the redundant `GET /analysis/{analysis_id}/report` route
  (`services/api/app/analysis/router.py:104-134`) in favor of `GET /reports/{analysis_id}`.

**Exit:** every page reachable from the router loads without a 404; `git grep` for `App.jsx` and
`pages/stakeholders` returns nothing (or a documented decision to keep them, wired to real data).

Maps to: hardening pass on master-plan Phase 12 (Frontend Rebuild) "no mock axios" done-criterion.

---

## Phase 2 — Backend reality: close the inference and training loop

This is the single biggest gap: **every classification result shown to a user today is a stub**
(`predicted_taxon=None`, `confidence=0.0`). Nothing else in the product matters if this isn't real.

1. 🧠 **Model artifact hosting.** Move the 7 registry entries off the Windows-only
   `E:\synthveda-data\checkpoints\...` paths (`models/registry/*.json`) onto Hugging Face Hub
   private repos or S3/GCS, per master-plan Phase 0's "Model Artifact Decision." Update
   `services/worker/app/inference/loader.py:188-198` (`_resolve_local`) to resolve from the new
   location. This alone unblocks real inference running in Docker/CI/any non-dev machine.
2. 🧠 Implement taxonomy lookup from label index so `predicted_taxon` is populated on the real-model
   path (`services/worker/app/inference/predictor.py:204`, tagged `# Phase 14`).
3. 🧠 Replace the embedding-isolation novelty proxy (`services/worker/app/novelty/signals.py:168-193`,
   hardcoded `typical_norm = 14.0`) with real cosine-distance-to-cluster-centre scoring.
4. 🔌 Close the retrain loop: add an admin-facing endpoint/flow that calls
   `SupabaseClient.register_model_version` / `promote_model`
   (`services/api/app/db/supabase_client.py:400,406` — implemented, currently orphaned) after a
   training batch is frozen and a new model is trained/evaluated. Right now the pipeline stops at
   "batch frozen" with a manual, out-of-repo step.
5. 🔌 Wire uploads to real object storage — `object_storage_url`/`object_storage_bucket` are already
   in `services/api/app/config.py:31-33` but unused; `uploads/router.py:80-87` still writes to local
   disk. Needed before this can run on any stateless/multi-instance deployment.
6. 🔌 `GET /models/status` (`services/api/app/models/router.py:29-40`) should query the real
   registry/loader state instead of returning a hardcoded dict.
7. 🗑️ Either wire up or drop the four unused Supabase tables (`review_evidence`,
   `curation_decisions`, `training_batch_items`, `model_eval_metrics`) — right now they're schema
   with no code path, which is dead weight or a half-finished feature depending on intent.
8. 🐛 Centralize the 0.45 novelty threshold into the one named constant that already exists
   (`services/api/app/reports/builder.py:39`, `_NOVELTY_THRESHOLD`) and import it everywhere it's
   currently re-typed as a bare literal: `services/worker/app/job_runner.py:252,282,338,359,375`,
   `services/api/app/reviews/curation.py:323,359`, `services/api/app/reports/router.py:81,157`,
   `services/api/app/abyss/analysis.py:57,363`. Today a tuning change requires 9+ manual edits
   across two services, and a missed spot silently diverges from the rest of the system.
9. 🐛 `services/api/app/models/router.py:51-54` — log (don't silently `pass` on) malformed model
   registry files in `GET /models/registry`, so a curator isn't shown a shorter list with no
   indication why.
10. 🐛 `services/api/app/abyss/analysis.py:243-245` — log the exception when the real heuristic
    router fails and Abyss analysis falls back to `_simple_gc_route()`. Currently indistinguishable
    from a legitimate result in the API response itself.

**Exit:** a fresh clone, deployed to a clean environment (no dev machine dependency), returns a
non-stub `predicted_taxon` and `confidence` for a real sequence; a trained model can be promoted to
production through the app, not by hand.

Maps to: master-plan Phase 7 (Foundation DNA Model Strategy) done-criteria + Phase 14 (Monthly
Release Process) done-criteria.

---

## Phase 3 — Wire the partner-facing pages to real data

Ordered by how close each page already is to real (least work first):

1. 🔌 **Academia** — already API-backed; un-mock the 11 flagged `MockTag` panels one at a time
   (dissolved oxygen, toxicity index, temp-at-depth, pH, salinity, wind/current, multi-omics
   overlay, sonic activity, activity rhythms, co-occurrence network, FAIR ZIP export) as each has a
   real data source. Co-occurrence network needs the Phase 0 scale-handling decision first.
2. 🔌 **FieldLog** — build `PATCH /field-log/entries/{id}` (currently only `POST`/`GET` exist) and
   real file-attachment storage (reuse the Phase 2.5 object-storage wiring) to replace the mocked
   edit-history and attachment UI (`FieldLog.jsx:374,436,451`, `MOCK_NOTE`, `MOCK_FILES`).
3. 🔌 **Industrial** — currently 100% static (zero API imports). Needs real data feeds for:
   incidents, audits, environmental risk, biological impact metrics, audit trail, remediation plan,
   document hub, and (pending Phase 0 decision) predictive biofouling threshold / remediation ROI.
   `scheduleAudit()`'s fake `setTimeout` success needs a real audit-scheduling backend.
4. 🔌 **Legislative** — also 100% static. Needs real feeds for: hotspot map, active alerts,
   indicator species trend, habitat-associated taxa decline, and (pending Phase 0 decision)
   economic risk/compliance exposure. `runFeasibility()`'s fake async run needs a real feasibility
   pipeline or should stay honestly disabled like the Export buttons already are.
5. 🔌 Wire the Abyss offline-auth endpoints that already exist server-side
   (`POST /auth/expedition/session`, `POST /auth/expedition/verify`) into `AbyssSetup.jsx`, which
   currently doesn't call them.
6. 🔌 Wire the already-built `ConfidenceChip`/`DetectionWindowBadge` components
   (`web_frontend/src/components/shared/`, zero current import sites) onto every predictive or
   financial figure across Academia/Industrial/Legislative as each gets un-mocked in items 1, 3, 4 —
   this is the component `SYNTHVEDA_MISSING_FEATURES.md`'s cross-cutting checklist needs, it just
   isn't rendered anywhere yet.
7. 🔌 Either wire Upload's `MODELS_BY_MODE` selector (`Upload.jsx:59-68`) into the real
   `POST /analysis/jobs` payload, or remove/relabel it — right now a user can pick a named
   "Processing Model" that has zero effect on their analysis run, with no in-context signal that
   it's inert.

**Exit:** no partner report page has a `MockTag` or a component with zero backend calls; every
number on screen traces to a real query and carries a confidence/provenance indicator.

Maps to: master-plan Phase 11 (Reports) + the per-page items in `SYNTHVEDA_MISSING_FEATURES.md`.

---

## Phase 4 — Abyss offline pack + scale hardening

Lower priority than Phases 1-3 because Abyss Mode's stub heuristics
(`services/api/app/abyss/analysis.py`) are an intentional permanent design for field triage, not a
bug — but the pack itself is incomplete:

- 🧠 Produce `route_models_quantized` (currently `"status": "not_yet_trained"`) once Phase 2's real
  models exist — quantize for offline field use.
- 🧠 Produce `reference_pack_v1` (currently `"status": "not_yet_available"`).
- 🔌 Implement LRU eviction in `services/worker/app/inference/loader.py:67-70` (currently
  single-model-per-route only, an acknowledged MVP limitation) once multiple models need to coexist
  in memory for offline packs or multi-route serving.

**Exit:** an expedition can download a working offline pack and run field triage without a network
connection, per master-plan Phase 10's done-criteria.

---

## Phase 5 — Cross-cutting polish

The finishing pass — mostly from `SYNTHVEDA_MISSING_FEATURES.md`'s cross-cutting list, called out
here because they're required for "fully polished," not because they're mock/stub bugs:

- eDNA limitations disclaimer component (technical + plain-language) — currently on zero pages.
- Provenance tag component (reference DB name + version + pipeline version) — currently on zero
  pages except a planned spot in Academia's citation generator.
- Detection Window / temporal decay badge — decided for Legislative only; confirm placement
  elsewhere or explicitly scope it out.
- Single source of truth for metadata capture (currently duplicated between Upload Analysis and
  Researcher Mode → Comments/FieldLog).
- Confidence/Source-citation chip standard applied to every predictive or financial number,
  including the Phase 3 Industrial/Legislative figures once they're real.
- Testing/CI/security pass per master-plan Phase 13 (auth tests, upload tests, RLS checks, rate
  limiting on admin-key attempts, CORS restriction, dependency scanning).
- `legacy/` and `frontend_zips_claude_design/` — decide whether to delete `legacy/` (superseded
  sklearn prototype) now that the audit confirms nothing references it.
- 🗑️ Remove the dead `debug: bool = False` flag from `services/api/app/config.py:13` (confirmed
  never read anywhere) or wire it to something real, e.g. verbose logging — a config option that
  silently does nothing is worse than no option at all.

**Deferred to last, by project owner call — not a concern while this stays a closed/internal
project, revisit before any real external users or a public deployment:**

- `services/api/app/config.py:27` — `jwt_secret` defaults to `"change-me-in-production"` with no
  startup check. Signs regular auth tokens, 45-day offline Abyss sessions, and 90-day offline
  licenses. Fix: fail loud at `main.py` startup if the default is still active.
- `infra/docker/nginx-lb.conf` has no rate limiting (the Terraform/GCP path does); only matters once
  the admin invite-key endpoint is reachable by anyone outside the team.

**Exit:** every page carries the disclaimer/provenance/confidence standard consistently; CI blocks
regressions on backend, frontend, and Rust parser; `legacy/` is either gone or explicitly kept with
a documented reason.

---

## Suggested execution order

```
Phase 0 (decisions, ~1 week, product+eng)
   ↓
Phase 1 (bug fixes + dead code, ~1-2 days, eng)
   ↓
Phase 2 (real inference + training loop, largest effort — weeks, eng+ML)
   ↓                                   ↘
Phase 3 (partner pages, can start   Phase 4 (Abyss pack, can trail
  once Phase 0 + relevant Phase 2     behind — depends on Phase 2's
  data sources land)                  real models)
   ↓                                   ↙
Phase 5 (cross-cutting polish, ongoing — start early on disclaimers/
  provenance since they touch every page, finish last on CI/security)
```

Phase 2 is the long pole — everything downstream that claims to show "results" is decorating stub
data until it lands. If sequencing under time pressure, treat Phase 1 + the Phase 2 model-hosting
item as the minimum bar before calling anything "beta," and treat the rest of Phase 2 plus Phases
3-5 as the path from beta to "fully polished."
