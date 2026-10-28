from datetime import datetime
from enum import StrEnum
from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid


class FieldEntryKind(StrEnum):
    note = "note"        # Field Notes & Anomalies (left column, unthreaded)
    comment = "comment"  # Team Discussion (right column, threaded)
    task = "task"        # Follow-up with a status, optional due date and assignee (M1)


class TaskStatus(StrEnum):
    open = "open"
    in_progress = "in_progress"
    done = "done"


# Fields a PATCH may change. kind, reply_to and analysis_id are structural
# (which column, which thread, which run) and stay as created. The task_*
# fields, due_date and assignee exist on kind=task entries only.
EditableField = Literal["body", "anchor_sequence_id", "task_status", "due_date", "assignee"]
EDITABLE_FIELDS: tuple[str, ...] = ("body", "anchor_sequence_id", "task_status", "due_date", "assignee")
TASK_FIELDS: tuple[str, ...] = ("task_status", "due_date", "assignee")


class FieldChange(BaseModel):
    field: EditableField
    old: Optional[str] = None
    new: Optional[str] = None


class FieldEntryEdit(BaseModel):
    """One PATCH, as recorded. Appended with $push and never rewritten, so
    `edits` is the entry's full, ordered history; edits[0].changes[*].old
    is what was originally posted."""
    edit_id: str = Field(default_factory=lambda: f"fle_edit_{uuid.uuid4().hex[:16]}")
    editor_id: str
    # Frozen at write time for the same reason as FieldEntryDoc.author_name.
    editor_name: str
    edited_at: datetime = Field(default_factory=datetime.utcnow)
    changes: list[FieldChange]


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
    # kind=task only (M1); None on notes and comments. due_date is an ISO
    # date string ("YYYY-MM-DD"): BSON has no date-only type, and a string
    # keeps FieldChange.old/new comparable. assignee is free text (a person
    # or a team), not a user_id -- there is no user directory to check it against.
    task_status: Optional[TaskStatus] = None
    due_date: Optional[str] = None
    assignee: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # B10: set by PATCH. Entries written before B10 have neither field in
    # Mongo and load with these defaults (no edits).
    updated_at: Optional[datetime] = None
    edits: list[FieldEntryEdit] = Field(default_factory=list)


class FieldAttachment(BaseModel):
    """What clients see of a field-log attachment (B10). The storage URI and
    key stay server-side; clients fetch bytes through the download route."""
    attachment_id: str = Field(default_factory=lambda: f"fla_{uuid.uuid4().hex[:16]}")
    analysis_id: str
    # Optional link to one note/comment; None means "attached to the run".
    entry_id: Optional[str] = None
    uploader_id: str
    uploader_name: str
    original_filename: str
    # Decided by the server from the file's leading bytes, not taken from
    # the client's Content-Type header.
    content_type: str
    size_bytes: int
    checksum_sha256: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FieldAttachmentDoc(FieldAttachment):
    """The Mongo document: the public fields plus where the bytes are
    (app/storage.py URI, QNA-009)."""
    storage_uri: str
    storage_key: str
