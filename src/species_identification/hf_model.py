# src/species_identification/hf_model.py
import os
import sys
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN")

# optional: silence symlink warning on Windows
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
from transformers.utils import logging as hf_logging
hf_logging.set_verbosity_info()

MODEL_NAME = "zhihan1996/DNABERT-2-117M"

def _detect_cuda():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False

def load_hf_model(model_name: str = MODEL_NAME, trust_remote_code: bool = True) -> Dict[str, Any]:
    """
    Loads tokenizer + model and returns dict:
      {"pipeline": classifier_pipeline, "tokenizer": tokenizer, "model": model, "device": 'cpu'/'cuda', "id2label": {...}}
    Falls back to CPU mode on Windows / missing accelerator libs.
    """
    print(f"Loading Hugging Face model: {model_name}")
    # Pass your token if set (huggingface_hub also reads HF_TOKEN env)
    use_auth_token = HF_TOKEN if HF_TOKEN else None

    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=trust_remote_code, use_auth_token=use_auth_token)

    device_is_cuda = _detect_cuda()
    device_str = "cuda" if device_is_cuda else "cpu"

    model = None
    # Try normal load (may raise ImportError if model repo uses specialized libs)
    try:
        # keep it simple and safe: load to CPU first or to GPU if available
        if device_is_cuda:
            model = AutoModelForSequenceClassification.from_pretrained(model_name, trust_remote_code=trust_remote_code, use_auth_token=use_auth_token)
        else:
            model = AutoModelForSequenceClassification.from_pretrained(model_name, trust_remote_code=trust_remote_code, use_auth_token=use_auth_token, device_map="cpu")
    except Exception as e:
        # If error mentions triton or other GPU-only libs, fallback to CPU
        err = str(e).lower()
        print("Model load exception:", err)
        print("Attempting CPU-only fallback...")
        try:
            model = AutoModelForSequenceClassification.from_pretrained(model_name, trust_remote_code=trust_remote_code, use_auth_token=use_auth_token, device_map="cpu")
            device_str = "cpu"
        except Exception as e2:
            print("CPU fallback also failed:", e2)
            raise

    # Create pipeline with device=-1 for CPU or 0..n for GPU
    pipe_device = -1 if device_str == "cpu" else 0
    classifier_pipeline = pipeline("text-classification", model=model, tokenizer=tokenizer, device=pipe_device, trust_remote_code=trust_remote_code, use_auth_token=use_auth_token)

    # Build label mapping id2label -> make keys like "LABEL_0" => human-readable if possible
    id2label = {}
    try:
        cfg = getattr(model, "config", None)
        if cfg is not None and hasattr(cfg, "id2label"):
            # cfg.id2label may have numeric keys; produce mapping LABEL_{k} -> label
            for k, v in cfg.id2label.items():
                key = f"LABEL_{k}" if (isinstance(k, int) or (isinstance(k, str) and k.isdigit())) else str(k)
                id2label[str(key)] = v
    except Exception:
        pass

    return {"pipeline": classifier_pipeline, "tokenizer": tokenizer, "model": model, "device": device_str, "id2label": id2label}


def chunk_sequence(seq: str, max_len: int):
    if len(seq) <= max_len:
        return [seq]
    chunks = []
    for i in range(0, len(seq), max_len):
        chunks.append(seq[i:i+max_len])
    return chunks


def predict_sequences(bundle: Dict[str, Any], sequences: List[Dict[str, str]], max_tokens: int = 512):
    """
    bundle: output from load_hf_model() -> contains 'pipeline' and 'tokenizer'
    sequences: list of dicts {id, sequence}
    returns list of dicts {sequence_id, predicted_species (label), confidence}
    """
    pipeline_obj = bundle.get("pipeline")
    tokenizer = bundle.get("tokenizer")
    results = []

    if pipeline_obj is None or tokenizer is None:
        for i, rec in enumerate(sequences, start=1):
            seq_id = rec.get("id", f"seq{i}")
            results.append({"sequence_id": seq_id, "predicted_species": "Unknown", "confidence": 0.0})
        return results

    model_max = getattr(tokenizer, "model_max_length", max_tokens) or max_tokens
    max_len = min(model_max, max_tokens)

    for i, rec in enumerate(sequences, start=1):
        seq_id = rec.get("id", f"seq{i}")
        raw_seq = rec.get("sequence", "")
        seq = "".join(raw_seq.split()).upper()
        if not seq:
            results.append({"sequence_id": seq_id, "predicted_species": "EmptySequence", "confidence": 0.0})
            continue

        chunks = chunk_sequence(seq, max_len)
        chunk_preds = []
        for ch in chunks:
            try:
                out = pipeline_obj(ch[:max_len])
                if isinstance(out, list) and out:
                    chunk_preds.append(out[0])  # {'label': 'LABEL_0', 'score': 0.9}
            except Exception as e:
                print(f"Warning: pipeline error for {seq_id}: {e}")
                chunk_preds.append({"label": "Error", "score": 0.0})

        if not chunk_preds:
            results.append({"sequence_id": seq_id, "predicted_species": "Unknown", "confidence": 0.0})
            continue

        best = max(chunk_preds, key=lambda x: x.get("score", 0.0))
        label = best.get("label", "Unknown")
        score = float(best.get("score", 0.0))
        results.append({"sequence_id": seq_id, "predicted_species": label, "confidence": score})

    return results


if __name__ == "__main__":
    try:
        bundle = load_hf_model()
    except Exception as e:
        print("Failed to load HF model:", e)
        sys.exit(1)
    test = [{"id": "s1", "sequence": "ATGCGTACGTAGCTAGCTGACTGATCG"}]
    print(predict_sequences(bundle, test))