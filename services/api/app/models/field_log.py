from datetime import datetime
from enum import StrEnum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class FieldEntryKind(StrEnum):
    note = "note"        # Field Notes & Anomalies (left column, unthreaded)
    comment = "comment"  # Team Discussion (right column, threaded)


class FieldEntryDoc(BaseModel):
    entry_id: str = Field(default_factory=lambda: f"fle_{uuid.uuid4().hex[:16]}")
    analysis_id: str
    kind: FieldEntryKind
    author_id: str
    # Denormalized at write time so the UI never has to resolve a raw user_id
    # into a display name (a real gap already hit on Species Correction's
    # version history) -- an activity-log entry's byline is meant to reflect
    # who the author was *at the time*, so freezing it here is correct even
    # if the user later renames themselves.
    author_name: str
    body: str
    # Comments only: optional link to a specific sequence (e.g. an ASV/NV
    # candidate being discussed) and optional parent for one-level threading.
    anchor_sequence_id: Optional[str] = None
    reply_to: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
