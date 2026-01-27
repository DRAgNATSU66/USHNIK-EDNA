# models/sandipan_models/model_interface.py
"""
DEPRECATED - Mock model removed.

This file previously contained a mock model. Real inference is now handled
by src/species_identification/hf_inference.py using a trained DNABERT-2 model.

To use the real model:
  1. Train: python src/species_identification/train_dnabert.py ...
  2. Set: USE_HF=true, HF_MODEL_PATH=models/trained_dnabert
  3. The FastAPI backend will use hf_inference.py for real predictions.
"""

def load(*args, **kwargs):
    raise NotImplementedError(
        "Mock model has been removed. Use real trained model.\n"
        "Set USE_HF=true and HF_MODEL_PATH=models/trained_dnabert in .env"
    )


def predict_batch(*args, **kwargs):
    raise NotImplementedError(
        "Mock model has been removed. Use real trained model.\n"
        "Set USE_HF=true and HF_MODEL_PATH=models/trained_dnabert in .env"
    )
