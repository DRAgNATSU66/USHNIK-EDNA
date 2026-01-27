# src/species_identification/model_wrapper.py
"""
Model wrapper / adapter layer for eDNA species classification.

Priority logic:
  1) NTWrapper (real trained nucleotide-transformer model) if USE_HF=true
  2) Error - NO FAKE SPECIES, NO MOCKS

Environment variables:
  USE_HF: Set to "true" to enable nucleotide transformer model (required)
  HF_MODEL_PATH: Path to trained model directory (default: models/trained_nt)

IMPORTANT: All mock models have been removed. This module will raise
an error if no real model is available.
"""

import os
import typing as t
from abc import ABC, abstractmethod


def is_hf_enabled() -> bool:
    """Check if HuggingFace/NT model is enabled via environment."""
    return os.getenv("USE_HF", "false").lower() in ("1", "true", "yes")


def get_model_path() -> str:
    """Get model path from environment."""
    return os.getenv("HF_MODEL_PATH", "models/trained_nt")


class ModelWrapperBase(ABC):
    """Base class for model wrappers."""
    
    @classmethod
    @abstractmethod
    def available(cls) -> bool:
        """Check if this model is available."""
        pass
    
    @classmethod
    @abstractmethod
    def load(cls, **kwargs) -> "ModelWrapperBase":
        """Load the model."""
        pass
    
    @abstractmethod
    def predict_batch(self, sequences: t.List[t.Dict]) -> t.List[t.Dict]:
        """
        Predict species for a batch of sequences.
        
        Args:
            sequences: List of dicts with keys: sequence_id, sequence
        
        Returns:
            List of dicts with keys: sequence_id, sequence, predicted_species, confidence, source
        """
        pass


class NTWrapper(ModelWrapperBase):
    """
    Nucleotide Transformer model wrapper using trained InstaDeepAI model.
    
    Loads model from HF_MODEL_PATH and performs GPU inference.
    Uses nt_inference module for actual predictions.
    """
    
    def __init__(self, nt_module):
        self.nt = nt_module
    
    @classmethod
    def available(cls) -> bool:
        """Check if NT model is available and configured."""
        if not is_hf_enabled():
            return False
        
        # Check if model directory exists
        model_path = get_model_path()
        if not os.path.exists(model_path):
            print(f"[NTWrapper] Model path does not exist: {model_path}")
            return False
        
        # Check for required files
        required_files = ["label_map.json", "training_config.json"]
        for f in required_files:
            fpath = os.path.join(model_path, f)
            if not os.path.exists(fpath):
                print(f"[NTWrapper] Missing required file: {f}")
                return False
        
        # Check for model weights
        model_file = os.path.join(model_path, "model.pt")
        classifier_file = os.path.join(model_path, "classifier_head.pt")
        if not os.path.exists(model_file) and not os.path.exists(classifier_file):
            print(f"[NTWrapper] Missing model weights (model.pt or classifier_head.pt)")
            return False
        
        return True
    
    @classmethod
    def load(cls, **kwargs) -> "NTWrapper":
        """Load the nucleotide transformer module."""
        from src.species_identification import nt_inference
        return cls(nt_inference)
    
    def predict_batch(self, sequences: t.List[t.Dict]) -> t.List[t.Dict]:
        """Run real inference on sequences."""
        if not sequences:
            return []
        
        # Extract raw sequences
        seqs = [s.get("sequence", "") for s in sequences]
        
        # Run inference using nt_inference module
        nt_results = self.nt.predict_batch(seqs)
        
        # Build output
        out = []
        for s, r in zip(sequences, nt_results):
            out.append({
                "sequence_id": s.get("sequence_id", ""),
                "sequence": s.get("sequence", ""),
                "predicted_species": r.get("label", "Unknown"),
                "confidence": float(r.get("confidence", 0.0)),
                "source": "huggingface_trained"
            })
        
        return out


# Keep HFWrapper as alias for backward compatibility
HFWrapper = NTWrapper


class ModelNotAvailableError(Exception):
    """Raised when no valid model is available."""
    pass


class ErrorWrapper(ModelWrapperBase):
    """
    Error wrapper - raises clear error instead of returning fake species.
    
    This is used when no real model is available. It provides a clear
    error message instead of returning fake/mock predictions.
    """
    
    def __init__(self, error_message: str):
        self.error_message = error_message
    
    @classmethod
    def available(cls) -> bool:
        return True  # Always available as fallback
    
    @classmethod
    def load(cls, **kwargs) -> "ErrorWrapper":
        model_path = get_model_path()
        use_hf = is_hf_enabled()
        
        if not use_hf:
            msg = (
                "Model inference is disabled. Set USE_HF=true in environment.\n"
                "Also ensure HF_MODEL_PATH points to a trained model directory."
            )
        else:
            msg = (
                f"Trained model not found at: {model_path}\n"
                f"Please train a model first using train_nt.py or set HF_MODEL_PATH correctly.\n"
                f"Required files: label_map.json, training_config.json, model.pt (or classifier_head.pt)"
            )
        
        return cls(error_message=msg)
    
    def predict_batch(self, sequences: t.List[t.Dict]) -> t.List[t.Dict]:
        """Raise error instead of returning fake predictions."""
        raise ModelNotAvailableError(self.error_message)


def get_best_model() -> ModelWrapperBase:
    """
    Get the best available model wrapper.
    
    Priority:
      1) NTWrapper (real trained nucleotide-transformer) if USE_HF=true and model exists
      2) ErrorWrapper (raises clear error with HTTP 503)
    
    NO MOCKS, NO FAKE SPECIES.
    """
    # Try Nucleotide Transformer wrapper
    if is_hf_enabled():
        try:
            if NTWrapper.available():
                print("[model_wrapper] Loading NTWrapper (real trained nucleotide-transformer)")
                return NTWrapper.load()
            else:
                print("[model_wrapper] NTWrapper not available (model missing)")
        except Exception as e:
            print(f"[model_wrapper] NTWrapper failed to load: {e}")
    else:
        print("[model_wrapper] USE_HF not enabled")
    
    # No real model available - return error wrapper
    print("[model_wrapper] WARNING: No real model available, using ErrorWrapper")
    return ErrorWrapper.load()


# Legacy compatibility - raise clear error for old mock imports
def _raise_mock_removed_error():
    raise ImportError(
        "Mock models have been removed. Use real trained model.\n"
        "Set USE_HF=true and HF_MODEL_PATH=models/trained_nt"
    )
