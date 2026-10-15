# Synth Veda — Rules

What to use, what to avoid, and the boundaries for AI-assisted changes in this repo.
Update when a real constraint is discovered (a library that broke something, a boundary
that got violated) — not speculatively.

## Libraries / tooling

- **Don't reimplement sequence alignment/matching or clustering algorithms.** Use
  established compiled tools (BLAST+/DIAMOND for alignment, VSEARCH/DADA2 for
  OTU/ASV clustering) as subprocesses or services rather than hand-rolling
  bioinformatics logic — see `docs/specs/SYNTHVEDA_TECH_STACK.md` §3.
- **FASTA/FASTQ parsing already has a real implementation — don't add pyfastx/
  Biopython.** `packages/fastx_parser` is a purpose-built Rust crate (own binary,
  `Cargo.toml`/`src/*.rs`) called from `services/worker/app/job_runner.py`'s
  `_stage_parse`, with a pure-Python fallback baked in (`parse_and_batch_auto`). This
  supersedes the old tech-stack doc's pyfastx/Biopython recommendation — that was
  written pre-implementation.
- **DNABERT-2 is the model backbone** (`zhihan1996/DNABERT-2-117M`), fine-tuned per
  route — not swapped casually. If a change proposes a different backbone, that's a
  decisions.md-worthy call, not a quiet substitution.
- **Three separate data stores, don't blur their jobs:** MongoDB (`motor`/`pymongo`) is
  the primary app data store (uploads, jobs, analysis results); Supabase is auth-only,
  used in `services/api` only (the worker has no Supabase dependency at all); Redis is
  the job queue between API and worker. A change that reads/writes app data via
  Supabase, or tries to queue jobs through Mongo, is fighting the actual architecture.
- Frontend: React + Vite, `react-router-dom` v7, Leaflet/`react-leaflet`/`leaflet.heat`
  for maps (not Mapbox, despite the original recommendation doc). Check
  `web_frontend/package.json` before adding a new UI/mapping/charting dependency —
  don't introduce a second library that does what an existing one already does.
- CI (`.github/workflows/ci.yml`) already runs: pytest+coverage for both `services/api`
  and `services/worker`, frontend lint (non-blocking) + production build, `bandit`
  security scan (medium+ severity) on both Python services, a check that no `.env` file
  is tracked, and a Docker build validation for all three images on push. Don't
  duplicate any of this with a new workflow — extend `ci.yml` instead.

## Error handling / boundaries

- Windows compatibility constraints on the training pipeline (still relevant if training
  is ever run on Windows): base weights frozen (avoids PEFT/LoRA/bitsandbytes issues),
  fp32 precision (fp16 unstable on some Windows CUDA), `workers=0` (Windows
  multiprocessing issues). See root `README.md`.
- Scientific-integrity constraints are **non-negotiable UI requirements**, not
  suggestions — see `prd.md`. Never let a change quietly drop the "Live vs. Dead",
  population-count, spatial-ambiguity, or temporal-decay disclaimers from a
  report/detection view.
- The novelty/contamination scorer's weights are a known placeholder — don't treat its
  output as validated ground truth in downstream logic without flagging that it's not.
- Inference has a real, live fallback path: when a route has no trained model weights
  (or torch isn't installed), `_stage_infer` returns stub predictions
  (`inference_mode: "stub"`) instead of failing the job. Don't assume every completed
  analysis used a real model — check `inference_mode` / `model_version_used` on results
  before treating a prediction as trained-model output.
- `services/worker/app/dispatcher.py` swallows exceptions from `run_job()` at the
  per-task level (`except Exception: pass`) because `run_job` already logs and marks the
  job failed internally — don't add a second layer of error handling around
  `run_job()` calls, and don't remove the try/except in the dispatcher without also
  checking it won't crash the whole poll loop on one bad job.

## AI-harnessing (how an agent should operate in this repo)

- Don't mass-migrate or rewrite `docs/specs/`, `docs/architecture/`, or `docs/ml/`
  content into the new `docs/*.md` scaffold unprompted — additive only, unless the user
  explicitly asks for consolidation. See `decisions.md` (2026-09-03 entry).
- Log real considerations to `decisions.md` when making a non-obvious implementation
  choice; log what changed to `flow.md`'s session change log.
- Major changes are **recorded, not gated**: they go into `docs/qna.md` as a stenographic
  transcript entry (4-6 Q&A covering mechanism, rationale, blast radius, verification,
  defence) written as the change happens. It never blocks a merge or push. The older
  "quiz the user before accepting a major change" protocol was retired 2026-09-11. This
  is a standing cross-project protocol (Claude's memory + `~/.claude/CLAUDE.md`), not
  something to reproduce here as code.
- Treat `uploads/` under `services/api/uploads/` as generated/test artifacts, not source
  — don't hand-edit or read them as if they were spec.
- `legacy/` is superseded code kept for reference — don't build new features on it or
  assume it reflects current architecture (see `architecture.md`).
