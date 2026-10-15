from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status

from ..auth.deps import get_current_user
from ..models.user import UserProfile
from ..models.upload import UploadDoc, UploadStatus
from ..db import get_db
from ..config import get_settings

router = APIRouter(prefix="/uploads", tags=["uploads"])

# A collection timestamp this far past "now" is a typo, not clock skew.
_COLLECTED_AT_FUTURE_TOLERANCE = timedelta(days=1)


def _clean_text(value: Optional[str]) -> Optional[str]:
    """Blank or whitespace-only form text means "not provided", not ""."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _validation_error(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


@router.post("", response_model=UploadDoc, status_code=status.HTTP_201_CREATED)
async def create_upload(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    file: UploadFile = File(...),
    # Every metadata field is optional (decisions.md 2026-10-14, Q2); the
    # list of them lives in models/upload.py OPTIONAL_METADATA_FIELDS.
    collected_at: Optional[datetime] = Form(None),
    depth_meters: Optional[float] = Form(None, ge=0),
    location_label: Optional[str] = Form(None, max_length=200),
    latitude: Optional[float] = Form(None, ge=-90, le=90),
    longitude: Optional[float] = Form(None, ge=-180, le=180),
    source_type: Optional[str] = Form(None, max_length=100),
    habitat: Optional[str] = Form(None, max_length=200),
    salinity_ppt: Optional[float] = Form(None),
    temperature_celsius: Optional[float] = Form(None),
    dissolved_oxygen_mg_l: Optional[float] = Form(None, ge=0),
    ph: Optional[float] = Form(None, ge=0, le=14),
    methodology: Optional[str] = Form(None, max_length=200),
    negative_control_included: Optional[bool] = Form(None),
    collector: Optional[str] = Form(None, max_length=200),
):
    """
    Upload a FASTA or JSON file for analysis.
    Returns an upload_id that can be used to create an analysis job.

    Only `file` is required. Coordinates must be sent as a pair. A partner
    report additionally needs `collected_at` + coordinates; results state
    which optional fields were provided (see app/uploads/context.py).
    """
    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    if (latitude is None) != (longitude is None):
        raise _validation_error("latitude and longitude must be provided together")

    if collected_at is not None:
        # Naive timestamps are compared as UTC; they are stored as sent.
        aware = collected_at if collected_at.tzinfo else collected_at.replace(tzinfo=timezone.utc)
        if aware > datetime.now(timezone.utc) + _COLLECTED_AT_FUTURE_TOLERANCE:
            raise _validation_error("collected_at cannot be in the future")

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
        collected_at=collected_at,
        depth_meters=depth_meters,
        location_label=_clean_text(location_label),
        latitude=latitude,
        longitude=longitude,
        source_type=_clean_text(source_type),
        habitat=_clean_text(habitat),
        salinity_ppt=salinity_ppt,
        temperature_celsius=temperature_celsius,
        dissolved_oxygen_mg_l=dissolved_oxygen_mg_l,
        ph=ph,
        methodology=_clean_text(methodology),
        negative_control_included=negative_control_included,
        collector=_clean_text(collector),
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
