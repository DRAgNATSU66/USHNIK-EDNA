# models/ — Packaging spec for drop-in models

Goal: make it trivial to drop trained models into `models/sandipan_models/` and have the backend use them.

Required structure (example):

models/
  sandipan_models/
    model_interface.py   # REQUIRED
    model_configs.json   # OPTIONAL
    kmer_classifier.pkl  # optional
    cgr_cnn.pth          # optional
    novelty_detector.pth # optional
    tokenizers/...

## model_interface.py API (REQUIRED)

def load(model_path: str) -> object:
    """
    Load model artifacts from model_path and return a model handle/object.
    """

def predict_batch(model_handle: object, sequences: List[str]) -> List[dict]:
    """
    Given a list of sequences, return a list of dicts in order:
      [{'predicted_species': 'Species name', 'confidence': 0.92}, ...]
    Must preserve input ordering.
    """

Notes:
- Keep predict_batch CPU-friendly if possible (worker may run on CPU).
- Keep dependencies minimal; avoid requiring CUDA on Windows.
- You may include helper tokenizers inside models/sandipan_models/tokenizers/.
- Example return fields may include 'label'/'score' instead of 'predicted_species'/'confidence'; model_wrapper handles common variants.
