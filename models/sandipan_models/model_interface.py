# models/sandipan_models/model_interface.py
"""
DEPRECATED - Mock model removed.

This file previously contained a mock model. Real inference is handled by
the worker (services/worker/app/inference/, DNABERT-2 + model registry);
training lives in services/worker/training/ (see its README.md).
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
