# Synth Veda

eDNA species classification: upload FASTA/FASTQ, get per-sequence species
predictions, possible-novelty flags and reports.

- API: `services/api/` (FastAPI)
- Worker: `services/worker/` (job pipeline, DNABERT-2 inference; training in `services/worker/training/`)
- Frontend: `web_frontend/` (React + Vite)
- Parser: `packages/fastx_parser/` (Rust, optional; Python fallback in the worker)

Architecture and request flow: `docs/architecture.md`, `docs/flow.md`.

---

## Quick start

```bash
cp .env.example .env            # fill in values; APP_ENV=dev for local work
make up                         # API, worker, Mongo, Redis, MinIO, frontend via Docker Compose
# API docs: http://localhost:8000/docs   Frontend: http://localhost:3000
```

Without Docker:

```bash
make api-install && make api-run          # API on :8000
make worker-install && make worker-run    # worker
cd web_frontend && npm install && npm run dev
```

Tests: `make api-test`, `make worker-test`, `cd web_frontend && npm run build`.

Full loop (local only, not in CI): `make test-loop` runs upload → worker orchestrator → reviews →
training batch → freeze → register → promote as one pytest against real Mongo and Redis, the
worker venv and the models. It needs Mongo :27017 and Redis :6379 (`make up`), a data root with
`processed/`, `checkpoints/`, `reference/` and BLAST+ (`DATA_ROOT=...`, default `./synthveda-data`),
and both service venvs (`API_PYTHON=` / `WORKER_PYTHON=` to point elsewhere). It works in a
throwaway Mongo database, Redis db 15 and a temp copy of `models/registry`; without the data
root it skips and says what is missing. See the comment above `test-loop` in the Makefile.
