"""Shapes for the environmental-context service (Q5, t-1026-1)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# Variables looked up for every upload with coordinates + collected_at, in
# display order. Units are the units of `value` after conversion.
VARIABLES: dict[str, str] = {
    "temperature": "°C",
    "salinity": "PSU",
    "dissolved_oxygen": "mg/L",
    "ph": "pH",
    "current": "m/s",
    "wind": "m/s",
}

# Upload metadata field a user can enter for a variable. A user value takes
# precedence over the public one (labelled user_provided); the public value is
# still stored and returned alongside it.
USER_FIELDS: dict[str, tuple[str, str]] = {
    "temperature": ("temperature_celsius", "°C"),
    "salinity": ("salinity_ppt", "ppt"),
    "dissolved_oxygen": ("dissolved_oxygen_mg_l", "mg/L"),
    "ph": ("ph", "pH"),
}


class GridPoint(BaseModel):
    """The model/grid cell the value actually came from."""
    latitude: float
    longitude: float
    depth_m: Optional[float] = None  # positive down; None for 10 m wind etc.
    time: str  # ISO timestamp of the time step used
    distance_km: Optional[float] = None  # from the lookup coordinate


class SourceInfo(BaseModel):
    provider: str  # "copernicus_marine" | "noaa_erddap" | "open_meteo"
    source: str  # human name of the service
    licence: str
    attribution: str
    terms_note: Optional[str] = None


class PublicValue(BaseModel):
    value: float
    unit: str
    provider: str
    source: str
    product_id: Optional[str] = None
    dataset_id: str
    source_variable: str  # variable name(s) in the source, e.g. "thetao", "uo,vo"
    query_url: str  # exact URL that returned the value (never contains secrets)
    grid_point: GridPoint
    retrieved_at: datetime
    access: str  # "anonymous_arco" | "authenticated_arco" | "public_api"
    raw_value: Optional[float] = None  # before unit conversion, when converted
    raw_unit: Optional[str] = None
    kind: str = "modelled"  # "modelled" | "satellite_analysis" | "reanalysis"
    details: dict[str, Any] = Field(default_factory=dict)  # direction, profile, ...
    series: list[dict[str, Any]] = Field(default_factory=list)  # by-day values
    licence: str
    attribution: str
    note: Optional[str] = None


class ProviderAttempt(BaseModel):
    provider: str
    ok: bool
    reason: Optional[str] = None
    transient: bool = False


class PublicVariableResult(BaseModel):
    status: Literal["ok", "unavailable"]
    value: Optional[PublicValue] = None
    reason: Optional[str] = None
    attempts: list[ProviderAttempt] = Field(default_factory=list)


class EnvironmentQuery(BaseModel):
    latitude: float  # as on the upload
    longitude: float
    # Coordinates actually queried: rounded to 2 decimals (~1 km, below every
    # grid spacing used) so nearby uploads share the coarse cache entry.
    lookup_latitude: float
    lookup_longitude: float
    collected_at: datetime
    date: str  # UTC date of collected_at, ISO
    depth_m: Optional[float] = None
    target_level: Literal["surface", "sample_depth"]


class UserValue(BaseModel):
    value: float
    unit: str
    field: str  # upload metadata field it came from


class VariableContext(BaseModel):
    status: Literal["ok", "unavailable", "user_provided"]
    value: Optional[float] = None  # the value to show: user's if provided, else public
    unit: Optional[str] = None
    value_source: Optional[Literal["user", "public"]] = None
    reason: Optional[str] = None  # why unavailable
    user_value: Optional[UserValue] = None
    public_status: Literal["ok", "unavailable", "pending", "not_applicable"]
    public: Optional[PublicValue] = None
    public_reason: Optional[str] = None
    attempts: list[ProviderAttempt] = Field(default_factory=list)


class EnvironmentContextResponse(BaseModel):
    upload_id: str
    # not_applicable: upload lacks coordinates or collected_at.
    # pending: lookup queued/running. complete: every variable has a public
    # value. partial: some unavailable. failed: the lookup itself crashed.
    status: Literal["not_applicable", "pending", "complete", "partial", "failed"]
    reason: Optional[str] = None
    query: Optional[EnvironmentQuery] = None
    variables: dict[str, VariableContext]
    sources: list[SourceInfo] = Field(default_factory=list)
    requested_at: Optional[datetime] = None
    retrieved_at: Optional[datetime] = None
    cache_hit: Optional[bool] = None
    cache_key: Optional[str] = None
