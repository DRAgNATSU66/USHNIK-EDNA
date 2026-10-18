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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ..auth.deps import require_role
from ..db import get_db
from ..db.supabase_client import SupabaseClient
from . import promotion as promo
from .analysis import TaxonomicRoute
from .user import UserProfile, UserRole

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

# Worker registry tier order (registry.STATUS_RANK). "candidate" (written by
# POST /models/register) ranks below every serving tier: registered, not served.
_TIER_ORDER = {"candidate": -1, "experimental": 0, "staging": 1, "production": 2, "retired": -1}

# Routes that get a model. low_quality sequences never reach inference
# (predictor.run_inference short-circuits them).
MODEL_ROUTES = [r.value for r in TaxonomicRoute if r != TaxonomicRoute.low_quality]

# Routes a registry entry may name: the six route models plus the learned
# router (QNA-010), which the worker finds as the entry with "route": "router".
REGISTRY_ROUTES = MODEL_ROUTES + [promo.ROUTER_ROUTE]

# Same set the review/curation admin endpoints accept.
_ADMIN_ROLES = (UserRole.admin, UserRole.company_owner)


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
        # heads.get_head refuses to build a randomly initialised head; the
        # predictor returns stubs with stub_reason="head_missing".
        status, reason, mode = "missing_artifacts", "head_weights_not_found", "stub"
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
        # Unauthenticated endpoint: say whether the data root exists, not where it is.
        "data_root_found": data_root.is_dir(),
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
    """
    Return all model registry entries from models/registry/*.json, plus any files
    that failed to parse, and for each route (router included) the model_id the
    worker would select.
    """
    parsed, errors = _load_registry(REGISTRY_DIR)
    entries = [d for _, d in parsed]
    selected = {}
    for route in REGISTRY_ROUTES:
        e = _select_entry(route, entries)
        selected[route] = e["model_id"] if e else None
    return {"models": entries, "count": len(entries), "errors": errors, "selected_by_route": selected}


# ---------------------------------------------------------------------------
# Registration and promotion (B8). Representation and rationale:
# app/models/promotion.py module docstring.
# ---------------------------------------------------------------------------

class RegisterModelRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), extra="forbid")

    model_id: str
    route: str
    base_model: str
    artifact_uri: str = Field(description="data:<relative path> to the head (.pt/.bin) or router (.npz)")
    checksum: str = Field(description="SHA-256 of the artifact file; verified against the file on disk")
    metrics: dict[str, Any]
    label_set_version: str
    training_dataset_version: str
    label_set: list[str] = []
    head_type: Optional[str] = None
    embedding_dim: int = 768
    thresholds: dict[str, float] = {"high_confidence": 0.75, "low_confidence": 0.4}
    trusted_remote_code: bool = False
    created_at: Optional[str] = None  # YYYY-MM-DD the model was trained; default today (UTC)
    notes: Optional[str] = None


class PromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # true: validate and return the plan (current model, deltas, demotions)
    # without writing anything. The Admin page's confirmation step uses this.
    dry_run: bool = False
    # The model_id the caller saw serving the route when it decided (null for
    # "none"). If the route changed since, the promotion is refused with 409.
    # Omit to skip the check (make train-promote does).
    expected_current_model_id: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


def _raise(exc: promo.RegistryError):
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _actor(user: UserProfile) -> dict:
    return {"actor_id": user.user_id, "actor_email": user.email, "actor_role": str(user.role)}


def _registry_dir_writable() -> Path:
    if not REGISTRY_DIR.is_dir():
        raise promo.RegistryError(503, "model registry directory not found on the API host")
    if not os.access(REGISTRY_DIR, os.W_OK):
        raise promo.RegistryError(503, "model registry directory is read-only on the API host")
    return REGISTRY_DIR


async def _mirror_to_supabase(entry: dict, status: str, promoted_by: str | None = None) -> str:
    """
    Mirror a registry entry into Supabase model_versions + model_eval_metrics
    (migration 20260526000001) and, for a promotion (promoted_by set), make it
    the route's production row there too.

    Best-effort, like the review and training-batch mirrors: the registry file
    is what the worker serves from and MongoDB audit_logs/model_eval_metrics is
    the required record, so a Supabase outage does not undo or block a
    promotion. The outcome is returned to the caller ("written",
    "not_configured", "failed") and a failure is logged with its traceback.
    Called under the registry lock so mirrors land in promotion order.
    """
    try:
        SupabaseClient._get()
    except RuntimeError:
        return "not_configured"
    try:
        batch_uuid = None
        if entry.get("training_dataset_version"):
            batch_uuid = await SupabaseClient.get_training_batch_uuid(entry["training_dataset_version"])
        row = await SupabaseClient.register_model_version({
            "model_id": entry["model_id"],
            "route": entry["route"],
            "base_model": entry["base_model"],
            "training_batch_id": batch_uuid,
            "artifact_uri": entry.get("artifact_uri"),
            "checksum": entry.get("checksum"),
            "metrics": entry.get("metrics") or {},
            "thresholds": entry.get("thresholds") or {},
            "status": status,
        })
        for eval_set, eval_row in promo.eval_metric_rows(entry.get("metrics")):
            await SupabaseClient.upsert_eval_metrics(row["id"], eval_set, eval_row)
        if promoted_by is not None:
            await SupabaseClient.promote_model(entry["model_id"], promoted_by)
    except Exception:
        logger.warning("Supabase mirror of model %s failed; registry and MongoDB records are written",
                       entry.get("model_id"), exc_info=True)
        return "failed"
    return "written"


@router.post("/register", status_code=201)
async def register_model(
    body: RegisterModelRequest,
    current_user: Annotated[UserProfile, Depends(require_role(*_ADMIN_ROLES))],
):
    """
    Add a trained model to the registry as status "candidate".

    Validates the model_id, route, required metrics, and the artifact: it must
    be a data: path under the data root whose SHA-256 equals `checksum`. A
    candidate is never served; POST /models/{model_id}/promote makes it serve.
    """
    try:
        if not promo.MODEL_ID_RE.match(body.model_id):
            raise promo.RegistryError(422, "model_id must be 3-64 chars of a-z, 0-9, '_', '.', '-'")
        if body.route not in REGISTRY_ROUTES:
            raise promo.RegistryError(422, f"route must be one of {REGISTRY_ROUTES}")
        problems = promo.metric_problems(body.metrics)
        if problems:
            raise promo.RegistryError(422, "; ".join(problems))
        created_at = body.created_at or date.today().isoformat()
        if not promo.DATE_RE.match(created_at):
            raise promo.RegistryError(422, "created_at must be YYYY-MM-DD")

        data_root = _resolve_data_root()
        entry = {
            "model_id": body.model_id,
            "route": body.route,
            "base_model": body.base_model,
            "head_type": body.head_type or (
                "route_classification" if body.route == promo.ROUTER_ROUTE else "sequence_classification"
            ),
            "embedding_dim": body.embedding_dim,
            "label_set_version": body.label_set_version,
            "label_set": body.label_set,
            "training_dataset_version": body.training_dataset_version,
            "metrics": body.metrics,
            "thresholds": body.thresholds,
            "artifact_uri": body.artifact_uri,
            "checksum": body.checksum.lower(),
            "created_at": created_at,
            "promoted_by": None,
            "status": promo.CANDIDATE_STATUS,
            "notes": body.notes,
            "trusted_remote_code": body.trusted_remote_code,
        }
        promo.check_base_model(entry, data_root)
        await promo.verify_artifact(entry, data_root)

        registry_dir = _registry_dir_writable()
        now = _now_iso()
        entry["registered_by"] = current_user.user_id
        entry["registered_at"] = now
        target = registry_dir / f"{body.model_id}.json"

        async with promo.registry_lock(registry_dir):
            parsed, _errors = _load_registry(registry_dir)
            if target.exists() or any(d["model_id"] == body.model_id for _, d in parsed):
                raise promo.RegistryError(409, f"model_id {body.model_id!r} is already registered")
            promo.write_json_atomic(target, entry)
            try:
                await get_db()["audit_logs"].insert_one({
                    "action": "model_registered",
                    "model_id": body.model_id,
                    "route": body.route,
                    "registry_file": target.name,
                    "checksum": entry["checksum"],
                    "artifact_uri": body.artifact_uri,
                    "training_dataset_version": body.training_dataset_version,
                    "metrics": body.metrics,
                    **_actor(current_user),
                    "timestamp": datetime.now(timezone.utc),
                })
            except Exception:
                # No audit record, no registration.
                promo.restore_text(target, None)
                logger.exception("audit write for registration of %s failed; registry file removed", body.model_id)
                raise promo.RegistryError(503, "audit log unavailable; registration not recorded")
            selected = _select_entry(body.route, [d for _, d in _load_registry(registry_dir)[0]])
            mirror = await _mirror_to_supabase(entry, promo.CANDIDATE_STATUS)
    except promo.RegistryError as exc:
        _raise(exc)

    logger.info("Model %s registered as candidate on route %s by %s", body.model_id, body.route, current_user.user_id)
    return {
        "ok": True,
        "model": entry,
        "registry_file": target.name,
        "serving_model_id": selected["model_id"] if selected else None,
        "supabase_mirror": mirror,
    }


def _promotion_plan(model_id: str, parsed: list[tuple[str, dict]]) -> dict:
    """Work out a promotion against the registry as it is now; writes nothing."""
    by_id: dict[str, list[tuple[str, dict]]] = {}
    for name, d in parsed:
        by_id.setdefault(d["model_id"], []).append((name, d))
    if model_id not in by_id:
        raise promo.RegistryError(404, f"model {model_id!r} is not in the registry")
    if len(by_id[model_id]) > 1:
        files = ", ".join(n for n, _ in by_id[model_id])
        raise promo.RegistryError(409, f"model_id {model_id!r} appears in more than one registry file ({files})")
    file_name, entry = by_id[model_id][0]
    route = entry["route"]
    status = entry.get("status", "experimental")
    if status == "production":
        raise promo.RegistryError(409, f"{model_id} is already the production model for route {route}")
    if status == "retired":
        raise promo.RegistryError(409, f"{model_id} is retired; register a new version instead")
    if route not in REGISTRY_ROUTES:
        raise promo.RegistryError(422, f"{model_id} has route {route!r}, which no worker stage reads")
    problems = promo.metric_problems(entry.get("metrics"))
    if problems:
        raise promo.RegistryError(422, f"{model_id}: " + "; ".join(problems))

    entries = [d for _, d in parsed]
    current = _select_entry(route, entries)
    demote = [
        (name, d) for name, d in parsed
        if d["route"] == route and d.get("status") == "production" and d["model_id"] != model_id
    ]
    compare_to = current if current is not None and current["model_id"] != model_id else None
    return {
        "file_name": file_name,
        "entry": entry,
        "route": route,
        "current": current,
        "demote": demote,
        "deltas": promo.metric_deltas(entry, compare_to),
        "warnings": promo.comparability_warnings(entry, compare_to),
    }


def _plan_summary(model_id: str, plan: dict) -> dict:
    cur = plan["current"]
    return {
        "model_id": model_id,
        "route": plan["route"],
        "from_status": plan["entry"].get("status", "experimental"),
        "current_model_id": cur["model_id"] if cur else None,
        "current_status": cur.get("status", "experimental") if cur else None,
        "demoted_model_ids": [d["model_id"] for _, d in plan["demote"]],
        "metric_deltas": plan["deltas"],
        "warnings": plan["warnings"],
    }


@router.post("/{model_id}/promote")
async def promote_model(
    model_id: str,
    body: PromoteRequest,
    current_user: Annotated[UserProfile, Depends(require_role(*_ADMIN_ROLES))],
):
    """
    Make a registered model the one the worker serves for its route.

    Sets the entry's status to "production" and demotes any other production
    entry on that route to "staging", so each route has one promoted model.
    The artifact checksum is re-verified first. Each promotion writes a
    model_eval_metrics document and an audit_logs document; if either write
    fails, the registry files are restored and the promotion is refused.
    """
    try:
        registry_dir = REGISTRY_DIR
        data_root = _resolve_data_root()
        if not body.dry_run:
            _registry_dir_writable()
        async with promo.registry_lock(registry_dir) if not body.dry_run else _nolock():
            parsed, _errors = _load_registry(registry_dir)
            plan = _promotion_plan(model_id, parsed)
            promo.check_base_model(plan["entry"], data_root)
            checksum = await promo.verify_artifact(plan["entry"], data_root)
            summary = _plan_summary(model_id, plan)

            if "expected_current_model_id" in body.model_fields_set and \
                    body.expected_current_model_id != summary["current_model_id"]:
                raise promo.RegistryError(
                    409,
                    f"route {plan['route']} is now served by {summary['current_model_id']!r}, not "
                    f"{body.expected_current_model_id!r}; reload and review the comparison again",
                )
            if body.dry_run:
                return {"ok": True, "dry_run": True, **summary}

            now = _now_iso()
            originals: dict[Path, str] = {}

            def write(name: str, data: dict) -> None:
                path = registry_dir / name
                originals.setdefault(path, path.read_text(encoding="utf-8"))
                promo.write_json_atomic(path, data)

            inserted: list[tuple[str, Any]] = []
            try:
                # Demote first: a crash between the two writes leaves the route
                # on its previous model (now staging), never on two productions.
                for name, d in plan["demote"]:
                    write(name, {**d, "status": "staging", "demoted_at": now,
                                 "demoted_by": current_user.user_id, "demoted_for": model_id})
                write(plan["file_name"], {**plan["entry"], "status": "production",
                                          "promoted_by": current_user.user_id, "promoted_at": now,
                                          "promoted_from_status": summary["from_status"]})

                after = _select_entry(plan["route"], [d for _, d in _load_registry(registry_dir)[0]])
                if after is None or after["model_id"] != model_id:
                    raise _PostCheckFailed(
                        f"post-check failed: route {plan['route']} selects "
                        f"{after['model_id'] if after else None}, not {model_id}"
                    )

                db = get_db()
                metrics = plan["entry"].get("metrics") or {}
                res = await db["model_eval_metrics"].insert_one({
                    "model_id": model_id,
                    "route": plan["route"],
                    "eval_set": "test",
                    "event": "promotion",
                    "accuracy": metrics.get("test_accuracy"),
                    "f1_macro": metrics.get("test_macro_f1"),
                    "n": metrics.get("test_size"),
                    "metrics": metrics,
                    "checksum": checksum,
                    "training_dataset_version": plan["entry"].get("training_dataset_version"),
                    "label_set_version": plan["entry"].get("label_set_version"),
                    "compared_to_model_id": summary["current_model_id"],
                    "metric_deltas": summary["metric_deltas"],
                    "recorded_by": current_user.user_id,
                    "recorded_at": datetime.now(timezone.utc),
                })
                inserted.append(("model_eval_metrics", res.inserted_id))
                res = await db["audit_logs"].insert_one({
                    "action": "model_promoted",
                    "model_id": model_id,
                    "route": plan["route"],
                    "from_status": summary["from_status"],
                    "to_status": "production",
                    "previous_model_id": summary["current_model_id"],
                    "previous_status": summary["current_status"],
                    "demoted_model_ids": summary["demoted_model_ids"],
                    "checksum": checksum,
                    "metrics": metrics,
                    "metric_deltas": summary["metric_deltas"],
                    "warnings": summary["warnings"],
                    "notes": body.notes,
                    **_actor(current_user),
                    "timestamp": datetime.now(timezone.utc),
                })
                inserted.append(("audit_logs", res.inserted_id))
            except Exception as exc:
                for path, text in originals.items():
                    promo.restore_text(path, text)
                for coll, _id in inserted:
                    try:
                        await get_db()[coll].delete_one({"_id": _id})
                    except Exception:
                        logger.exception("could not remove %s %s after a failed promotion", coll, _id)
                logger.exception("promotion of %s failed; registry restored", model_id)
                if isinstance(exc, _PostCheckFailed):
                    raise promo.RegistryError(500, str(exc))
                raise promo.RegistryError(503, "audit/metrics store unavailable; promotion rolled back")
            mirror = await _mirror_to_supabase(
                {**plan["entry"], "checksum": checksum}, summary["from_status"], promoted_by=current_user.user_id,
            )
    except promo.RegistryError as exc:
        _raise(exc)

    logger.info("Model %s promoted to production on route %s by %s (was %s)",
                model_id, plan["route"], current_user.user_id, summary["current_model_id"])
    return {"ok": True, "dry_run": False, "promoted_at": now, "serving_model_id": model_id,
            "supabase_mirror": mirror, **summary}


class _PostCheckFailed(Exception):
    """After writing, the registry does not select the promoted model."""


class _nolock:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


@router.get("/promotions")
async def list_promotions(
    current_user: Annotated[UserProfile, Depends(require_role(*_ADMIN_ROLES))],
    limit: int = Query(20, ge=1, le=200),
):
    """Most recent registration and promotion audit records, newest first."""
    cursor = (
        get_db()["audit_logs"]
        .find({"action": {"$in": ["model_registered", "model_promoted"]}}, {"_id": 0})
        .sort("timestamp", -1)
        .limit(limit)
    )
    return {"events": [doc async for doc in cursor]}
