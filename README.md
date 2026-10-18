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
