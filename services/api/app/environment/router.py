"""
GET  /environment/uploads/{upload_id}          cached environmental context (Q5, t-1026-1)
POST /environment/uploads/{upload_id}/refresh  admin: re-fetch, bypassing the shared cache

Same access rule as GET /uploads/{upload_id}: the owner, or admin/company_owner.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from ..auth.deps import get_current_user, require_role
from ..config import get_settings
from ..db import get_db
from ..models.user import UserProfile, UserRole
from ..uploads.access import can_view_upload
from . import service
from .models import EnvironmentContextResponse

router = APIRouter(prefix="/environment", tags=["environment"])
logger = logging.getLogger("app.environment")


async def _load_upload(upload_id: str, user: UserProfile) -> dict:
    doc = await get_db()["uploads"].find_one({"upload_id": upload_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
    if not can_view_upload(doc.get("user_id"), user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return {k: v for k, v in doc.items() if k != "_id"}


@router.get("/uploads/{upload_id}", response_model=EnvironmentContextResponse)
async def get_environment_context(
    upload_id: str,
    background_tasks: BackgroundTasks,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """Per-variable status: ok (public value), user_provided (upload metadata
    wins; public value alongside) or unavailable (with the reason).

    Uploads that pre-date this service, or whose coordinates/date changed, or
    whose lookup died mid-run, get a lookup scheduled here (claimed with a
    conditional write so concurrent GETs schedule it once)."""
    upload = await _load_upload(upload_id, current_user)
    db = get_db()
    doc = await db[service.CONTEXTS].find_one({"upload_id": upload_id})
    built = service.build_query(upload)
    pending_reason = None

    if built is not None and service.needs_lookup(doc, built[1]):
        if not get_settings().environment_context_enabled:
            pending_reason = "Environmental lookups are disabled on this server (ENVIRONMENT_CONTEXT_ENABLED=false)."
        else:
            now = service._utcnow()
            # The query goes in with the claim so the next GET sees a matching,
            # fresh pending doc and does not schedule a second lookup.
            claim = {"status": "pending", "requested_at": now,
                     "query": built[1].model_dump(mode="json"), "cache_key": service.cache_key(built[0])}
            if doc is None:
                res = await db[service.CONTEXTS].update_one(
                    {"upload_id": upload_id},
                    {"$setOnInsert": {"upload_id": upload_id, "user_id": upload.get("user_id"), **claim}},
                    upsert=True,
                )
                claimed = getattr(res, "upserted_id", None) is not None
            else:
                res = await db[service.CONTEXTS].update_one(
                    {"upload_id": upload_id, "requested_at": doc.get("requested_at")},
                    {"$set": claim},
                )
                claimed = getattr(res, "modified_count", 0) == 1
            if claimed:
                background_tasks.add_task(service.run_lookup, upload_id)
            doc = await db[service.CONTEXTS].find_one({"upload_id": upload_id})
            if doc is not None:
                doc = {**doc, "status": "pending"}

    return service.build_response(upload, doc, pending_reason=pending_reason)


@router.post("/uploads/{upload_id}/refresh", response_model=EnvironmentContextResponse,
             status_code=status.HTTP_202_ACCEPTED)
async def refresh_environment_context(
    upload_id: str,
    background_tasks: BackgroundTasks,
    current_user: Annotated[UserProfile, Depends(require_role(UserRole.admin))],
):
    """Re-run the lookup for one upload, skipping the shared cache (admin)."""
    upload = await _load_upload(upload_id, current_user)
    if service.build_query(upload) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Upload has no {', '.join(service.missing_inputs(upload))}; nothing to look up",
        )
    background_tasks.add_task(service.run_lookup, upload_id, force=True)
    return service.build_response(upload, None, pending_reason="Refresh queued; skipping the shared cache.")
