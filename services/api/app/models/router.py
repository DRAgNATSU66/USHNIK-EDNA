import json
import os
from pathlib import Path
from fastapi import APIRouter

router = APIRouter(prefix="/models", tags=["models"])

# MODELS_REGISTRY_PATH env var lets Docker/Cloud Run point to a mounted registry.
# Falls back to walking up from this file (works in local dev).
def _resolve_registry_dir() -> Path:
    env_path = os.environ.get("MODELS_REGISTRY_PATH")
    if env_path:
        return Path(env_path)
    # Walk up from this file: models/router.py → app/ → api/ → services/ → repo root
    p = Path(__file__).resolve()
    for _ in range(10):
        candidate = p / "models" / "registry"
        if candidate.exists():
            return candidate
        if p.parent == p:
            break
        p = p.parent
    return Path("/app/models/registry")  # Docker default (empty if not mounted)

REGISTRY_DIR = _resolve_registry_dir()


@router.get("/status")
async def models_status():
    """Return current status of all known model routes."""
    return {
        "status": "ok",
        "routes": {
            "fish": {"status": "unavailable", "reason": "no_model_loaded"},
            "plant": {"status": "unavailable", "reason": "no_model_loaded"},
            "bacteria_pathogen": {"status": "unavailable", "reason": "no_model_loaded"},
            "animal_general": {"status": "unavailable", "reason": "no_model_loaded"},
            "human_domestic_contamination": {"status": "unavailable", "reason": "no_model_loaded"},
            "misc_unknown": {"status": "unavailable", "reason": "no_model_loaded"},
        },
        "note": "Models will be loaded after Phase 7 (DNA foundation model integration).",
    }


@router.get("/registry")
async def models_registry():
    """Return all model registry entries from models/registry/*.json."""
    entries = []
    if REGISTRY_DIR.exists():
        for f in sorted(REGISTRY_DIR.glob("*.json")):
            try:
                entries.append(json.loads(f.read_text()))
            except Exception:
                pass
    return {"models": entries, "count": len(entries)}
