from .models import PredictionResult, InferenceMode
from .registry import ModelRegistry

__all__ = [
    "run_inference",
    "run_inference_batch",
    "PredictionResult",
    "InferenceMode",
    "ModelRegistry",
]


def __getattr__(name: str):
    # The predictor pulls in torch, transformers and sklearn (~680 MB RSS,
    # ~3 s). Importing it lazily keeps `app.inference.models` light for the
    # training scripts that only need the label enums (build_reference_db,
    # build_dataset; QNA-048).
    if name in ("run_inference", "run_inference_batch"):
        from . import predictor
        return getattr(predictor, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
