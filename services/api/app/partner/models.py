"""Shapes for the partner endpoints (t-1026-2 summary, B16)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

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
