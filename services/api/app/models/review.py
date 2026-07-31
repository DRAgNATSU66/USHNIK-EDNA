from datetime import datetime
from enum import StrEnum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class ReviewState(StrEnum):
    submitted = "submitted"
    triaged = "triaged"
    needs_evidence = "needs_evidence"
    accepted = "accepted"
    rejected = "rejected"
    duplicate = "duplicate"
    company_verified = "company_verified"
    included_in_training_batch = "included_in_training_batch"


class ReviewDecision(StrEnum):
    accept = "accept"
    reject = "reject"
    needs_evidence = "needs_evidence"
    mark_duplicate = "mark_duplicate"
    company_verify = "company_verify"


class ReviewType(StrEnum):
    auto_novelty = "auto_novelty"
    auto_contamination = "auto_contamination"
    manual_correction = "manual_correction"
    manual_novelty = "manual_novelty"
    manual_contamination = "manual_contamination"


class TriagePriority(StrEnum):
    urgent = "urgent"
    normal = "normal"
    low = "low"


class ReviewDoc(BaseModel):
    review_id: str = Field(default_factory=lambda: f"rev_{uuid.uuid4().hex[:16]}")
    analysis_id: str
    sequence_id: str
    submitted_by: str  # user_id; "system" for auto-queued reviews
    state: ReviewState = ReviewState.submitted
    review_type: ReviewType = ReviewType.manual_correction
    triage_priority: TriagePriority = TriagePriority.normal
    # Signal scores from the pipeline (populated for auto-queued reviews)
    novelty_score: Optional[float] = None
    contamination_score: Optional[float] = None
    novelty_level: Optional[str] = None
    abyss_recommendation: Optional[str] = None
    # Correction data
    correction_type: str  # e.g. "species_correction", "novelty_flag", "contamination_flag"
    proposed_taxon: Optional[str] = None
    is_novelty: Optional[bool] = None
    is_contamination: Optional[bool] = None
    is_low_quality: Optional[bool] = None
    evidence_notes: Optional[str] = None
    evidence_attachments: list[str] = Field(default_factory=list)
    # Triage
    triaged_by: Optional[str] = None
    triaged_at: Optional[datetime] = None
    # Admin decision
    decided_by: Optional[str] = None
    decision_notes: Optional[str] = None
    decided_at: Optional[datetime] = None
    # Training batch linkage
    training_batch_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
