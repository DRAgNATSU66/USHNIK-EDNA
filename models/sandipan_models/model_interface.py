"""
Mock Sandipan model_interface for local testing.

This file implements the required API:

def load(model_path: str) -> model_handle
def predict_batch(model_handle, sequences: List[str]) -> List[dict]

Replace with real model loading/predict logic when Sandipan provides assets.
"""

from typing import List, Dict
import time
import random
import os

# Simple model handle example (could be a dict or class in real life)
class MockModel:
    def __init__(self, config=None):
        self.config = config or {}
        # pretend we loaded weights
        self.loaded_at = time.time()

def load(model_path: str = "models/sandipan_models"):
    """
    "Load" the model artifacts. In real use, load weights, tokenizer, configs, etc.
    """
    cfg_path = os.path.join(model_path, "model_configs.json")
    config = {}
    if os.path.exists(cfg_path):
        try:
            import json
            with open(cfg_path, "r", encoding="utf-8") as fh:
                config = json.load(fh)
        except Exception:
            config = {}
    return MockModel(config=config)


def predict_batch(model_handle, sequences: List[str]) -> List[Dict]:
    """
    A deterministic-ish mock predictor so results are repeatable for testing.

    Returns list of dicts aligned with input, e.g.:
      {'predicted_species': 'Species A', 'confidence': 0.92}
    """
    out = []
    # Some simple fake species list
    species_pool = ["Panthera tigris", "Canis lupus", "Homo sapiens", "Drosophila melanogaster"]
    for seq in sequences:
        # crude deterministic pseudo-random pick based on sequence length + first char
        seed_val = (len(seq) + (ord(seq[0]) if seq else 0)) % 100
        idx = seed_val % len(species_pool)
        confidence = 0.4 + ((seed_val % 60) / 100)  # between 0.4 - 0.99
        out.append({
            "predicted_species": species_pool[idx],
            "confidence": round(confidence, 3)
        })
    return out
