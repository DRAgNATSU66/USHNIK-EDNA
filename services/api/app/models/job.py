from datetime import datetime
from enum import StrEnum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class JobState(StrEnum):
    queued = "queued"
    parsing = "parsing"
    qc = "qc"
    routing = "routing"
    inferencing = "inferencing"
    novelty_scoring = "novelty_scoring"
    reporting = "reporting"
    completed = "completed"
    failed = "failed"
    needs_review = "needs_review"


class AnalysisJobDoc(BaseModel):
    job_id: str = Field(default_factory=lambda: f"job_{uuid.uuid4().hex[:16]}")
    upload_id: str
    user_id: Optional[str] = None
    state: JobState = JobState.queued
    analysis_id: Optional[str] = None  # set when analysis result is written
    error_message: Optional[str] = None
    queued_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    # Mode: online_full or abyss_synced
    mode: str = "online_full"
