from datetime import datetime
from enum import StrEnum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class UploadStatus(StrEnum):
    pending = "pending"
    stored = "stored"
    failed = "failed"


# Single source of truth for the optional sample metadata an upload can carry
# (decisions.md 2026-10-14, Q2: only the file is required). Ordered field
# name -> human label. POST /uploads, UploadDoc, the report's SampleMetadata
# and the "provided vs missing" context block are all checked against this
# mapping in tests/test_upload_metadata.py, so adding a field here without
# wiring it everywhere fails the suite.
OPTIONAL_METADATA_FIELDS: dict[str, str] = {
    "collected_at": "Collection date/time",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "location_label": "Location",
    "depth_meters": "Depth",
    "source_type": "Source type",
    "habitat": "Habitat",
    "salinity_ppt": "Salinity",
    "temperature_celsius": "Temperature",
    "dissolved_oxygen_mg_l": "Dissolved oxygen",
    "ph": "pH",
    "methodology": "Methodology",
    "negative_control_included": "Negative control",
    "collector": "Collector",
}

# Optional at upload, but a partner report cannot be produced without them
# (Q2). Coordinates count only when both latitude and longitude are present.
PARTNER_REPORT_REQUIRED_FIELDS: tuple[str, ...] = ("collected_at", "latitude", "longitude")


class UploadDoc(BaseModel):
    upload_id: str = Field(default_factory=lambda: f"upl_{uuid.uuid4().hex[:16]}")
    user_id: Optional[str] = None
    original_filename: str
    file_size_bytes: int
    # Where the bytes are (B7, app/storage.py): local://<key> or
    # s3://<bucket>/<key>. The worker reads the file back through this URI.
    storage_uri: Optional[str] = None
    storage_key: Optional[str] = None  # the <key> part of storage_uri
    checksum_sha256: Optional[str] = None  # of the stored bytes; the worker verifies it
    # Pre-B7 uploads only: an absolute path on the API's disk. New uploads
    # leave it None; the worker still reads it when storage_uri is absent.
    file_path: Optional[str] = None
    status: UploadStatus = UploadStatus.pending
    # Sample metadata provided at upload time. Every field is optional and is
    # listed in OPTIONAL_METADATA_FIELDS above.
    collected_at: Optional[datetime] = None  # when the sample was collected, not uploaded
    depth_meters: Optional[float] = None
    location_label: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source_type: Optional[str] = None  # e.g. "seawater", "sediment", "tissue"
    habitat: Optional[str] = None
    salinity_ppt: Optional[float] = None
    temperature_celsius: Optional[float] = None
    dissolved_oxygen_mg_l: Optional[float] = None
    ph: Optional[float] = None
    methodology: Optional[str] = None  # e.g. "metabarcoding", "qPCR"
    # None = not recorded. The team does not run blanks (Q4), so absence is the
    # common case: results flag it, uploads are never blocked on it.
    negative_control_included: Optional[bool] = None
    collector: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
