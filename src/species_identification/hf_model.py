# src/species_identification/hf_inference.py
"""
Lazy HF inference helper for eDNA project.

Provides:
 - call_hf_model(model_name, sequences, timeout=30) -> raw_output
 - infer_labels_from_hf_output(raw_output, top_k=1) -> list of label lists:
       [ [ {"label": "<label>", "score": float}, ... ], ... ]

Behavior:
 - If model_name corresponds to a SequenceClassification model (AutoModelForSequenceClassification),
   we will return label(s) and scores using model.config.id2label if present.
 - If model_name has no classification head (AutoModel), we return embeddings (numpy arrays).
   infer_labels_from_hf_output will return safe "Unknown" labels (score 0.0) for those cases.
 - Lazy-loads tokenizer + model on first call to avoid heavy imports at server startup.
"""

import threading
from typing import List, Any
import numpy as np

_lock = threading.Lock()
_state = {
    "loaded": False,
    "model_name": None,
    "tokenizer": None,
    "model": None,
    "is_classification": False,
    "has_logits": False,
    "device": "cpu"
}

def _lazy_load(model_name: str, device: str = "cpu"):
    with _lock:
        if _state["loaded"] and _state["model_name"] == model_name:
            return
        # lazy import transformers to keep module import cheap
        try:
            from transformers import AutoTokenizer, AutoModel, AutoModelForSequenceClassification
        except Exception as e:
            raise RuntimeError(f"transformers import failed: {e}")

        _state["model_name"] = model_name
        _state["device"] = device

        # try to load tokenizer first
        tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=True)
        model = None
        is_classification = False
        has_logits = False

        # Try classification model (preferred) -> fallback to AutoModel
        try:
            model = AutoModelForSequenceClassification.from_pretrained(model_name)
            is_classification = True
            has_logits = True
        except Exception:
            # fallback to encoder-only model
            try:
                model = AutoModel.from_pretrained(model_name)
                is_classification = False
                has_logits = False
            except Exception as e:
                raise RuntimeError(f"Failed to load HF model '{model_name}': {e}")

        # move to device if CUDA available and requested
        try:
            import torch
            if device != "cpu" and torch.cuda.is_available():
                model.to(device)
            else:
                model.to("cpu")
        except Exception:
            # If torch missing or move fails, keep model on cpu
            pass

        _state["tokenizer"] = tokenizer
        _state["model"] = model
        _state["is_classification"] = is_classification
        _state["has_logits"] = has_logits
        _state["loaded"] = True

def call_hf_model(model_name: str, sequences: List[str], timeout: int = 30, device: str = "cpu") -> Any:
    """
    Tokenizes and runs the model. Returns raw model output object:
      - For classification model: returns model output (with logits).
      - For encoder model: returns dict with 'embeddings' = np.ndarray (N x D).
    """
    _lazy_load(model_name, device=device)
    tokenizer = _state["tokenizer"]
    model = _state["model"]

    # small safeguard: limit length to avoid OOM; user can customize tokenizer args
    inputs = tokenizer(sequences, padding=True, truncation=True, return_tensors="pt")

    try:
        import torch
        device_t = torch.device(device if (device != "cpu" and torch.cuda.is_available()) else "cpu")
        inputs = {k: v.to(device_t) for k, v in inputs.items()}
        model.to(device_t)
        model.eval()
        with torch.no_grad():
            outputs = model(**inputs)
    except Exception as e:
        # Last resort: try CPU inference without moving tensors
        outputs = model(**inputs)

    # If classification model -> return outputs (logits exist)
    if _state["is_classification"] and hasattr(outputs, "logits"):
        return outputs

    # Else encoder-only: produce pooled embeddings (mean pooling)
    # We try last_hidden_state; shape (batch, seq_len, dim)
    last_hidden = getattr(outputs, "last_hidden_state", None)
    if last_hidden is None:
        # some models use hidden_states; try that
        hidden_states = getattr(outputs, "hidden_states", None)
        if hidden_states:
            last_hidden = hidden_states[-1]
    if last_hidden is None:
        raise RuntimeError("Could not obtain hidden states from model output.")

    # Convert to CPU numpy: mean pool over sequence length (ignoring attention mask if present)
    attn_mask = inputs.get("attention_mask", None)
    if attn_mask is not None:
        # compute masked mean
        mask = attn_mask.unsqueeze(-1).expand_as(last_hidden)
        summed = (last_hidden * mask).sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1)
        pooled = summed / counts
    else:
        pooled = last_hidden.mean(dim=1)

    try:
        pooled_np = pooled.cpu().numpy()
    except Exception:
        # fallback convert via numpy()
        pooled_np = np.array(pooled.detach().numpy())

    return {"embeddings": pooled_np}

def infer_labels_from_hf_output(raw_output: Any, top_k: int = 1) -> List[List[dict]]:
    """
    Convert raw_output into a list-of-list of label dicts:
      [ [ {"label": "xxx", "score": 0.9}, ... ], ... ]

    For classification models, uses softmax over logits and model.config.id2label if present.
    For encoder-only outputs (dict with 'embeddings'), returns Unknown label(s).
    """
    # classification branch
    try:
        import numpy as np
        if hasattr(raw_output, "logits"):
            logits = raw_output.logits.detach().cpu().numpy()
            # softmax
            exp = np.exp(logits - logits.max(axis=-1, keepdims=True))
            probs = exp / exp.sum(axis=-1, keepdims=True)
            id2label = getattr(raw_output.model.config, "id2label", None) if hasattr(raw_output, "model") else None
            if id2label is None:
                # sometimes model is not attached; try _state model's config
                cfg = getattr(_state.get("model"), "config", None)
                id2label = getattr(cfg, "id2label", None) if cfg is not None else None

            results = []
            for p in probs:
                top_idx = p.argsort()[::-1][:top_k]
                row = []
                for idx in top_idx:
                    label = id2label.get(idx, str(idx)) if isinstance(id2label, dict) else str(idx)
                    row.append({"label": label, "score": float(p[idx])})
                results.append(row)
            return results

        # embeddings branch
        if isinstance(raw_output, dict) and "embeddings" in raw_output:
            # We don't have a classifier -> return Unknown placeholders
            emb = raw_output["embeddings"]
            n = emb.shape[0]
            return [[{"label": "Unknown", "score": 0.0}] for _ in range(n)]
    except Exception as e:
        # if anything unexpected, return Unknown for each input
        try:
            n = raw_output["embeddings"].shape[0]
        except Exception:
            n = 1
        return [[{"label": "Unknown", "score": 0.0}] for _ in range(n)]

    # final fallback
    return [[{"label": "Unknown", "score": 0.0}]]
