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
    summary: Optional[AnalysisSummary] = None
    results: list[SequenceResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
