# src/species_identification/hf_inference.py
"""
Real HuggingFace Inference Module for eDNA Species Classification.

NO MOCKS - This module loads the trained DNABERT-2 model and performs
real GPU inference.

Environment variables:
  HF_MODEL_PATH: Path to trained model directory (default: models/trained_dnabert)

Usage:
  from src.species_identification.hf_inference import predict_batch
  results = predict_batch(["ATGCGTACGTAGCTAG..."])
  # Returns: [{"label": "FishA", "label_id": 0, "confidence": 0.95}]

CLI test:
  python src/species_identification/hf_inference.py --test-seq "ATGCGTACGTAGCTAGCTGACTGATCGTAGCTAGCTAGCTAG"
"""

import os
import sys
import json
import threading
from typing import List, Dict, Any, Optional
from pathlib import Path

import torch
import numpy as np

# Lock for thread-safe model loading
_lock = threading.Lock()

# Global state for lazy loading
_state = {
    "loaded": False,
    "model_path": None,
    "tokenizer": None,
    "model": None,
    "label_map": None,  # label -> id
    "id2label": None,   # id -> label
    "device": None
}


def _get_model_path() -> str:
    """Get model path from environment or default."""
    return os.getenv("HF_MODEL_PATH", "models/trained_dnabert")


def _lazy_load(model_path: Optional[str] = None) -> None:
    """Lazy load model and tokenizer on first inference call."""
    with _lock:
        path = model_path or _get_model_path()
        
        # Already loaded with same path
        if _state["loaded"] and _state["model_path"] == path:
            return
        
        print(f"[hf_inference] Loading model from: {path}")
        
        # Validate path exists
        model_dir = Path(path)
        if not model_dir.exists():
            raise FileNotFoundError(
                f"Model directory not found: {path}\n"
                f"Please train a model first or set HF_MODEL_PATH correctly."
            )
        
        # Load label_map.json
        label_map_path = model_dir / "label_map.json"
        if not label_map_path.exists():
            raise FileNotFoundError(f"label_map.json not found in {path}")
        
        with open(label_map_path, "r", encoding="utf-8") as f:
            label_map = json.load(f)
        
        id2label = {v: k for k, v in label_map.items()}
        
        # Import here to keep module import cheap
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        
        # Load tokenizer
        tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
        
        # Load model
        model = AutoModelForSequenceClassification.from_pretrained(
            path,
            trust_remote_code=True
        )
        
        # Move to GPU if available
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device)
        model.eval()
        
        print(f"[hf_inference] Model loaded on {device}")
        print(f"[hf_inference] Labels: {list(label_map.keys())}")
        
        # Update state
        _state["loaded"] = True
        _state["model_path"] = path
        _state["tokenizer"] = tokenizer
        _state["model"] = model
        _state["label_map"] = label_map
        _state["id2label"] = id2label
        _state["device"] = device


def predict_single(sequence: str, model_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Predict species for a single DNA sequence.
    
    Args:
        sequence: DNA sequence string (A/T/C/G/N)
        model_path: Optional model directory override
    
    Returns:
        {"label": str, "label_id": int, "confidence": float}
    """
    results = predict_batch([sequence], model_path=model_path)
    return results[0]


def predict_batch(sequences: List[str], model_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Predict species for a batch of DNA sequences.
    
    Args:
        sequences: List of DNA sequence strings
        model_path: Optional model directory override
    
    Returns:
        List of {"label": str, "label_id": int, "confidence": float}
    """
    if not sequences:
        return []
    
    # Ensure model is loaded
    _lazy_load(model_path)
    
    tokenizer = _state["tokenizer"]
    model = _state["model"]
    id2label = _state["id2label"]
    device = _state["device"]
    
    # Tokenize
    inputs = tokenizer(
        sequences,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt"
    )
    
    # Move to device
    inputs = {k: v.to(device) for k, v in inputs.items()}
    
    # Inference
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits
        
        # Softmax for probabilities
        probs = torch.nn.functional.softmax(logits, dim=-1)
        
        # Get predictions
        predicted_ids = torch.argmax(probs, dim=-1).cpu().numpy()
        confidences = probs.max(dim=-1).values.cpu().numpy()
    
    # Build results
    results = []
    for i, seq in enumerate(sequences):
        label_id = int(predicted_ids[i])
        label = id2label.get(label_id, f"UNKNOWN_{label_id}")
        confidence = float(confidences[i])
        
        results.append({
            "label": label,
            "label_id": label_id,
            "confidence": round(confidence, 4)
        })
    
    return results


def get_model_info() -> Dict[str, Any]:
    """Get information about the loaded model."""
    if not _state["loaded"]:
        return {"loaded": False, "model_path": _get_model_path()}
    
    return {
        "loaded": True,
        "model_path": _state["model_path"],
        "device": str(_state["device"]),
        "labels": list(_state["label_map"].keys()),
        "num_labels": len(_state["label_map"])
    }


def unload_model() -> None:
    """Unload model from memory."""
    with _lock:
        if _state["model"] is not None:
            del _state["model"]
        if _state["tokenizer"] is not None:
            del _state["tokenizer"]
        
        _state["loaded"] = False
        _state["model_path"] = None
        _state["model"] = None
        _state["tokenizer"] = None
        _state["label_map"] = None
        _state["id2label"] = None
        _state["device"] = None
        
        # Clear CUDA cache
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# CLI for testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test HF inference")
    parser.add_argument("--test-seq", type=str, help="DNA sequence to classify")
    parser.add_argument("--model-path", type=str, default=None, help="Model directory")
    args = parser.parse_args()
    
    if args.test_seq:
        print("=" * 60)
        print("HF INFERENCE TEST")
        print("=" * 60)
        
        result = predict_single(args.test_seq, model_path=args.model_path)
        
        print(f"\nSequence: {args.test_seq[:50]}...")
        print(f"Predicted: {result['label']}")
        print(f"Confidence: {result['confidence']:.4f}")
        print(f"Label ID: {result['label_id']}")
        
        print("\n" + "=" * 60)
        print("Model Info:")
        info = get_model_info()
        for k, v in info.items():
            print(f"  {k}: {v}")
    else:
        print("Usage: python hf_inference.py --test-seq 'ATGCGTACG...'")
