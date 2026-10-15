"""
/models endpoints: the model registry and a per-route readiness view built from it.

The API is a separate process from the GPU worker and the worker publishes no
state (no Redis heartbeat, no loaded-model list), so /models/status cannot know
what the worker has actually loaded. It reports what *can* be known from here:
the registry entry the worker will select for each route, whether that entry's
artifacts resolve on disk, the registry's own metrics, and the inference mode
the worker's code path implies. It never claims a model is "loaded".

The selection and path-resolution rules below mirror the worker
(services/worker/app/inference/registry.py, loader.py, predictor.py). The two
services ship as separate images with no shared Python package, so the logic is
duplicated deliberately and kept small; if the worker's rules change, change
these too.
"""
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter

from .analysis import TaxonomicRoute

logger = logging.getLogger(__name__)

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

# Same convention as the worker: "data:<relative path>" is relative to the data
# root (SYNTHVEDA_DATA_ROOT, else a synthveda-data/ dir found walking up, else
# /data). Anything else is a HF Hub id or a plain path.
DATA_URI_PREFIX = "data:"

# Fields the worker's registry parser indexes directly (registry._parse_entry);
# a file missing any of them is dropped by the worker, so it is an error here.
_REQUIRED_FIELDS = ("model_id", "route", "base_model")

# Worker registry tier order (registry.ModelRegistry.for_route).
_TIER_ORDER = {"experimental": 0, "staging": 1, "production": 2, "retired": -1}

# Routes that get a model. low_quality sequences never reach inference
# (predictor.run_inference short-circuits them).
MODEL_ROUTES = [r.value for r in TaxonomicRoute if r != TaxonomicRoute.low_quality]


def _resolve_data_root() -> Path:
    env_path = os.environ.get("SYNTHVEDA_DATA_ROOT")
    if env_path:
        return Path(env_path)
    p = Path(__file__).resolve()
    for _ in range(10):
        candidate = p / "synthveda-data"
        if candidate.exists():
            return candidate
        if p.parent == p:
            break
        p = p.parent
    return Path("/data")  # Docker default (mount synthveda-data here)


def _load_registry(registry_dir: Path) -> tuple[list[tuple[str, dict]], list[dict]]:
    """
    Read every *.json in the registry dir.

    Returns (entries, errors): entries as (filename, parsed dict) pairs, and one
    {"file", "error"} record per file that is not valid JSON, is not an object,
    or lacks a field the worker requires. Bad files are logged and reported,
    never silently dropped.
    """
    entries: list[tuple[str, dict]] = []
    errors: list[dict] = []
    if not registry_dir.exists():
        logger.warning("Model registry directory not found: %s", registry_dir)
        return entries, errors

    for f in sorted(registry_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"expected a JSON object, got {type(data).__name__}")
            missing = [k for k in _REQUIRED_FIELDS if not data.get(k)]
            if missing:
                raise ValueError(f"missing required field(s): {', '.join(missing)}")
        except Exception as exc:
            logger.warning("Malformed model registry file %s: %s", f.name, exc)
            errors.append({"file": f.name, "error": str(exc)})
            continue
        entries.append((f.name, data))
    return entries, errors


def _is_runnable(entry: dict) -> bool:
    # Mirrors ModelRegistryEntry.is_runnable.
    return entry.get("artifact_uri") is not None and entry.get("status", "experimental") != "retired"


def _select_entry(route: str, entries: list[dict]) -> dict | None:
    """Mirror of ModelRegistry.best_available: production > staging > experimental,
    newest created_at within a tier, runnable entries only."""
    for tier in ("production", "staging", "experimental"):
        min_rank = _TIER_ORDER[tier]
        candidates = [
            e for e in entries
            if e["route"] == route
            and _TIER_ORDER.get(e.get("status", "experimental"), -1) >= min_rank
            and _is_runnable(e)
        ]
        if candidates:
            return max(candidates, key=lambda e: e.get("created_at", ""))
    return None


def _backbone_info(uri: str, data_root: Path) -> dict:
    """Where the worker's loader will look for the backbone (loader._resolve_local)."""
    if uri.startswith(DATA_URI_PREFIX):
        path = data_root / uri[len(DATA_URI_PREFIX):]
        return {"uri": uri, "source": "local", "present": path.exists()}
    if Path(uri).exists():
        return {"uri": uri, "source": "local", "present": True}
    # Not on disk: the worker hands it to transformers as a Hub id. Whether
    # that download works is not observable from the API.
    return {"uri": uri, "source": "hub", "present": None}


def _head_info(uri: str, data_root: Path) -> dict:
    """The worker only loads head weights from a .pt/.bin path (predictor._run_model)."""
    if uri.startswith(DATA_URI_PREFIX):
        path = data_root / uri[len(DATA_URI_PREFIX):]
    else:
        path = Path(uri)
    loadable_format = uri.endswith((".pt", ".bin"))
    return {
        "uri": uri,
        "source": "local",
        "present": loadable_format and path.is_file(),
    }


def _route_status(route: str, entries: list[dict], data_root: Path) -> dict:
    route_entries = [e for e in entries if e["route"] == route]
    registered = [e["model_id"] for e in route_entries]
    entry = _select_entry(route, entries)

    if entry is None:
        return {
            "status": "no_model",
            "reason": "no_runnable_registry_entry" if registered else "no_registry_entry",
            "model_id": None,
            "registered_model_ids": registered,
            "inference_mode": "stub",
        }

    backbone = _backbone_info(entry["base_model"], data_root)
    head = _head_info(entry["artifact_uri"], data_root)
    warnings: list[str] = []

    if backbone["present"] is False:
        # Loader cannot find it locally, tries it as a Hub id, fails, worker stubs.
        status, reason, mode = "missing_artifacts", "backbone_not_found", "stub"
    elif not head["present"]:
        # heads.get_head logs a warning and falls back to a randomly initialised
        # head; predictor still labels those results inference_mode="model".
        status, reason, mode = "missing_artifacts", "head_weights_not_found", "model"
        warnings.append(
            "head weights not found: the worker will run a randomly initialised head "
            "and still label results inference_mode=model"
        )
    elif backbone["present"] is None:
        status, reason, mode = "unverified", "backbone_from_hub", "model"
        warnings.append("backbone is a Hub id; availability depends on the worker's network/cache")
    else:
        status, reason, mode = "ready", "artifacts_resolved", "model"

    out = {
        "status": status,
        "reason": reason,
        "model_id": entry["model_id"],
        "registry_status": entry.get("status", "experimental"),
        "label_set_version": entry.get("label_set_version"),
        "training_dataset_version": entry.get("training_dataset_version"),
        "created_at": entry.get("created_at"),
        "registered_model_ids": registered,
        "artifacts": {"backbone": backbone, "head": head},
        "metrics": entry.get("metrics") or {},
        "inference_mode": mode,
    }
    if warnings:
        out["warnings"] = warnings
    return out


@router.get("/status")
async def models_status():
    """Per-route model readiness, derived from the registry and the data root on disk."""
    parsed, errors = _load_registry(REGISTRY_DIR)
    entries = [d for _, d in parsed]
    data_root = _resolve_data_root()
    return {
        "status": "ok",
        "routes": {route: _route_status(route, entries, data_root) for route in MODEL_ROUTES},
        "errors": errors,
        "data_root": str(data_root),
        "worker_state": "not_observable",
        "note": (
            "Derived from models/registry and the data root as seen by the API process. "
            "'ready' means the selected entry's backbone and head resolve on disk; it does "
            "not mean the worker has loaded them. The worker publishes no state, and falls "
            "back to stub inference if torch is not installed in its environment or its "
            "data root differs from the API's."
        ),
    }


@router.get("/registry")
async def models_registry():
    """Return all model registry entries from models/registry/*.json, plus any files that failed to parse."""
    parsed, errors = _load_registry(REGISTRY_DIR)
    entries = [d for _, d in parsed]
    return {"models": entries, "count": len(entries), "errors": errors}
