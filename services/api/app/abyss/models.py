"""
Abyss Mode domain models — Phase 10.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


ABYSS_DISCLAIMER = (
    "Abyss Mode is a field-triage system. Results are preliminary and must be "
    "confirmed by full online analysis after reconnecting."
)


class ExpeditionStatus(StrEnum):
    pre_departure = "pre_departure"
    active = "active"
    synced = "synced"
    archived = "archived"


class ExpeditionDoc(BaseModel):
    expedition_id: str = Field(default_factory=lambda: f"exp_{uuid.uuid4().hex[:16]}")
    name: str
    description: Optional[str] = None
    created_by: str
    status: ExpeditionStatus = ExpeditionStatus.pre_departure
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    vessel: Optional[str] = None
    target_depth_meters: Optional[float] = None
    location_label: Optional[str] = None
    # Offline pack info
    offline_license_issued: bool = False
    offline_license_expires_at: Optional[datetime] = None
    # Sync state
    synced_at: Optional[datetime] = None
    sync_job_count: int = 0  # how many re-analysis jobs were queued on sync
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OfflinePackManifest(BaseModel):
    """
    Describes the contents of an offline pack for an expedition.
    The pack is assembled by the expedition operator before departure.
    Phase 10 defines the manifest contract; actual file bundling is Phase 15.
    """
    expedition_id: str
    pack_version: str = "1.0"
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    disclaimer: str = ABYSS_DISCLAIMER
    components: list[OfflinePackComponent]
    total_size_mb_estimate: float
    instructions: str


class OfflinePackComponent(BaseModel):
    name: str
    component_type: str  # model_pack | reference_pack | contaminant_pack | metadata_pack | license | route_classifier
    # status: available | not_yet_trained | not_yet_available | requires_manual_download | unavailable
    status: str  # available | not_yet_trained | requires_manual_download
    size_mb_estimate: float
    description: str
    artifact_uri: Optional[str] = None


class AbyssSequenceInput(BaseModel):
    sequence_id: str
    sequence: str
    description: Optional[str] = None
    # Optional field metadata
    habitat: Optional[str] = None
    depth_meters: Optional[float] = None
    location_label: Optional[str] = None
    sample_timestamp: Optional[datetime] = None


class AbyssAnalysisRequest(BaseModel):
    expedition_id: str
    offline_license_token: str
    sequences: list[AbyssSequenceInput]
    device_id: Optional[str] = None
    local_timestamp: Optional[datetime] = None


class AbyssSequenceResult(BaseModel):
    sequence_id: str
    length: int
    gc_ratio: float
    n_ratio: float
    route: str
    route_confidence: float
    confidence_tier: str
    novelty_score: float
    novelty_level: str
    contamination_flagged: bool
    contamination_score: float
    abyss_recommendation: str
    requires_cloud_confirmation: bool
    reason_codes: list[str]
    # Explicit field-triage action
    field_action: str  # preserve_sample | continue_sampling | resample | return_for_full_analysis
    # Which router produced `route` (B25):
    #   learned          learned k-mer router (learned_router.py)
    #   gc_fallback      learned router unavailable or failed; GC-only routing
    #   gc_only          GC-only routing forced by SYNTHVEDA_ROUTER=heuristic
    #   low_quality_gate QC gate fired before any router ran
    router_method: str = "gc_fallback"
    router_version: Optional[str] = None
    # Why the learned router was not used (e.g. "artifact_missing"); None when it was.
    router_fallback_reason: Optional[str] = None
    # Per-route probabilities; calibrated (dev-fitted temperature) when
    # probabilities_calibrated is True. Empty for GC-only routing.
    route_probabilities: dict[str, float] = Field(default_factory=dict)
    probabilities_calibrated: bool = False
    # True when GC-only routing was used because the learned router was
    # unavailable or failed (not when forced); router_error carries
    # "<reason>: <detail>" (B12, B25).
    router_error_fallback: bool = False
    router_error: Optional[str] = None


class AbyssRouterSummary(BaseModel):
    """Which router ran for a batch (B25)."""
    # learned | gc_fallback | gc_only: the router state for this batch. With
    # "learned", single sequences can still fall back (e.g. no valid k-mer);
    # `counts` gives the per-sequence router_method tally.
    method: str
    model_id: Optional[str] = None
    version: Optional[str] = None
    artifact_sha256: Optional[str] = None
    fallback_reason: Optional[str] = None
    detail: Optional[str] = None
    counts: dict[str, int] = Field(default_factory=dict)


class AbyssAnalysisResult(BaseModel):
    analysis_id: str = Field(default_factory=lambda: f"abyss_{uuid.uuid4().hex[:12]}")
    expedition_id: str
    disclaimer: str = ABYSS_DISCLAIMER
    sequences_analyzed: int
    possible_novelty_count: int
    contamination_flag_count: int
    low_quality_count: int
    results: list[AbyssSequenceResult]
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    # Aggregate recommendation for the sample batch
    batch_recommendation: str
    batch_risk_level: str  # low | medium | high
    requires_cloud_confirmation: bool
    router: Optional[AbyssRouterSummary] = None


class OfflineSyncedAnalysis(BaseModel):
    """Preliminary abyss analysis submitted during sync."""
    abyss_analysis_id: str
    sequences_analyzed: int
    possible_novelty_count: int
    contamination_flag_count: int
    analyzed_at: Optional[datetime] = None
    device_id: Optional[str] = None
    raw_results: list[dict] = Field(default_factory=list)
    # AbyssAnalysisResult.router, so the synced record says which router ran.
    router: Optional[dict] = None


class AbyssSyncRequest(BaseModel):
    expedition_id: str
    local_logs: list[dict] = Field(default_factory=list)
    local_analyses: list[OfflineSyncedAnalysis] = Field(default_factory=list)
    # If provided, these uploads already exist in MongoDB (user pre-uploaded before sync)
    upload_ids_for_reanalysis: list[str] = Field(default_factory=list)


class AbyssSyncResult(BaseModel):
    ok: bool
    expedition_id: str
    logs_stored: int
    analyses_stored: int
    reanalysis_jobs_queued: int
    job_ids: list[str]
    disclaimer: str = ABYSS_DISCLAIMER
