# Model Registry

This directory contains metadata for all Synth Veda models.
Model binaries are **not** stored here — they live on Hugging Face Hub private repos or object storage.

## Artifact Locations

| Model | Location | Notes |
|-------|----------|-------|
| `trained_dnabert` | local (untracked) | DNABERT-2 fine-tune prototype — not production |
| `trained_nt` | local (untracked) | Nucleotide Transformer prototype — not production |
| `species_clf.pkl` | local (untracked) | sklearn prototype — smoke-test only |
| `sandipan_models/` | local (untracked) | external model artifacts — not production |

## Download Instructions

Production models will be hosted on Hugging Face Hub private repos.
See individual model entries in this directory once they are promoted to staging/production.

## Model Metadata Schema

Each model entry (e.g. `fish_classifier_v1.json`) must include:

```json
{
  "model_id": "sv_fish_v1",
  "route": "fish",
  "base_model": "zhihan1996/DNABERT-2-117M",
  "training_dataset_version": "2026-05",
  "label_set_version": "2026-05",
  "metrics": {
    "f1": 0.0,
    "precision": 0.0,
    "recall": 0.0
  },
  "thresholds": {
    "min_confidence": 0.5
  },
  "artifact_uri": "hf://synthveda-private/fish_v1",
  "checksum": "",
  "created_at": "",
  "promoted_by": "",
  "status": "experimental"
}
```

Status values: `experimental` | `staging` | `production` | `retired`
