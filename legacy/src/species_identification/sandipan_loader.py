"""
Tiny helper for sandipan models.

Assumes a package directory at: models/sandipan_models/
which contains model_interface.py implementing:
 - load(model_path: str) -> model_handle
 - predict_batch(model_handle, list_of_sequences: List[str]) -> List[dict]
"""

from typing import List, Dict
import os


def is_present(path: str = "models/sandipan_models") -> bool:
    return os.path.isdir(path) and os.path.exists(os.path.join(path, "model_interface.py"))


def load_model(path: str = "models/sandipan_models"):
    # dynamic import to avoid import time errors if package not present
    from importlib import import_module
    module = import_module("models.sandipan_models.model_interface")
    model = module.load(path)
    return module, model


def predict_batch(module, model_handle, sequences: List[str]) -> List[Dict]:
    # delegate to module.predict_batch
    return module.predict_batch(model_handle, sequences)
