"""
Inference data models.

String values of result_class match SequenceResultClass in
services/api/app/models/analysis.py exactly — kept in sync manually.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SequenceResultClass(StrEnum):
    known_species = "known_species"
    likely_taxonomic_group = "likely_taxonomic_group"
    possible_novelty = "possible_novelty"
    possible_contamination = "possible_contamination"
    low_quality_unusable = "low_quality_unusable"
    unknown_needs_online_confirmation = "unknown_needs_online_confirmation"


class InferenceMode(StrEnum):
    model = "model"           # real model ran
    stub = "stub"             # no model available / not loaded yet
    low_quality = "low_quality"  # skipped — routed as low_quality


# Labels available to each route's classifier head.
# These MUST match the label ordering used when training the head.
ROUTE_LABEL_SETS: dict[str, list[str]] = {
    "fish": [
        SequenceResultClass.known_species,
        SequenceResultClass.possible_novelty,
        SequenceResultClass.low_quality_unusable,
    ],
    "plant": [
        SequenceResultClass.known_species,
        SequenceResultClass.possible_novelty,
        SequenceResultClass.possible_contamination,
        SequenceResultClass.low_quality_unusable,
    ],
    "bacteria_pathogen": [
        SequenceResultClass.known_species,
        SequenceResultClass.likely_taxonomic_group,
        SequenceResultClass.possible_novelty,
        SequenceResultClass.possible_contamination,
    ],
    "animal_general": [
        SequenceResultClass.known_species,
        SequenceResultClass.likely_taxonomic_group,
        SequenceResultClass.possible_novelty,
    ],
    "human_domestic_contamination": [
        SequenceResultClass.possible_contamination,
        SequenceResultClass.known_species,
    ],
    "misc_unknown": [
        SequenceResultClass.unknown_needs_online_confirmation,
        SequenceResultClass.possible_novelty,
        SequenceResultClass.low_quality_unusable,
    ],
    "low_quality": [
        SequenceResultClass.low_quality_unusable,
    ],
}


@dataclass
class ModelRegistryEntry:
    model_id: str
    route: str
    base_model: str               # HuggingFace model ID or local path
    head_type: str                # "sequence_classification" | "token_classification"
    embedding_dim: int            # hidden size of the base model
    label_set_version: str
    status: str                   # experimental / staging / production / retired
    # Optional — null means no trained weights yet.
    training_dataset_version: str | None = None
    metrics: dict = field(default_factory=dict)
    thresholds: dict = field(default_factory=dict)
    artifact_uri: str | None = None      # local path or HF Hub repo/file
    checksum: str | None = None
    created_at: str = ""
    promoted_by: str | None = None
    # Per-model allowlist for custom modeling code (e.g. DNABERT-2 ships its
    # own attention implementation and needs this to load at all). Defaults
    # to False — a registry entry must explicitly opt in per base_model, so
    # trusting one model's repo code never silently extends to another's.
    trusted_remote_code: bool = False

    @property
    def is_runnable(self) -> bool:
        """True when the model artifact is available and the status is not retired."""
        return self.artifact_uri is not None and self.status != "retired"


@dataclass
class PredictionResult:
    sequence_id: str
    result_class: str              # SequenceResultClass value
    predicted_taxon: str | None    # best taxonomic assignment (null until Phase 14)
    confidence: float              # 0.0–1.0
    model_version_used: str        # model_id or "stub" / "low_quality"
    inference_mode: InferenceMode
    # Per-label logit scores (softmax probabilities if model ran, else empty).
    label_scores: dict[str, float] = field(default_factory=dict)
    # [CLS] embedding vector — used by Phase 8 novelty scorer.
    embedding: list[float] | None = None

    def to_dict(self) -> dict:
        return {
            "result_class": self.result_class,
            "predicted_taxon": self.predicted_taxon,
            "confidence": round(self.confidence, 4),
            "model_version_used": self.model_version_used,
            "inference_mode": str(self.inference_mode),
            "label_scores": {k: round(v, 4) for k, v in self.label_scores.items()},
        }
