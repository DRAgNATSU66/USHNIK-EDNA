"""
Model wrapper / adapter layer.

Priority logic (dynamic):
 1) sandipan_local (models/sandipan_models.model_interface) if present
 2) Hugging Face helper (src.species_identification.hf_inference) if USE_HF=true
 3) models/species_clf.pkl (sklearn_local) if present
 4) Dummy fallback returning 'Unknown'

This file intentionally reads the USE_HF flag at runtime (not once at import) so
you can toggle the env var without restarting Python in many cases.
"""
import os
import typing as t
import importlib
import importlib.util
from abc import ABC, abstractmethod

def is_hf_enabled() -> bool:
    """Read USE_HF from environment at call time (dynamic)."""
    return os.getenv("USE_HF", "false").lower() in ("1", "true", "yes")


class ModelWrapperBase(ABC):
    @classmethod
    @abstractmethod
    def available(cls) -> bool:
        pass

    @classmethod
    @abstractmethod
    def load(cls, **kwargs) -> "ModelWrapperBase":
        pass

    @abstractmethod
    def predict_batch(self, sequences: t.List[t.Dict]) -> t.List[t.Dict]:
        pass


# -------------------------
# Sandipan wrapper
# -------------------------
class SandipanWrapper(ModelWrapperBase):
    def __init__(self, iface_module, model_obj):
        self.iface = iface_module
        self.model = model_obj

    @classmethod
    def available(cls) -> bool:
        try:
            spec = importlib.util.find_spec("models.sandipan_models.model_interface")
            return spec is not None
        except Exception:
            return False

    @classmethod
    def load(cls, model_path: str = "models/sandipan_models", **kwargs) -> "SandipanWrapper":
        module = importlib.import_module("models.sandipan_models.model_interface")
        model_obj = module.load(model_path)
        return cls(iface_module=module, model_obj=model_obj)

    def predict_batch(self, sequences: t.List[t.Dict]) -> t.List[t.Dict]:
        seqs = [s["sequence"] for s in sequences]
        results = self.iface.predict_batch(self.model, seqs)
        out = []
        for s, r in zip(sequences, results):
            out.append({
                "sequence_id": s.get("sequence_id"),
                "sequence": s.get("sequence"),
                "predicted_species": r.get("predicted_species") or r.get("label") or "Unknown",
                "confidence": float(r.get("confidence", 0.0)),
                "source": "sandipan_local",
            })
        return out


# -------------------------
# HF wrapper (lazy)
# -------------------------
class HFWrapper(ModelWrapperBase):
    def __init__(self, hf_module):
        self.hf = hf_module

    @classmethod
    def available(cls) -> bool:
        try:
            spec = importlib.util.find_spec("src.species_identification.hf_inference")
            return spec is not None
        except Exception:
            return False

    @classmethod
    def load(cls, **kwargs) -> "HFWrapper":
        hf_module = importlib.import_module("src.species_identification.hf_inference")
        return cls(hf_module)

    def predict_batch(self, sequences: t.List[t.Dict]) -> t.List[t.Dict]:
        seqs = [s["sequence"] for s in sequences]
        hf_results = self.hf.predict_batch(seqs)
        out = []
        for s, r in zip(sequences, hf_results):
            out.append({
                "sequence_id": s.get("sequence_id"),
                "sequence": s.get("sequence"),
                "predicted_species": r.get("predicted_species") or r.get("label") or "Unknown",
                "confidence": float(r.get("confidence", 0.0)),
                "source": "huggingface_api",
            })
        return out


# -------------------------
# Sklearn wrapper
# -------------------------
class SklearnWrapper(ModelWrapperBase):
    def __init__(self, model, vectorizer=None):
        self.model = model
        self.vectorizer = vectorizer

    @classmethod
    def available(cls) -> bool:
        return os.path.exists(os.path.join("models", "species_clf.pkl"))

    @classmethod
    def load(cls, path: str = os.path.join("models", "species_clf.pkl"), **kwargs) -> "SklearnWrapper":
        try:
            import joblib  # type: ignore
        except Exception as e:
            raise RuntimeError("joblib is required to load sklearn model") from e

        obj = joblib.load(path)
        if isinstance(obj, dict):
            model = obj.get("model")
            vectorizer = obj.get("vectorizer")
        else:
            model = obj
            vectorizer = None
        return cls(model=model, vectorizer=vectorizer)

    def predict_batch(self, sequences: t.List[t.Dict]) -> t.List[t.Dict]:
        texts = [s["sequence"] for s in sequences]
        try:
            X = self.vectorizer.transform(texts) if self.vectorizer else texts
        except Exception:
            X = texts
        try:
            preds = self.model.predict(X)
        except Exception:
            preds = ["Unknown"] * len(texts)
        probs = None
        try:
            if hasattr(self.model, "predict_proba"):
                probs = self.model.predict_proba(X)
        except Exception:
            probs = None

        out = []
        for i, s in enumerate(sequences):
            predicted = str(preds[i])
            confidence = float(max(probs[i]) if probs is not None else 0.0)
            out.append({
                "sequence_id": s.get("sequence_id"),
                "sequence": s.get("sequence"),
                "predicted_species": predicted,
                "confidence": confidence,
                "source": "sklearn_local",
            })
        return out


# -------------------------
# Dummy fallback
# -------------------------
class DummyWrapper(ModelWrapperBase):
    @classmethod
    def available(cls) -> bool:
        return True

    @classmethod
    def load(cls, **kwargs) -> "DummyWrapper":
        return cls()

    def predict_batch(self, sequences):
        return [{
            "sequence_id": s.get("sequence_id"),
            "sequence": s.get("sequence"),
            "predicted_species": "Unknown",
            "confidence": 0.0,
            "source": "none",
        } for s in sequences]


# -------------------------
# get_best_model: orchestrates priority (evaluates USE_HF dynamically)
# -------------------------
def get_best_model() -> ModelWrapperBase:
    # 1) sandipan_local
    try:
        if SandipanWrapper.available():
            return SandipanWrapper.load()
    except Exception as e:
        print("SandipanWrapper failed to load:", e)

    # 2) HF (if allowed at call time)
    try:
        if is_hf_enabled() and HFWrapper.available():
            return HFWrapper.load()
    except Exception as e:
        print("HFWrapper failed to load:", e)

    # 3) sklearn_local
    try:
        if SklearnWrapper.available():
            return SklearnWrapper.load()
    except Exception as e:
        print("SklearnWrapper failed to load:", e)

    # 4) fallback
    return DummyWrapper.load()
