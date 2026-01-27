# src/species_identification/nt_inference.py
"""
Inference Module for Trained Nucleotide Transformer (Windows-Safe)

NO MOCKS - This module loads the trained nucleotide-transformer model
from models/trained_nt/ and performs real GPU inference.

Environment variables:
  HF_MODEL_PATH: Path to trained model directory (default: models/trained_nt)

Usage:
  from src.species_identification.nt_inference import predict_batch
  results = predict_batch(["ATGCGTACGTAGCTAG..."])
  # Returns: [{"label": "FishA", "label_id": 0, "confidence": 0.95}]

CLI test:
  python src/species_identification/nt_inference.py --test-seq "ATGCGTACGTAGCTAGCTGACTGATCGTAGCTAGCTAGCTAG"
"""

import os
import sys
import json
import threading
from typing import List, Dict, Any, Optional
from pathlib import Path

import torch
import torch.nn as nn
import numpy as np

# Lock for thread-safe model loading
_lock = threading.Lock()

# Global state for lazy loading
_state = {
    "loaded": False,
    "model_path": None,
    "tokenizer": None,
    "model": None,
    "base_model": None,
    "label_map": None,  # label -> id
    "id2label": None,   # id -> label
    "device": None,
    "config": None
}


def _get_model_path() -> str:
    """
    Get model path from environment or default.
    
    Handles cross-platform paths:
    - Windows: models/trained_nt or C:\\...\\models\\trained_nt
    - WSL Linux: /mnt/c/Users/.../models/trained_nt
    """
    import platform
    
    # Check environment variable first
    env_path = os.getenv("HF_MODEL_PATH")
    if env_path:
        return env_path
    
    # Default paths based on platform
    if platform.system() == "Linux":
        # Check if running in WSL (Linux with Windows filesystem access)
        wsl_path = "/mnt/c/Users/ushni/Documents/SIH_REPO/models/trained_nt"
        if os.path.exists(wsl_path):
            return wsl_path
    
    # Default relative path (works on Windows and standard setups)
    return "models/trained_nt"


class NTClassifier(nn.Module):
    """
    Nucleotide Transformer Classifier for inference.
    
    Loads base model + trained classification head.
    """
    
    def __init__(self, base_model, hidden_size: int, num_labels: int, dropout: float = 0.1):
        super().__init__()
        self.base_model = base_model
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(hidden_size, num_labels)
        
    def forward(self, input_ids, attention_mask=None, **kwargs):
        with torch.no_grad():
            outputs = self.base_model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                output_hidden_states=True
            )
        
        if hasattr(outputs, 'last_hidden_state'):
            hidden_states = outputs.last_hidden_state
        else:
            hidden_states = outputs[0]
        
        # Mean pooling
        if attention_mask is not None:
            mask = attention_mask.unsqueeze(-1).float()
            pooled = (hidden_states * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        else:
            pooled = hidden_states.mean(dim=1)
        
        pooled = self.dropout(pooled)
        logits = self.classifier(pooled)
        
        return logits


def _lazy_load(model_path: Optional[str] = None) -> None:
    """Lazy load model and tokenizer on first inference call."""
    with _lock:
        path = model_path or _get_model_path()
        
        # Already loaded with same path
        if _state["loaded"] and _state["model_path"] == path:
            return
        
        print(f"[nt_inference] Loading model from: {path}")
        
        # Validate path exists
        model_dir = Path(path)
        if not model_dir.exists():
            raise FileNotFoundError(
                f"Model directory not found: {path}\n"
                f"Please train a model first using train_nt.py or set HF_MODEL_PATH correctly."
            )
        
        # Check for required files
        required_files = ["label_map.json", "training_config.json"]
        for f in required_files:
            fpath = model_dir / f
            if not fpath.exists():
                raise FileNotFoundError(f"Required file not found: {fpath}")
        
        # Load label_map.json
        label_map_path = model_dir / "label_map.json"
        with open(label_map_path, "r", encoding="utf-8") as f:
            label_map = json.load(f)
        
        id2label = {v: k for k, v in label_map.items()}
        
        # Load training config
        config_path = model_dir / "training_config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            training_config = json.load(f)
        
        # Get model info from training config
        base_model_name = training_config.get("model_name", "InstaDeepAI/nucleotide-transformer-500m-1000g")
        hidden_size = training_config.get("hidden_size", 1024)
        num_labels = training_config.get("num_labels", len(label_map))
        dropout = training_config.get("dropout", 0.1)
        
        print(f"[nt_inference] Base model: {base_model_name}")
        print(f"[nt_inference] Labels: {list(label_map.keys())}")
        
        # Import HuggingFace
        from transformers import AutoTokenizer, AutoModel, AutoConfig
        
        # Load tokenizer from saved directory
        tokenizer = AutoTokenizer.from_pretrained(str(model_dir), trust_remote_code=True)
        
        # Ensure pad token
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token or "[PAD]"
        
        # Load base model from original HuggingFace
        print(f"[nt_inference] Loading base model from HuggingFace: {base_model_name}")
        base_config = AutoConfig.from_pretrained(base_model_name, trust_remote_code=True)
        base_model = AutoModel.from_pretrained(
            base_model_name,
            config=base_config,
            trust_remote_code=True
        )
        
        # Create classifier
        model = NTClassifier(base_model, hidden_size, num_labels, dropout=dropout)
        
        # Load trained weights
        model_weights_path = model_dir / "model.pt"
        if model_weights_path.exists():
            print(f"[nt_inference] Loading trained weights from: {model_weights_path}")
            state_dict = torch.load(model_weights_path, map_location="cpu")
            model.load_state_dict(state_dict)
        else:
            # Try loading just the classifier head
            classifier_path = model_dir / "classifier_head.pt"
            if classifier_path.exists():
                print(f"[nt_inference] Loading classifier head from: {classifier_path}")
                classifier_state = torch.load(classifier_path, map_location="cpu")
                model.classifier.weight.data = classifier_state['classifier.weight']
                model.classifier.bias.data = classifier_state['classifier.bias']
            else:
                raise FileNotFoundError(
                    f"No model weights found. Expected model.pt or classifier_head.pt in {path}"
                )
        
        # Move to GPU if available
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device)
        model.eval()
        
        print(f"[nt_inference] Model loaded on {device}")
        
        # Update state
        _state["loaded"] = True
        _state["model_path"] = path
        _state["tokenizer"] = tokenizer
        _state["model"] = model
        _state["label_map"] = label_map
        _state["id2label"] = id2label
        _state["device"] = device
        _state["config"] = training_config


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
    config = _state["config"]
    
    max_length = config.get("max_length", 512)
    
    # Tokenize
    inputs = tokenizer(
        sequences,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt"
    )
    
    # Move to device
    inputs = {k: v.to(device) for k, v in inputs.items()}
    
    # Inference
    with torch.no_grad():
        logits = model(**inputs)
        
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
        "num_labels": len(_state["label_map"]),
        "config": _state["config"]
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
        _state["config"] = None
        
        # Clear CUDA cache
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# CLI for testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test NT inference")
    parser.add_argument("--test-seq", type=str, help="DNA sequence to classify")
    parser.add_argument("--model-path", type=str, default=None, help="Model directory")
    args = parser.parse_args()
    
    if args.test_seq:
        print("=" * 60)
        print("NUCLEOTIDE TRANSFORMER INFERENCE TEST")
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
            if k != "config":
                print(f"  {k}: {v}")
        
        print("\n" + "=" * 60)
        print("JSON Output:")
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python nt_inference.py --test-seq 'ATGCGTACG...'")
