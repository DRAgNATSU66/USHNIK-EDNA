from pathlib import Path, PurePosixPath
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from pydantic import BaseModel

from ..auth.deps import get_current_user
from ..models.user import UserProfile
from ..models.upload import UploadDoc, UploadStatus
from ..db import get_db
from ..config import get_settings

router = APIRouter(prefix="/uploads", tags=["uploads"])


class UploadMetadataForm(BaseModel):
    depth_meters: Optional[float] = None
    location_label: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source_type: Optional[str] = None
    habitat: Optional[str] = None
    salinity_ppt: Optional[float] = None
    temperature_celsius: Optional[float] = None


@router.post("", response_model=UploadDoc, status_code=status.HTTP_201_CREATED)
async def create_upload(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    file: UploadFile = File(...),
    depth_meters: Optional[float] = Form(None),
    location_label: Optional[str] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    source_type: Optional[str] = Form(None),
    habitat: Optional[str] = Form(None),
    salinity_ppt: Optional[float] = Form(None),
    temperature_celsius: Optional[float] = Form(None),
):
    """
    Upload a FASTA or JSON file for analysis.
    Returns an upload_id that can be used to create an analysis job.
    """
    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    if file.filename is None or not (
        file.filename.endswith(".fasta")
        or file.filename.endswith(".fa")
        or file.filename.endswith(".fastq")
        or file.filename.endswith(".json")
        or file.filename.endswith(".jsonl")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be FASTA (.fasta, .fa, .fastq) or JSON (.json, .jsonl)",
        )

    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_upload_size_mb}MB",
        )

    doc = UploadDoc(
        user_id=current_user.user_id,
        original_filename=file.filename,
        file_size_bytes=len(content),
        status=UploadStatus.stored,
        depth_meters=depth_meters,
        location_label=location_label,
        latitude=latitude,
        longitude=longitude,
        source_type=source_type,
        habitat=habitat,
        salinity_ppt=salinity_ppt,
        temperature_celsius=temperature_celsius,
    )

    # Persist to local disk so the worker's parser can read it. In production
    # this would upload to S3/GCS instead and set storage_key.
    storage_dir = Path(settings.upload_storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    safe_name = PurePosixPath(file.filename).name  # strip any path components
    dest = storage_dir / f"{doc.upload_id}_{safe_name}"
    dest.write_bytes(content)
    doc.file_path = str(dest)

    db = get_db()
    await db["uploads"].insert_one(doc.model_dump())

    return doc


@router.get("/{upload_id}", response_model=UploadDoc)
async def get_upload(
    upload_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    db = get_db()
    doc = await db["uploads"].find_one({"upload_id": upload_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")

    upload = UploadDoc(**{k: v for k, v in doc.items() if k != "_id"})

    # Users can only see their own uploads unless admin
    from ..models.user import UserRole
    if upload.user_id != current_user.user_id and current_user.role not in (
        UserRole.admin, UserRole.company_owner
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return upload
