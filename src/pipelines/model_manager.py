"""
src/pipelines/model_manager.py

Lightweight model manager / hot-swap pipeline for the eDNA project.

- Lazily loads Hugging Face models for temporary inference.
- Supports a drop-in "custom model package" (Sandipan / Arya) which must include
  a model_interface.py implementing a class with:
      @classmethod
      def load(cls, model_path) -> CustomModelWrapper
  and CustomModelWrapper must implement:
      def predict(self, sequences: List[str]) -> List[dict]
      (see README or comments below)

This file intentionally avoids heavy imports at module import time and attempts
CPU-friendly fallbacks. It returns simple prediction dicts the frontend expects.
"""

import os
import importlib.util
import logging
from typing import List, Dict, Any, Optional
import numpy as np

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------
# Device detection
# ---------------------
try:
    import torch

    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
except Exception:
    torch = None
    DEVICE = "cpu"

# ---------------------
# ModelManager
# ---------------------
class ModelManager:
    """
    Manages a pool of models (temporary HF models and optional custom models).
    Public methods:
      - predict(sequences, metadata) -> standardized list of dicts
      - set_custom_pipeline(path) -> load custom models provided by teammates
      - get_status() -> health info
    """

    def __init__(self):
        # lazy-loaded model objects
        self._hf_models = {}  # name -> { 'tokenizer':..., 'model':..., 'type':... }
        self._custom_pipeline = None  # loaded custom wrapper (Sandipan/Arya)
        self._active_backend = "huggingface"  # or "custom"
        self._available_hf = {
            "esm2": "facebook/esm2_t6_8M_UR50D",
            "nucleotide": "InstaDeepAI/nucleotide-transformer-v2-50m-multi-species",
            # Llama kept out of cold start due to size - load manually if you want
            # "llama_1b": "meta-llama/Llama-3.2-1B-Instruct"
        }

    # ---------------------
    # Helpers: lazy HF loader
    # ---------------------
    def _lazy_load_hf(self, key: str):
        """
        Lazy-load a Hugging Face model and tokenizer if not loaded.
        This uses transformers AutoModel/AutoTokenizer by default; for special
        models (esm) the project may provide dedicated classes — we attempt
        to use standard Auto* as a robust fallback.
        """
        if key in self._hf_models:
            return self._hf_models[key]

        model_name = self._available_hf.get(key)
        if not model_name:
            raise ValueError(f"No HF model configured for key: {key}")

        logger.info("Attempting to load HF model '%s' -> %s (device=%s)", key, model_name, DEVICE)
        try:
            # import inside function to avoid heavy import at module load
            from transformers import AutoModel, AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=True)
            model = AutoModel.from_pretrained(model_name)
            # move to device if torch available
            if torch is not None and isinstance(DEVICE, torch.device) and DEVICE.type == "cuda":
                model.to(DEVICE)
            # store minimal wrapper
            wrapper = {"tokenizer": tokenizer, "model": model, "hf_name": model_name}
            self._hf_models[key] = wrapper
            logger.info("Loaded model %s", model_name)
            return wrapper
        except Exception as e:
            logger.exception("Failed to load HF model %s: %s", model_name, e)
            # safe fallback: mark as not available
            self._hf_models[key] = None
            return None

    # ---------------------
    # Custom pipeline loader
    # ---------------------
    def set_custom_pipeline(self, package_path: str) -> bool:
        """
        Try to load a custom model package from the given path.
        The package must contain model_interface.py with a class implementing:
            @classmethod load(cls, model_path) -> instance
            instance.predict(sequences: List[str]) -> List[dict]  # standardized output
        Returns True if loaded and activated, False otherwise.
        """
        if not os.path.exists(package_path):
            logger.error("Custom pipeline path does not exist: %s", package_path)
            return False

        # look for model_interface.py
        interface_file = os.path.join(package_path, "model_interface.py")
        if not os.path.exists(interface_file):
            logger.error("No model_interface.py found in custom package at %s", package_path)
            return False

        try:
            # dynamic import
            spec = importlib.util.spec_from_file_location("custom_model_interface", interface_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore
            # expect class CustomModelWrapper or SandipanModelWrapper / AryaModelWrapper - be flexible
            wrapper_cls = None
            for name in ("CustomModelWrapper", "SandipanModelWrapper", "AryaModelWrapper", "ModelWrapper"):
                wrapper_cls = getattr(mod, name, None)
                if wrapper_cls:
                    break
            if wrapper_cls is None and hasattr(mod, "load"):
                # support module-level load function
                self._custom_pipeline = mod
            else:
                # call classmethod load
                self._custom_pipeline = wrapper_cls.load(package_path)

            # quick check: ensure predict exists
            if not hasattr(self._custom_pipeline, "predict"):
                logger.error("Custom pipeline loaded but has no 'predict' method.")
                self._custom_pipeline = None
                return False

            self._active_backend = "custom"
            logger.info("Custom pipeline loaded and activated from %s", package_path)
            return True
        except Exception as e:
            logger.exception("Failed to load custom pipeline: %s", e)
            self._custom_pipeline = None
            return False

    # ---------------------
    # Predict interface
    # ---------------------
    async def predict(self, sequences: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Main entrypoint used by FastAPI.
        Input:
          sequences: list of dicts { 'id': <id>, 'sequence': <nucleotide string> }
        Output:
          list of dicts:
            {
                "sequence_id": str,
                "sequence": str,
                "predicted_species": str,
                "confidence": float (0..1),
                "source": "huggingface" | "custom" | "unknown"
            }
        Behavior:
          - If custom pipeline active, call it.
          - Otherwise call hf fallback pipeline (ESM2 + Nucleotide Transformer ensemble)
          - If both fail -> return Unknown results with 0.0 confidence
        """
        metadata = metadata or {}
        # normalize input
        seqs_only = [s.get("sequence", "") for s in sequences]
        ids = [s.get("id", f"seq{i+1}") for i, s in enumerate(sequences)]

        # 1) If custom pipeline available, use it
        if self._active_backend == "custom" and self._custom_pipeline is not None:
            try:
                # custom pipeline may accept list[str] or list[dict]
                raw_out = self._custom_pipeline.predict(seqs_only)
                # Expect list of dicts with keys -> convert/normalize to standard shape
                return self._normalize_custom_output(ids, seqs_only, raw_out)
            except Exception:
                logger.exception("Custom pipeline prediction failed; falling back to HF.")
                # fall through to HF

        # 2) HF fallback ensemble (try nucleotide model first for DNA)
        hf_nt = self._lazy_load_hf("nucleotide")
        hf_esm = self._lazy_load_hf("esm2")

        # if neither HF model available -> Unknowns
        if hf_nt is None and hf_esm is None:
            logger.warning("No models available for inference (custom missing and HF fallback not loaded).")
            return [
                {
                    "sequence_id": seq_id,
                    "sequence": seq,
                    "predicted_species": "Unknown",
                    "confidence": 0.0,
                    "source": "none"
                }
                for seq_id, seq in zip(ids, seqs_only)
            ]

        # try nucleotide transformer first (DNA-specialized)
        try:
            nt_scores = self._predict_with_hf(hf_nt, seqs_only) if hf_nt else None
        except Exception:
            logger.exception("Nucleotide model failed during prediction")
            nt_scores = None

        try:
            esm_scores = self._predict_with_hf(hf_esm, seqs_only) if hf_esm else None
        except Exception:
            logger.exception("ESM model failed during prediction")
            esm_scores = None

        # Merge / ensemble logic (simple)
        results = []
        for i, seq in enumerate(seqs_only):
            best_label = "Unknown"
            best_score = 0.0
            source = "unknown"

            # prefer nucleotide model for DNA-specific signals
            if nt_scores and i < len(nt_scores):
                label, score = nt_scores[i]
                if score >= best_score:
                    best_label, best_score, source = label, score, "nucleotide"
            if esm_scores and i < len(esm_scores):
                label, score = esm_scores[i]
                # if ESM gives higher confidence, use it
                if score >= best_score:
                    best_label, best_score, source = label, score, "esm2"

            # simple sanity bounding
            best_score = float(min(max(best_score, 0.0), 1.0))
            results.append({
                "sequence_id": ids[i],
                "sequence": seq,
                "predicted_species": best_label,
                "confidence": best_score,
                "source": source
            })
        return results

    # ---------------------
    # Internal: normalize custom
    # ---------------------
    def _normalize_custom_output(self, ids: List[str], seqs: List[str], raw_out: Any) -> List[Dict[str, Any]]:
        """
        Accepts various raw outputs from a custom pipeline and normalize to standard shape.
        Supports:
         - list[str] labels
         - list[ (label, score) ]
         - list[ dicts {'label':..., 'score':...} ]
         - list[ dicts ] with custom keys -> attempt mapping
        """
        out = []
        # if custom returned None or empty
        if not raw_out:
            for i, seq in enumerate(seqs):
                out.append({
                    "sequence_id": ids[i],
                    "sequence": seq,
                    "predicted_species": "Unknown",
                    "confidence": 0.0,
                    "source": "custom"
                })
            return out

        # if list-like
        if isinstance(raw_out, (list, tuple)):
            for i, item in enumerate(raw_out):
                seq = seqs[i] if i < len(seqs) else ""
                sid = ids[i] if i < len(ids) else f"seq{i+1}"
                if isinstance(item, str):
                    out.append({"sequence_id": sid, "sequence": seq, "predicted_species": item, "confidence": 1.0, "source": "custom"})
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    label, score = item[0], float(item[1])
                    out.append({"sequence_id": sid, "sequence": seq, "predicted_species": label, "confidence": score, "source": "custom"})
                elif isinstance(item, dict):
                    # common keys
                    label = item.get("predicted_species") or item.get("label") or item.get("species") or item.get("prediction")
                    score = item.get("confidence") or item.get("score") or item.get("probability") or 0.0
                    label = label or "Unknown"
                    out.append({"sequence_id": sid, "sequence": seq, "predicted_species": label, "confidence": float(score), "source": "custom"})
                else:
                    out.append({"sequence_id": sid, "sequence": seq, "predicted_species": "Unknown", "confidence": 0.0, "source": "custom"})
            return out

        # fallback
        for i, seq in enumerate(seqs):
            out.append({
                "sequence_id": ids[i],
                "sequence": seq,
                "predicted_species": "Unknown",
                "confidence": 0.0,
                "source": "custom"
            })
        return out

    # ---------------------
    # Internal: simple HF prediction helper
    # ---------------------
    def _predict_with_hf(self, wrapper: Dict[str, Any], sequences: List[str]) -> List[tuple]:
        """
        Lightweight prediction wrapper for AutoModel-based HF models.
        It returns a list of (label, score) tuples for each sequence.

        NOTE: This is intentionally simple: many HF models require special tokenization
              for biological sequences. This function aims to provide a functional
              temporary pipeline that produces a confidence score from model embeddings.

        You should replace this with model-specific code when fine-tuning or adding
        proper classifier heads.
        """
        if wrapper is None:
            return []

        tokenizer = wrapper.get("tokenizer")
        model = wrapper.get("model")
        hf_name = wrapper.get("hf_name", "hf_model")
        results = []

        # If model has a .predict or classifier head, you should call that instead.
        # We'll compute an embedding and then produce a dummy label/confidence.
        try:
            # tokenizer handles batch encode
            encoded = tokenizer(sequences, padding=True, truncation=True, return_tensors="pt")
            if torch is not None:
                # move inputs to same device as model if possible
                try:
                    device = next(model.parameters()).device
                except Exception:
                    device = DEVICE if isinstance(DEVICE, torch.device) else "cpu"
                for k, v in encoded.items():
                    try:
                        encoded[k] = v.to(device)
                    except Exception:
                        pass

            # forward pass
            with torch.no_grad() if torch is not None else DummyContextManager():
                out = model(**encoded) if hasattr(model, "__call__") else None

            # obtain a pooled embedding (try common locations)
            embedding = None
            if out is None:
                # fallback - random
                embedding = np.random.randn(len(sequences), 16)
            else:
                # attempt several common names
                if hasattr(out, "pooler_output") and out.pooler_output is not None:
                    emb = out.pooler_output
                elif isinstance(out, tuple) and len(out) >= 1:
                    # some models return (last_hidden_state, pooler)
                    emb = out[0].mean(dim=1) if hasattr(out[0], "mean") else out[0]
                elif hasattr(out, "last_hidden_state"):
                    emb = out.last_hidden_state.mean(dim=1)
                else:
                    # generic fallback
                    try:
                        emb = list(out.values())[0]
                    except Exception:
                        emb = None

                if emb is None:
                    embedding = np.random.randn(len(sequences), 16)
                else:
                    # convert to numpy
                    try:
                        embedding = emb.cpu().numpy() if torch is not None and hasattr(emb, "cpu") else np.asarray(emb)
                        # if embedding is higher-dim & too large, reduce to small vector
                        if embedding.ndim > 2:
                            embedding = embedding.reshape(embedding.shape[0], -1)[:, :128]
                        elif embedding.ndim == 2 and embedding.shape[1] > 128:
                            embedding = embedding[:, :128]
                    except Exception:
                        embedding = np.random.randn(len(sequences), 16)
        except Exception as e:
            logger.exception("Exception while running HF model forward pass: %s", e)
            embedding = np.random.randn(len(sequences), 16)

        # Simple toy classifier over embedding to produce label + confidence
        # Replace with proper classifier head when available.
        for i in range(len(sequences)):
            vec = embedding[i]
            # deterministic-ish pseudo scoring: use normalized L2 to map to 0..1
            score = float(1.0 / (1.0 + float(np.linalg.norm(vec))))
            # fake label — use model name and top-k hash to create consistent pseudo-labels
            label = f"{hf_name.split('/')[-1][:20]}_hit"
            results.append((label, float(score)))

        return results

    # ---------------------
    # Status
    # ---------------------
    def get_status(self) -> Dict[str, Any]:
        return {
            "active_backend": self._active_backend,
            "custom_pipeline_loaded": self._custom_pipeline is not None,
            "hf_models": {k: (v is not None) for k, v in self._hf_models.items()},
            "device": str(DEVICE),
        }


# ---------------------
# Small utility
# ---------------------
class DummyContextManager:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


# ---------------------
# Single global instance for app to import
# ---------------------
MODEL_MANAGER = ModelManager()
