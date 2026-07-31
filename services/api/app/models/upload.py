from datetime import datetime
from enum import StrEnum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class UploadStatus(StrEnum):
    pending = "pending"
    stored = "stored"
    failed = "failed"


class UploadDoc(BaseModel):
    upload_id: str = Field(default_factory=lambda: f"upl_{uuid.uuid4().hex[:16]}")
    user_id: Optional[str] = None
    original_filename: str
    file_size_bytes: int
    storage_key: Optional[str] = None
    file_path: Optional[str] = None  # local disk path; read by the worker's parser
    status: UploadStatus = UploadStatus.pending
    # Sample metadata provided at upload time
    depth_meters: Optional[float] = None
    location_label: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source_type: Optional[str] = None  # e.g. "seawater", "sediment", "tissue"
    habitat: Optional[str] = None
    salinity_ppt: Optional[float] = None
    temperature_celsius: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
