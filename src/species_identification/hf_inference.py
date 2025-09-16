# src/species_identification/hf_inference.py
"""
Mock HF helper for testing the HFWrapper path.

Implements predict_batch(sequences: List[str]) -> List[dict]
Return shape is compatible with the model_wrapper expectations.
"""

from typing import List, Dict
import hashlib

def _deterministic_species(seq: str) -> (str, float):
    # derive deterministic pseudo-random result from sequence bytes
    h = hashlib.sha256(seq.encode("utf-8")).hexdigest()
    # use a small pool
    pool = ["HF_Species_A", "HF_Species_B", "HF_Species_C", "HF_Species_D"]
    idx = int(h[:8], 16) % len(pool)
    # confidence from hex fragment
    conf = (int(h[8:16], 16) % 50) / 100 + 0.5  # 0.5 - 0.99
    return pool[idx], round(conf, 3)

def predict_batch(sequences: List[str]) -> List[Dict]:
    out = []
    for seq in sequences:
        label, confidence = _deterministic_species(seq)
        out.append({"predicted_species": label, "confidence": confidence})
    return out
