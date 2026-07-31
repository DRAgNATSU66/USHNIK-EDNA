"""
Router data models.

These mirror TaxonomicRoute / SequenceResultClass from the API but are defined
here independently so the worker has no import-time dependency on the API package.
The string values must stay in sync with services/api/app/models/analysis.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TaxonomicRoute(StrEnum):
    fish = "fish"
    plant = "plant"
    bacteria_pathogen = "bacteria_pathogen"
    animal_general = "animal_general"
    human_domestic_contamination = "human_domestic_contamination"
    misc_unknown = "misc_unknown"
    low_quality = "low_quality"


class ConfidenceTier(StrEnum):
    """
    How certain the router is.

    Downstream inference uses this to decide whether to run one model or
    multiple models in parallel (specialist + fallback).
    """
    high = "high"       # confidence >= 0.70 → specialist model only
    medium = "medium"   # confidence >= 0.40 → specialist + top fallback
    low = "low"         # confidence  < 0.40 → general/misc model + reference search


@dataclass
class RouterInput:
    """Subset of BatchRecord needed by the router."""
    sequence_id: str
    sequence: str
    length: int
    gc_ratio: float
    n_ratio: float
    sha256: str
    source_file: str = ""
    # Optional context from sample metadata — improves routing accuracy.
    depth_meters: float | None = None
    habitat: str | None = None
    location_label: str | None = None


@dataclass
class RouteResult:
    """Output of route_sequence()."""
    sequence_id: str
    route: TaxonomicRoute
    route_confidence: float          # 0.0–1.0, normalised probability
    confidence_tier: ConfidenceTier
    fallback_routes: list[str]       # ordered by descending confidence, excluding primary
    reason_codes: list[str]          # human-readable codes for audit / admin review
    # Raw per-route scores before normalisation — useful for debugging.
    raw_scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "sequence_id": self.sequence_id,
            "route": str(self.route),
            "route_confidence": round(self.route_confidence, 4),
            "confidence_tier": str(self.confidence_tier),
            "fallback_routes": self.fallback_routes,
            "reason_codes": self.reason_codes,
            "raw_scores": {k: round(v, 4) for k, v in self.raw_scores.items()},
        }
