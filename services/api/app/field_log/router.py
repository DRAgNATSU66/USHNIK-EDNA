"""
Field Log API.

Backs the Researcher Mode "Field Log" tab (SYNTHVEDA_BUILD_SPEC.md 2.4):
field notes/anomalies (unthreaded) and team discussion (optionally threaded
one level, optionally anchored to a specific sequence). Both are the same
underlying entry shape, discriminated by `kind`.

Endpoints:
  POST  /field-log/entries                          Create a note or comment
  GET   /field-log/entries                          List entries for one analysis
  GET   /field-log/entries/{entry_id}               One entry, with its edit history
  PATCH /field-log/entries/{entry_id}               Edit body / anchor; appends to history
  POST  /field-log/attachments                      Attach a PDF/JPEG/PNG to an analysis
  GET   /field-log/attachments                      List attachments for one analysis
  GET   /field-log/attachments/{attachment_id}/download   The stored bytes

Access (every route): the analysis owner, or a curator/admin/company_owner
(_check_analysis_access). PATCH additionally needs the caller to be the
entry's author or one of those roles, so a collaborator can't rewrite
someone else's note under their name; the history records who did edit.

Edit history (B10) is append-only: each PATCH $push-es one FieldEntryEdit
(who, when, [{field, old, new}]) in the same update_one that $set-s the new
values, filtered on the old values, so two concurrent edits can't both
apply against the same "old" (the loser gets 409). Nothing removes or
rewrites an edit.

Attachments (B10) go through app/storage.py (local or S3, QNA-009) under the
key prefix field-log/. Size is capped by FIELD_LOG_ATTACHMENT_MAX_MB, the
type is decided from the file's leading bytes (PDF, JPEG, PNG only), and the
sha256 computed while writing is stored and re-checked on download.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from io import BytesIO
from pathlib import PurePosixPath
from typing import Annotated, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ..auth.deps import get_current_user
from ..config import get_settings
from ..db import get_db
from ..models.field_log import (
    EDITABLE_FIELDS,
    FieldAttachment,
    FieldAttachmentDoc,
    FieldChange,
    FieldEntryDoc,
    FieldEntryEdit,
    FieldEntryKind,
)
from ..models.user import UserProfile, UserRole
from ..storage import StorageError, storage_for_uri, storage_from_settings, upload_key

router = APIRouter(prefix="/field-log", tags=["field-log"])
logger = logging.getLogger(__name__)

_CURATOR_ROLES = (UserRole.curator, UserRole.admin, UserRole.company_owner)

ENTRIES = "field_log_entries"
ATTACHMENTS = "field_log_attachments"
ATTACHMENT_KEY_PREFIX = "field-log/"

# Content types accepted for attachments, keyed by the leading bytes that
# identify them. The client's declared type and extension are not trusted:
# a .png that starts with "%PDF-" is stored and served as a PDF, and an
# .html renamed to .png is refused.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)
ALLOWED_ATTACHMENT_TYPES = tuple(ct for _, ct in _MAGIC)


class CreateFieldEntryRequest(BaseModel):
    analysis_id: str
    kind: FieldEntryKind
    body: str
    anchor_sequence_id: Optional[str] = None
    reply_to: Optional[str] = None


class UpdateFieldEntryRequest(BaseModel):
    """Omitted fields are left alone; `anchor_sequence_id: null` clears the
    anchor (model_fields_set tells "omitted" from "null")."""
    body: Optional[str] = None
    anchor_sequence_id: Optional[str] = None


def _actor_name(user: UserProfile) -> str:
    return user.display_name or user.email


async def _check_analysis_access(db, analysis_id: str, current_user: UserProfile) -> None:
    analysis_doc = await db["analysis_results"].find_one({"analysis_id": analysis_id})
    if not analysis_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis_doc.get("user_id") != current_user.user_id and current_user.role not in _CURATOR_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


async def _load_entry(db, entry_id: str, current_user: UserProfile) -> dict:
    """The entry doc, after checking the caller may see its analysis."""
    doc = await db[ENTRIES].find_one({"entry_id": entry_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    await _check_analysis_access(db, doc["analysis_id"], current_user)
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------

@router.post("/entries", response_model=FieldEntryDoc, status_code=status.HTTP_201_CREATED)
async def create_entry(
    body: CreateFieldEntryRequest,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """Log a field note or post a team-discussion comment."""
    if not body.body.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Entry body cannot be empty")

    db = get_db()
    await _check_analysis_access(db, body.analysis_id, current_user)

    if body.reply_to:
        parent = await db[ENTRIES].find_one({"entry_id": body.reply_to, "analysis_id": body.analysis_id})
        if not parent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent entry not found")

    entry = FieldEntryDoc(
        analysis_id=body.analysis_id,
        kind=body.kind,
        author_id=current_user.user_id,
        author_name=_actor_name(current_user),
        body=body.body.strip(),
        anchor_sequence_id=body.anchor_sequence_id,
        reply_to=body.reply_to,
    )
    await db[ENTRIES].insert_one(entry.model_dump())
    return entry


@router.get("/entries", response_model=list[FieldEntryDoc])
async def list_entries(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    analysis_id: str,
    kind: Optional[FieldEntryKind] = None,
):
    """List field notes and/or comments for one analysis, oldest first.
    Each entry carries its full edit history (`edits`)."""
    db = get_db()
    await _check_analysis_access(db, analysis_id, current_user)

    query: dict = {"analysis_id": analysis_id}
    if kind:
        query["kind"] = kind

    docs = []
    async for doc in db[ENTRIES].find(query).sort("created_at", 1):
        doc.pop("_id", None)
        docs.append(FieldEntryDoc(**doc))
    return docs


@router.get("/entries/{entry_id}", response_model=FieldEntryDoc)
async def get_entry(
    entry_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """One entry with its edit history, oldest edit first."""
    db = get_db()
    return FieldEntryDoc(**await _load_entry(db, entry_id, current_user))


@router.patch("/entries/{entry_id}", response_model=FieldEntryDoc)
async def update_entry(
    entry_id: str,
    body: UpdateFieldEntryRequest,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """
    Edit a note or comment's body and/or anchor. The previous values are
    kept: one FieldEntryEdit (editor, time, field old -> new) is appended to
    `edits`. A PATCH that changes nothing returns the entry as is and
    records nothing.
    """
    requested = {f: getattr(body, f) for f in EDITABLE_FIELDS if f in body.model_fields_set}
    if not requested:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Nothing to update; send one of: {', '.join(EDITABLE_FIELDS)}",
        )
    if "body" in requested:
        if requested["body"] is None or not requested["body"].strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Entry body cannot be empty")
        requested["body"] = requested["body"].strip()

    db = get_db()
    doc = await _load_entry(db, entry_id, current_user)
    if doc.get("author_id") != current_user.user_id and current_user.role not in _CURATOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the entry's author or a curator can edit it",
        )

    changes = [
        FieldChange(field=f, old=doc.get(f), new=v)
        for f, v in requested.items()
        if doc.get(f) != v
    ]
    if not changes:
        return FieldEntryDoc(**doc)

    edit = FieldEntryEdit(
        editor_id=current_user.user_id,
        editor_name=_actor_name(current_user),
        changes=changes,
    )
    # Filter on the values this edit says it replaces: if another PATCH got
    # in first, nothing matches and the history never claims an "old" value
    # the entry didn't have.
    match = {"entry_id": entry_id, **{c.field: c.old for c in changes}}
    new_values = {c.field: c.new for c in changes}
    result = await db[ENTRIES].update_one(
        match,
        {
            "$set": {**new_values, "updated_at": edit.edited_at},
            "$push": {"edits": edit.model_dump()},
        },
    )
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entry was changed by someone else; reload and try again",
        )

    doc.update(new_values)
    doc["updated_at"] = edit.edited_at
    doc["edits"] = [*doc.get("edits", []), edit.model_dump()]
    return FieldEntryDoc(**doc)


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

def _sniff_content_type(head: bytes) -> Optional[str]:
    for magic, content_type in _MAGIC:
        if head.startswith(magic):
            return content_type
    return None


@router.post("/attachments", response_model=FieldAttachment, status_code=status.HTTP_201_CREATED)
async def create_attachment(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    analysis_id: str = Form(...),
    entry_id: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """Attach a PDF, JPEG or PNG to an analysis's field log (optionally to
    one entry of it). Attachments are permanent, like entries."""
    settings = get_settings()
    max_bytes = settings.field_log_attachment_max_mb * 1024 * 1024

    db = get_db()
    await _check_analysis_access(db, analysis_id, current_user)
    entry_id = (entry_id or "").strip() or None
    if entry_id:
        entry = await db[ENTRIES].find_one({"entry_id": entry_id, "analysis_id": analysis_id})
        if not entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")

    # Read one byte past the cap so an oversize file is refused without
    # holding all of it.
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Attachment exceeds maximum size of {settings.field_log_attachment_max_mb}MB",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Attachment is empty")
    content_type = _sniff_content_type(content[:16])
    if content_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Attachment must be a PDF, JPEG or PNG file",
        )

    # Keep only the base name: a browser may send a path ("C:\\fakepath\\x.png").
    filename = PurePosixPath((file.filename or "").replace("\\", "/")).name or "attachment"
    attachment_id = f"fla_{uuid.uuid4().hex[:16]}"
    store = storage_from_settings(settings)
    key = ATTACHMENT_KEY_PREFIX + upload_key(attachment_id, filename)
    try:
        stored = await run_in_threadpool(store.put, key, BytesIO(content))
    except Exception as exc:  # MinIO/S3 down, bad credentials, disk full
        logger.exception("field-log attachment %s: storage write to %s failed", attachment_id, store.uri(key))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Attachment storage unavailable ({type(exc).__name__}); nothing was saved",
        ) from exc

    doc = FieldAttachmentDoc(
        attachment_id=attachment_id,
        analysis_id=analysis_id,
        entry_id=entry_id,
        uploader_id=current_user.user_id,
        uploader_name=_actor_name(current_user),
        original_filename=filename,
        content_type=content_type,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.sha256,
        storage_uri=stored.uri,
        storage_key=stored.key,
    )
    await db[ATTACHMENTS].insert_one(doc.model_dump())
    return doc


@router.get("/attachments", response_model=list[FieldAttachment])
async def list_attachments(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    analysis_id: str,
):
    """Attachments for one analysis, oldest first."""
    db = get_db()
    await _check_analysis_access(db, analysis_id, current_user)
    docs = []
    async for doc in db[ATTACHMENTS].find({"analysis_id": analysis_id}).sort("created_at", 1):
        doc.pop("_id", None)
        docs.append(FieldAttachmentDoc(**doc))
    return docs


def _read_verified(uri: str, expected_sha: str) -> bytes:
    storage, key = storage_for_uri(uri, get_settings())
    body = storage.open(key)
    try:
        data = body.read()
    finally:
        body.close()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha:
        raise StorageError(f"checksum mismatch for {uri}: recorded {expected_sha}, stored bytes hash to {actual}")
    return data


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """The attachment's bytes, checked against the sha256 recorded at upload.
    Always served as a download (Content-Disposition: attachment, nosniff),
    never rendered inline from the API origin."""
    db = get_db()
    raw = await db[ATTACHMENTS].find_one({"attachment_id": attachment_id})
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    await _check_analysis_access(db, raw["analysis_id"], current_user)
    raw.pop("_id", None)
    doc = FieldAttachmentDoc(**raw)

    try:
        data = await run_in_threadpool(_read_verified, doc.storage_uri, doc.checksum_sha256)
    except StorageError as exc:
        logger.error("field-log attachment %s: %s", attachment_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Attachment bytes are missing or failed their checksum",
        ) from exc
    except Exception as exc:  # backend unreachable
        logger.exception("field-log attachment %s: storage read failed", attachment_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Attachment storage unavailable ({type(exc).__name__})",
        ) from exc

    ascii_name = doc.original_filename.encode("ascii", "replace").decode().replace('"', "_")
    return Response(
        content=data,
        media_type=doc.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(doc.original_filename)}'
            ),
            "X-Content-Type-Options": "nosniff",
            "X-Checksum-SHA256": doc.checksum_sha256,
        },
    )
