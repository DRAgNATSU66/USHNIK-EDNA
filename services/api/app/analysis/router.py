from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth.deps import get_current_user
from ..models.user import UserProfile, UserRole
from ..models.job import AnalysisJobDoc, JobState
from ..models.analysis import AnalysisResultDoc
from ..db import get_db
from ..queue import enqueue_job
from ..uploads.context import MetadataContext, build_metadata_context

router = APIRouter(prefix="/analysis", tags=["analysis"])


class CreateJobRequest(BaseModel):
    upload_id: str
    mode: str = "online_full"  # "online_full" | "abyss_synced"


class CreateJobResponse(BaseModel):
    job_id: str
    upload_id: str
    state: JobState


@router.post("/jobs", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_analysis_job(
    body: CreateJobRequest,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """
    Create an analysis job for a previously uploaded file.
    The job is queued; poll GET /analysis/jobs/{job_id} for status.
    """
    db = get_db()

    upload = await db["uploads"].find_one({"upload_id": body.upload_id})
    if not upload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")

    if upload.get("user_id") != current_user.user_id and current_user.role not in (
        UserRole.admin, UserRole.company_owner
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    job = AnalysisJobDoc(
        upload_id=body.upload_id,
        user_id=current_user.user_id,
        mode=body.mode,
        state=JobState.queued,
    )
    await db["analysis_jobs"].insert_one(job.model_dump())

    # Push to Redis queue so the worker picks it up
    try:
        await enqueue_job(job_id=job.job_id, upload_id=job.upload_id, mode=job.mode)
    except Exception:
        # Redis not available in dev without Docker — job stays queued in Mongo
        pass

    return CreateJobResponse(job_id=job.job_id, upload_id=job.upload_id, state=job.state)


@router.get("/jobs/{job_id}", response_model=AnalysisJobDoc)
async def get_job(
    job_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    db = get_db()
    doc = await db["analysis_jobs"].find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    job = AnalysisJobDoc(**{k: v for k, v in doc.items() if k != "_id"})

    if job.user_id != current_user.user_id and current_user.role not in (
        UserRole.admin, UserRole.company_owner
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return job


class AnalysisResultWithContext(AnalysisResultDoc):
    # Q2/Q4: which optional upload metadata was provided vs missing. Built at
    # read time from the upload doc (app/uploads/context.py), never stored.
    context: MetadataContext


@router.get("/{analysis_id}", response_model=AnalysisResultWithContext)
async def get_analysis(
    analysis_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    db = get_db()
    doc = await db["analysis_results"].find_one({"analysis_id": analysis_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    result = AnalysisResultDoc(**{k: v for k, v in doc.items() if k != "_id"})

    if result.user_id != current_user.user_id and current_user.role not in (
        UserRole.admin, UserRole.company_owner, UserRole.curator
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    upload = await db["uploads"].find_one({"upload_id": result.upload_id})
    return AnalysisResultWithContext(
        **result.model_dump(), context=build_metadata_context(upload),
    )

