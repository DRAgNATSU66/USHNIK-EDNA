from datetime import datetime
from enum import StrEnum
from typing import Optional, Any
from pydantic import BaseModel, Field
import uuid


class TaxonomicRoute(StrEnum):
    fish = "fish"
    plant = "plant"
    bacteria_pathogen = "bacteria_pathogen"
    animal_general = "animal_general"
    human_domestic_contamination = "human_domestic_contamination"
    misc_unknown = "misc_unknown"
    low_quality = "low_quality"


class SequenceResultClass(StrEnum):
    known_species = "known_species"
    likely_taxonomic_group = "likely_taxonomic_group"
    possible_novelty = "possible_novelty"
    known_species_not_novelty = "known_species_not_novelty"
    possible_contamination = "possible_contamination"
    low_quality_unusable = "low_quality_unusable"
    unknown_needs_online_confirmation = "unknown_needs_online_confirmation"


class SequenceDecision(BaseModel):
    """The worker orchestrator's combined answer for one sequence (decision
    Q7; services/worker/app/orchestrator/combiner.py). `rule` names the
    combiner rule that set result_class. Every field can be None: no
    reference assignment -> no taxon/identity, no head -> no confidence."""
    final_route: Optional[str] = None
    result_class: Optional[str] = None
    predicted_taxon: Optional[str] = None
    taxon_rank: Optional[str] = None
    percent_identity: Optional[float] = None
    reference_db: Optional[str] = None
    reference_db_version: Optional[str] = None
    confidence: Optional[float] = None
    rule: Optional[str] = None


class SequenceResult(BaseModel):
    sequence_id: str
    sequence: str
    length: int
    gc_ratio: float
    n_ratio: float
    route: TaxonomicRoute
    route_confidence: float
    result_class: SequenceResultClass
    predicted_taxon: Optional[str] = None
    confidence: float
    novelty_score: Optional[float] = None
    contamination_score: Optional[float] = None
    reason_codes: list[str] = Field(default_factory=list)
    model_version_used: Optional[str] = None
    # Which router chose `route` (worker model_router, B19): "learned",
    # "heuristic_fallback" (with router_fallback_reason), "heuristic" or
    # "low_quality_gate". None on results written before B19.
    router_method: Optional[str] = None
    router_version: Optional[str] = None
    router_fallback_reason: Optional[str] = None
    route_probabilities: Optional[dict[str, float]] = None
    route_probabilities_calibrated: Optional[bool] = None
    # "model" | "stub" | "low_quality"; stub_reason says why a stub was used
    # (e.g. head_missing). Written by the worker's _stage_infer; None on old docs.
    inference_mode: Optional[str] = None
    stub_reason: Optional[str] = None
    # Day 9 orchestrator (decision Q7). `route` above is the final route;
    # router_route is the router's own top pick. decision_trace is
    # {orchestrator_version, plan, evidence, combine}, bounded by the worker
    # (top hits capped, no embeddings; mean 5.4 KB BSON on the held-out
    # smoke run). All None on results written before the orchestrator.
    router_route: Optional[str] = None
    decision: Optional[SequenceDecision] = None
    decision_trace: Optional[dict[str, Any]] = None


class AnalysisSummary(BaseModel):
    total_sequences: int
    known_species: int
    possible_novelty: int
    contamination_flags: int
    low_quality: int
    route_distribution: dict[str, int] = Field(default_factory=dict)


class AnalysisResultDoc(BaseModel):
    analysis_id: str = Field(default_factory=lambda: f"ana_{uuid.uuid4().hex[:16]}")
    job_id: str
    upload_id: str
    user_id: Optional[str] = None
    mode: str = "online_full"
    model_version_set: Optional[str] = None
    orchestrator_version: Optional[str] = None
    summary: Optional[AnalysisSummary] = None
    results: list[SequenceResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
