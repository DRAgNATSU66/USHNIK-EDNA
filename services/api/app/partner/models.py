"""Shapes for the partner endpoints (t-1026-2 summary, B16; t-1028-1 audits, M1)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SummaryInterval = Literal["day", "week", "month"]
SummaryScope = Literal["mine", "all"]


class SummaryScopeInfo(BaseModel):
    """What the numbers were computed over, as resolved from the request."""
    mode: Literal["mine", "all", "user"]
    user_id: Optional[str] = None  # set for "mine" and "user"
    date_from: Optional[date] = None
    date_to: Optional[date] = None  # inclusive
    interval: SummaryInterval


class SummaryTotals(BaseModel):
    uploads: int = 0
    analyses: int = 0
    sequences: int = 0
    # Sequences whose effective predicted_taxon is not null (see definitions).
    sequences_with_taxon: int = 0
    novelty_flags: int = 0
    contamination_flags: int = 0
    low_quality: int = 0
    analyses_with_novelty_flags: int = 0
    analyses_with_contamination_flags: int = 0


class TimeSeriesPoint(BaseModel):
    period_start: date  # first day of the day/ISO week (Monday)/month, UTC
    uploads: int = 0
    analyses: int = 0
    sequences: int = 0
    novelty_flags: int = 0
    contamination_flags: int = 0


class TaxonCount(BaseModel):
    taxon: str
    taxon_rank: Optional[str] = None  # from results[].decision when present
    sequences: int
    analyses: int


class ReviewSummary(BaseModel):
    total: int = 0
    # submitted + triaged + needs_evidence
    open: int = 0
    by_state: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)


class EnvironmentSourceCount(BaseModel):
    provider: str
    source: str
    licence: str
    attribution: str
    uploads: int  # uploads with at least one public value from this provider
    latest_retrieved_at: Optional[datetime] = None


class EnvironmentCoverage(BaseModel):
    uploads_in_scope: int = 0
    # Uploads with latitude, longitude and collected_at (a lookup is possible).
    eligible: int = 0
    not_applicable: int = 0
    # eligible uploads by lookup state: complete | partial | pending | failed,
    # plus not_requested (no lookup doc yet; GET /environment/uploads/{id}
    # schedules one).
    by_status: dict[str, int] = Field(default_factory=dict)
    # Per variable over eligible uploads: ok (public value) | user_provided |
    # unavailable (includes pending / not looked up).
    variables: dict[str, dict[str, int]] = Field(default_factory=dict)
    sources: list[EnvironmentSourceCount] = Field(default_factory=list)
    latest_retrieved_at: Optional[datetime] = None


class SiteSummary(BaseModel):
    """One in-scope upload that has coordinates (map marker)."""
    upload_id: str
    latitude: float
    longitude: float
    location_label: Optional[str] = None
    collected_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    analyses: int = 0
    sequences: int = 0
    novelty_flags: int = 0
    contamination_flags: int = 0
    # Same values as GET /environment/uploads/{id} (not_applicable when
    # collected_at is missing; not_requested when no lookup doc exists).
    environment_status: str
    environment_retrieved_at: Optional[datetime] = None
    environment_providers: list[str] = Field(default_factory=list)


class TaskSummary(BaseModel):
    """Field-log tasks (kind=task) on the analyses in scope."""
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    overdue: int = 0  # not done, due_date before today (UTC)
    next_due_date: Optional[date] = None  # earliest due_date among tasks not done


class AuditSummary(BaseModel):
    """Audits in the summary's owner scope: current state, not date-filtered
    (a pending audit created before date_from is still pending)."""
    total: int = 0
    pending: int = 0  # scheduled + in_progress
    by_status: dict[str, int] = Field(default_factory=dict)
    findings_by_severity: dict[str, int] = Field(default_factory=dict)
    next_due_date: Optional[date] = None  # earliest due_date among pending audits
    overdue: int = 0  # pending audits with due_date before today (UTC)
    last_completed_at: Optional[datetime] = None


class PartnerSummary(BaseModel):
    generated_at: datetime
    scope: SummaryScopeInfo
    # How each count is computed, so a partner page can say it in plain words.
    definitions: dict[str, str]
    # Plain-language caveats: empty scope, no taxa yet, truncation, ...
    notes: list[str] = Field(default_factory=list)
    totals: SummaryTotals
    time_series: list[TimeSeriesPoint] = Field(default_factory=list)
    route_distribution: dict[str, int] = Field(default_factory=dict)
    result_class_distribution: dict[str, int] = Field(default_factory=dict)
    top_taxa: list[TaxonCount] = Field(default_factory=list)
    reviews: ReviewSummary
    environment: EnvironmentCoverage
    sites: list[SiteSummary] = Field(default_factory=list)
    sites_truncated: bool = False
    tasks: TaskSummary
    audits: AuditSummary


# ---------------------------------------------------------------------------
# Audits (t-1028-1, M1)
# ---------------------------------------------------------------------------

class AuditStatus(StrEnum):
    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


# scheduled + in_progress: what the Industrial page calls "pending audits".
PENDING_AUDIT_STATUSES = (AuditStatus.scheduled, AuditStatus.in_progress)


class AuditTargetKind(StrEnum):
    upload = "upload"        # ref = upload_id, checked to exist and be visible to the caller
    analysis = "analysis"    # ref = analysis_id, same check
    site = "site"            # a sampling site or zone, free text
    organisation = "organisation"
    other = "other"


class FindingSeverity(StrEnum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


def _not_blank(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


class AuditTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AuditTargetKind
    ref: Optional[str] = Field(default=None, max_length=200)
    label: str = Field(min_length=1, max_length=300)

    _strip = field_validator("ref", "label")(_not_blank)

    @model_validator(mode="after")
    def _ref_for_records(self):
        if self.kind in (AuditTargetKind.upload, AuditTargetKind.analysis) and not self.ref:
            raise ValueError(f"target.ref (the {self.kind.value}_id) is required when target.kind is {self.kind.value}")
        return self


class AuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: FindingSeverity
    description: str = Field(min_length=1, max_length=4000)
    reference: Optional[str] = Field(default=None, max_length=500)

    _strip = field_validator("description", "reference")(_not_blank)


class CreateAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: AuditTarget
    scope: str = Field(min_length=1, max_length=2000)
    findings: list[AuditFinding] = Field(default_factory=list, max_length=200)
    status: AuditStatus = AuditStatus.scheduled
    due_date: Optional[date] = None
    # Only with status=completed; defaults to the time of the POST when
    # omitted. Lets a past audit be recorded with the date it finished.
    completed_at: Optional[datetime] = None

    _strip = field_validator("scope")(_not_blank)

    @model_validator(mode="after")
    def _completion(self):
        if self.completed_at is not None:
            if self.status != AuditStatus.completed:
                raise ValueError("completed_at is only allowed when status is completed")
            ts = self.completed_at
            ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
            if ts > datetime.now(timezone.utc):
                raise ValueError("completed_at cannot be in the future")
        return self


class AuditDoc(BaseModel):
    audit_id: str = Field(default_factory=lambda: f"aud_{uuid.uuid4().hex[:16]}")
    target: AuditTarget
    scope: str
    findings: list[AuditFinding] = Field(default_factory=list)
    status: AuditStatus
    # ISO date string: BSON has no date-only type (same as field-log tasks).
    due_date: Optional[str] = None
    completed_at: Optional[datetime] = None
    created_by: str
    # Frozen at write time, like field-log author_name.
    created_by_name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Regional views: hotspots + alerts (t-1027-3, M2; app/partner/regional.py)
# ---------------------------------------------------------------------------

class TaxonInCell(BaseModel):
    taxon: str
    taxon_rank: Optional[str] = None
    sequences: int


class HotspotCell(BaseModel):
    """One latitude/longitude grid cell holding at least one upload."""
    cell_id: str  # "<lat index>:<lon index>" at the response's cell_deg
    lat_min: float
    lat_max: float
    lng_min: float
    lng_max: float
    center_lat: float
    center_lng: float
    uploads: int
    analyses: int
    sequences: int
    sequences_with_taxon: int
    distinct_taxa: int
    novelty_flags: int
    contamination_flags: int
    open_reviews: int
    open_urgent_reviews: int
    top_taxa: list[TaxonInCell] = Field(default_factory=list)
    location_labels: list[str] = Field(default_factory=list)
    upload_ids: list[str] = Field(default_factory=list)  # newest first, capped
    first_collected_at: Optional[datetime] = None
    last_collected_at: Optional[datetime] = None


class HotspotCoverage(BaseModel):
    uploads_in_scope: int = 0
    uploads_with_coordinates: int = 0
    uploads_without_coordinates: int = 0
    uploads_invalid_coordinates: int = 0
    analyses_in_scope: int = 0
    analyses_mapped: int = 0  # in-scope analyses of mapped in-scope uploads


class HotspotsResponse(BaseModel):
    generated_at: datetime
    scope: SummaryScopeInfo
    cell_deg: float
    definitions: dict[str, str]
    notes: list[str] = Field(default_factory=list)
    coverage: HotspotCoverage
    # Most open urgent reviews first, then most flags, then most uploads.
    cells: list[HotspotCell] = Field(default_factory=list)


class RegionalAlert(BaseModel):
    analysis_id: str
    upload_id: Optional[str] = None
    priority: Literal["urgent", "flagged"]
    # Subset of open_urgent_review | contamination_flags | novelty_flags.
    reasons: list[str]
    analysis_created_at: Optional[datetime] = None
    upload_found: bool
    original_filename: Optional[str] = None
    location_label: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    collected_at: Optional[datetime] = None
    sequences: int
    novelty_flags: int
    contamination_flags: int
    contamination_types: dict[str, int] = Field(default_factory=dict)
    open_reviews: int
    open_urgent_reviews: int
    open_reviews_by_type: dict[str, int] = Field(default_factory=dict)


class AlertsResponse(BaseModel):
    generated_at: datetime
    scope: SummaryScopeInfo
    definitions: dict[str, str]
    notes: list[str] = Field(default_factory=list)
    analyses_in_scope: int
    total: int  # alerts before the limit
    urgent: int  # of total
    truncated: bool
    alerts: list[RegionalAlert] = Field(default_factory=list)
