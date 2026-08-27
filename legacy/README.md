# Legacy (archived, not deleted)

This is the pre-refactor version of the app, archived here 2026-08-15 during
a codebase cleanup rather than deleted, in case any of the ML experimentation
in `src/species_identification/` is worth revisiting.

**None of this is used by the running application.** The current app is:
- API: `services/api/` (FastAPI)
- Worker: `services/worker/` (job pipeline, DNABERT-2 inference)
- Frontend: `web_frontend/` (React + Vite)
- Parser: `packages/fastx_parser/` (Rust, optional) with a Python fallback in `services/worker/app/fastx_parser.py`

What's in here and why it was retired:
- `src/web_api/` — an earlier FastAPI app, superseded by `services/api/`.
- `src/species_identification/` — earlier sklearn/Nucleotide-Transformer
  experiments (`train_dnabert.py`, `train_nt.py`, `nt_inference.py`, etc.)
  loading a `species_clf.pkl` model, superseded by the DNABERT-2 +
  model-registry approach in `services/worker/app/inference/` and the
  active training code in `services/worker/training/`.
- `Dockerfile`, `requirements.txt`, `tests/` — build/test scaffolding for
  `src/web_api`, kept alongside it since they're meaningless without it.
- `inspect_model.py`, `inspect_pickle.py` — debug scripts for the old
  `models/species_clf.pkl` artifact.

Safe to delete outright once you're confident nothing here is worth
salvaging.
