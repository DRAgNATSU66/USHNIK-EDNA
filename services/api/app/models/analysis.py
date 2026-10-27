from datetime import datetime
from enum import StrEnum
from collections.abc import Mapping
from typing import Literal, Optional, Any
from pydantic import BaseModel, Field, model_validator
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


TAXON_FIELDS = ("predicted_taxon", "taxon_rank", "percent_identity", "reference_db", "reference_db_version")

TaxonSource = Literal["decision", "legacy"]


_QUOTES = "'\""


def clean_taxon_name(name: Optional[str], rank: Optional[str] = None) -> Optional[str]:
    """A stored taxon name without stray wrapping quotes, for display and sort.

    Reference builds before the worker's unquote_name (services/worker/
    training/build_reference_db.py) kept SILVA's quotes around names that are
    not validly published: plant v2 stores genus "'Halosarcinochlamys", which
    then sorts first in top-taxa. The same rule as the worker's
    clean_rank_name: quotes wrapping the whole name are dropped, and for a
    genus (or, rank unknown, a one-word name) a lone quote at either end too.
    Quotes inside a name are nomenclature ("'Catharanthus roseus' malformation
    phytoplasma", "witches'-broom") and are kept. None and "" pass through; a
    name that would clean to nothing is returned as stored.
    """
    if not name:
        return name
    s = name.strip()
    if len(s) >= 2 and s[0] in _QUOTES and s[-1] == s[0] and s[0] not in s[1:-1]:
        s = s[1:-1].strip()
    if rank == "genus" or (rank is None and len(s.split()) == 1):
        s = s.strip(_QUOTES).strip()
    return s or name


def resolve_taxon_fields(result: Mapping[str, Any]) -> dict[str, Any]:
    """The flat taxon fields of one stored per-sequence result (t-1023-1).

    Decision-first, the same rule as partner/summary.py _effective: when the
    orchestrator wrote results[].decision, all five fields come from it
    (a None there means the decision has no value, e.g. no reference
    assignment, and is kept as None). Otherwise only the legacy top-level
    predicted_taxon exists; taxon_rank, percent_identity, reference_db and
    reference_db_version were never recorded before the orchestrator and are
    None. taxon_source says which of the two applied. predicted_taxon is
    passed through clean_taxon_name.
    """
    dec = result.get("decision")
    if isinstance(dec, Mapping):
        out: dict[str, Any] = {f: dec.get(f) for f in TAXON_FIELDS}
        out["taxon_source"] = "decision"
    else:
        out = {f: None for f in TAXON_FIELDS}
        out["predicted_taxon"] = result.get("predicted_taxon")
        out["taxon_source"] = "legacy"
    if out["percent_identity"] is not None:
        out["percent_identity"] = float(out["percent_identity"])
    out["predicted_taxon"] = clean_taxon_name(out["predicted_taxon"], out["taxon_rank"])
    return out


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
    # Flat, typed taxon fields (t-1023-1), derived on read by
    # resolve_taxon_fields from `decision` when present, else from the legacy
    # predicted_taxon; never stored by the worker. predicted_taxon (above) is
    # set the same way. All None on pre-orchestrator results except
    # predicted_taxon, with taxon_source = "legacy".
    taxon_rank: Optional[str] = None
    percent_identity: Optional[float] = None
    reference_db: Optional[str] = None
    reference_db_version: Optional[str] = None
    taxon_source: Optional[TaxonSource] = None

    @model_validator(mode="after")
    def _derive_taxon_fields(self) -> "SequenceResult":
        src = {"predicted_taxon": self.predicted_taxon,
               "decision": self.decision.model_dump() if self.decision is not None else None}
        for field, value in resolve_taxon_fields(src).items():
            setattr(self, field, value)
        return self


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
