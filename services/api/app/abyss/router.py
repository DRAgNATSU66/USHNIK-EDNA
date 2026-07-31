"""
Abyss Mode API — Phase 10.

Endpoints:
  POST /abyss/expeditions               Create expedition (expedition_operator+)
  GET  /abyss/expeditions               List user's expeditions
  GET  /abyss/expeditions/{id}          Get expedition detail
  POST /abyss/expeditions/{id}/activate Mark as active (departed)
  GET  /abyss/expeditions/{id}/pack-manifest  Offline pack manifest
  POST /abyss/expeditions/{id}/license  Issue offline license JWT
  POST /abyss/analyze                   Run lightweight Abyss analysis
  POST /abyss/sync                      Sync offline data + queue re-analysis
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth.deps import get_current_user, require_role
from ..models.user import UserProfile, UserRole
from ..db import get_db
from .models import (
    AbyssAnalysisRequest,
    AbyssAnalysisResult,
    AbyssSyncRequest,
    AbyssSyncResult,
    ExpeditionDoc,
    ExpeditionStatus,
    ABYSS_DISCLAIMER,
)
from .offline_pack import (
    build_pack_manifest,
    generate_offline_license,
    validate_offline_license,
)
from .analysis import run_abyss_analysis

router = APIRouter(prefix="/abyss", tags=["abyss"])

_OPERATOR_ROLES = (
    UserRole.expedition_operator,
    UserRole.admin,
    UserRole.company_owner,
)


# ---------------------------------------------------------------------------
# Request bodies not already in models.py
# ---------------------------------------------------------------------------

class CreateExpeditionRequest(BaseModel):
    name: str
    description: Optional[str] = None
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    vessel: Optional[str] = None
    target_depth_meters: Optional[float] = None
    location_label: Optional[str] = None


class IssueLicenseRequest(BaseModel):
    duration_days: int = 14  # capped at 90 server-side


# ---------------------------------------------------------------------------
# Create expedition
# ---------------------------------------------------------------------------

@router.post("/expeditions", status_code=status.HTTP_201_CREATED)
async def create_expedition(
    body: CreateExpeditionRequest,
    current_user: Annotated[UserProfile, Depends(require_role(*_OPERATOR_ROLES))],
):
    """
    Create an Abyss Mode expedition.
    Returns the expedition record. Issue an offline license separately via
    POST /abyss/expeditions/{id}/license before departure.
    """
    db = get_db()
    expedition = ExpeditionDoc(
        name=body.name,
        description=body.description,
        created_by=current_user.user_id,
        planned_start=body.planned_start,
        planned_end=body.planned_end,
        vessel=body.vessel,
        target_depth_meters=body.target_depth_meters,
        location_label=body.location_label,
    )
    await db["abyss_expeditions"].insert_one(expedition.model_dump())

    return {
        **expedition.model_dump(),
        "disclaimer": ABYSS_DISCLAIMER,
        "next_steps": [
            f"GET /abyss/expeditions/{expedition.expedition_id}/pack-manifest — review offline pack",
            f"POST /abyss/expeditions/{expedition.expedition_id}/license — issue offline credential before departure",
        ],
    }


# ---------------------------------------------------------------------------
# List expeditions
# ---------------------------------------------------------------------------

@router.get("/expeditions")
async def list_expeditions(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    status_filter: Optional[str] = None,
    limit: int = 20,
    skip: int = 0,
):
    """List expeditions created by the current user (or all, for admin)."""
    db = get_db()
    query: dict = {}
    if current_user.role not in (UserRole.admin, UserRole.company_owner):
        query["created_by"] = current_user.user_id
    if status_filter:
        query["status"] = status_filter

    cursor = db["abyss_expeditions"].find(query).skip(skip).limit(limit)
    docs = []
    async for doc in cursor:
        doc.pop("_id", None)
        docs.append(doc)
    return {"expeditions": docs, "count": len(docs)}


# ---------------------------------------------------------------------------
# Get expedition detail
# ---------------------------------------------------------------------------

@router.get("/expeditions/{expedition_id}")
async def get_expedition(
    expedition_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    db = get_db()
    doc = await db["abyss_expeditions"].find_one({"expedition_id": expedition_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expedition not found")
    doc.pop("_id", None)

    if doc.get("created_by") != current_user.user_id and current_user.role not in (
        UserRole.admin, UserRole.company_owner
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return doc


# ---------------------------------------------------------------------------
# Activate expedition (mark as departed)
# ---------------------------------------------------------------------------

@router.post("/expeditions/{expedition_id}/activate")
async def activate_expedition(
    expedition_id: str,
    current_user: Annotated[UserProfile, Depends(require_role(*_OPERATOR_ROLES))],
):
    """Mark expedition as active (departed). Requires an offline license to have been issued."""
    db = get_db()
    doc = await db["abyss_expeditions"].find_one({"expedition_id": expedition_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expedition not found")

    if not doc.get("offline_license_issued"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Issue an offline license before activating. POST /abyss/expeditions/{id}/license",
        )

    await db["abyss_expeditions"].update_one(
        {"expedition_id": expedition_id},
        {"$set": {"status": ExpeditionStatus.active}},
    )
    await db["audit_logs"].insert_one({
        "action": "expedition_activated",
        "expedition_id": expedition_id,
        "actor_id": current_user.user_id,
        "timestamp": datetime.now(timezone.utc),
    })

    return {"ok": True, "expedition_id": expedition_id, "status": ExpeditionStatus.active}


# ---------------------------------------------------------------------------
# Offline pack manifest
# ---------------------------------------------------------------------------

@router.get("/expeditions/{expedition_id}/pack-manifest")
async def get_pack_manifest(
    expedition_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """Return the offline pack manifest for the expedition."""
    db = get_db()
    doc = await db["abyss_expeditions"].find_one({"expedition_id": expedition_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expedition not found")

    if doc.get("created_by") != current_user.user_id and current_user.role not in (
        UserRole.admin, UserRole.company_owner
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    expedition = ExpeditionDoc(**{k: v for k, v in doc.items() if k != "_id"})
    manifest = build_pack_manifest(expedition)
    return manifest.model_dump()


# ---------------------------------------------------------------------------
# Issue offline license
# ---------------------------------------------------------------------------

@router.post("/expeditions/{expedition_id}/license")
async def issue_offline_license(
    expedition_id: str,
    body: IssueLicenseRequest,
    current_user: Annotated[UserProfile, Depends(require_role(*_OPERATOR_ROLES))],
):
    """
    Generate and return a signed offline license JWT for the expedition.

    The token is presented with every POST /abyss/analyze call.
    Duration is capped at 90 days. Issue only once per expedition
    (re-issue is allowed but the old token remains valid until it expires).
    """
    db = get_db()
    doc = await db["abyss_expeditions"].find_one({"expedition_id": expedition_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expedition not found")

    if doc.get("created_by") != current_user.user_id and current_user.role not in (
        UserRole.admin, UserRole.company_owner
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    expedition = ExpeditionDoc(**{k: v for k, v in doc.items() if k != "_id"})
    token, expires_at = generate_offline_license(expedition, current_user.user_id, body.duration_days)

    await db["abyss_expeditions"].update_one(
        {"expedition_id": expedition_id},
        {"$set": {
            "offline_license_issued": True,
            "offline_license_expires_at": expires_at,
        }},
    )
    await db["audit_logs"].insert_one({
        "action": "offline_license_issued",
        "expedition_id": expedition_id,
        "actor_id": current_user.user_id,
        "expires_at": expires_at,
        "timestamp": datetime.now(timezone.utc),
    })

    return {
        "expedition_id": expedition_id,
        "offline_license_token": token,
        "expires_at": expires_at.isoformat(),
        "duration_days": min(body.duration_days, 90),
        "disclaimer": ABYSS_DISCLAIMER,
        "instructions": (
            "Store this token securely on your field device. "
            "Present it in every POST /abyss/analyze request. "
            "The token cannot be revoked once issued — keep it confidential."
        ),
    }


# ---------------------------------------------------------------------------
# Run lightweight Abyss analysis
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=AbyssAnalysisResult)
async def run_abyss_analysis_endpoint(
    body: AbyssAnalysisRequest,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """
    Run lightweight field-triage analysis on a batch of sequences.

    Validates the offline license, runs heuristic routing + novelty scoring
    (no foundation model — stub inference only), and returns preliminary results.

    All results carry requires_cloud_confirmation=True. After returning from
    the field, POST /abyss/sync to trigger full online re-analysis.
    """
    # Validate offline license
    license_payload = validate_offline_license(body.offline_license_token)
    if license_payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired offline license token.",
        )
    if license_payload.get("expedition_id") != body.expedition_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="License token does not match expedition_id.",
        )

    if not body.sequences:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No sequences provided.",
        )

    # Run analysis in thread pool (blocking CPU work)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        run_abyss_analysis,
        body.expedition_id,
        body.sequences,
    )

    # Store the abyss analysis result in MongoDB for sync later
    db = get_db()
    await db["abyss_analyses"].insert_one({
        **result.model_dump(),
        "user_id": current_user.user_id,
        "device_id": body.device_id,
        "local_timestamp": body.local_timestamp,
    })

    return result


# ---------------------------------------------------------------------------
# Sync offline data
# ---------------------------------------------------------------------------

@router.post("/sync", response_model=AbyssSyncResult)
async def sync_expedition(
    body: AbyssSyncRequest,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """
    Sync offline Abyss Mode data after returning online.

    Steps:
      1. Store offline audit logs.
      2. Store preliminary abyss analyses.
      3. Queue full re-analysis jobs for any upload_ids provided.
      4. Mark expedition as synced.

    The full re-analysis runs the complete pipeline (parsing → QC → routing →
    inference → novelty scoring) and produces a proper analysis result that
    supersedes the offline preliminary result.
    """
    db = get_db()
    expedition = await db["abyss_expeditions"].find_one({"expedition_id": body.expedition_id})
    if not expedition:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expedition not found")

    if expedition.get("created_by") != current_user.user_id and current_user.role not in (
        UserRole.admin, UserRole.company_owner
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    synced_at = datetime.now(timezone.utc)

    # 1. Store offline audit logs
    if body.local_logs:
        await db["abyss_expedition_logs"].insert_many([
            {**log, "expedition_id": body.expedition_id, "log_type": "audit", "synced_at": synced_at}
            for log in body.local_logs
        ])

    # 2. Store preliminary offline analyses
    if body.local_analyses:
        await db["abyss_expedition_logs"].insert_many([
            {
                **ana.model_dump(),
                "expedition_id": body.expedition_id,
                "log_type": "preliminary_analysis",
                "synced_at": synced_at,
            }
            for ana in body.local_analyses
        ])

    # 3. Queue full re-analysis jobs for each provided upload_id
    from ..models.job import AnalysisJobDoc, JobState
    from ..queue import enqueue_job

    job_ids: list[str] = []
    for upload_id in body.upload_ids_for_reanalysis:
        upload = await db["uploads"].find_one({"upload_id": upload_id})
        if not upload:
            continue  # skip missing uploads — don't fail the whole sync

        job = AnalysisJobDoc(
            upload_id=upload_id,
            user_id=current_user.user_id,
            mode="abyss_synced",
            state=JobState.queued,
        )
        await db["analysis_jobs"].insert_one(job.model_dump())
        try:
            await enqueue_job(job_id=job.job_id, upload_id=upload_id, mode="abyss_synced")
        except Exception:
            pass  # Redis unavailable — job stays in MongoDB for worker to poll
        job_ids.append(job.job_id)

    # 4. Mark expedition synced
    await db["abyss_expeditions"].update_one(
        {"expedition_id": body.expedition_id},
        {"$set": {
            "status": ExpeditionStatus.synced,
            "synced_at": synced_at,
            "sync_job_count": len(job_ids),
        }},
    )

    await db["audit_logs"].insert_one({
        "action": "expedition_synced",
        "expedition_id": body.expedition_id,
        "logs_stored": len(body.local_logs),
        "analyses_stored": len(body.local_analyses),
        "jobs_queued": len(job_ids),
        "actor_id": current_user.user_id,
        "timestamp": synced_at,
    })

    return AbyssSyncResult(
        ok=True,
        expedition_id=body.expedition_id,
        logs_stored=len(body.local_logs),
        analyses_stored=len(body.local_analyses),
        reanalysis_jobs_queued=len(job_ids),
        job_ids=job_ids,
    )
