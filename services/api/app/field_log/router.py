"""
Field Log API.

Backs the Researcher Mode "Field Log" tab (SYNTHVEDA_BUILD_SPEC.md 2.4):
field notes/anomalies (unthreaded) and team discussion (optionally threaded
one level, optionally anchored to a specific sequence). Both are the same
underlying entry shape, discriminated by `kind`.

Endpoints:
  POST /field-log/entries               Create a note or comment
  GET  /field-log/entries               List entries for one analysis
"""
from __future__ import annotations

from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth.deps import get_current_user
from ..models.user import UserProfile, UserRole
from ..models.field_log import FieldEntryDoc, FieldEntryKind
from ..db import get_db

router = APIRouter(prefix="/field-log", tags=["field-log"])

_CURATOR_ROLES = (UserRole.curator, UserRole.admin, UserRole.company_owner)


class CreateFieldEntryRequest(BaseModel):
    analysis_id: str
    kind: FieldEntryKind
    body: str
    anchor_sequence_id: Optional[str] = None
    reply_to: Optional[str] = None


async def _check_analysis_access(db, analysis_id: str, current_user: UserProfile) -> None:
    analysis_doc = await db["analysis_results"].find_one({"analysis_id": analysis_id})
    if not analysis_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis_doc.get("user_id") != current_user.user_id and current_user.role not in _CURATOR_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


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
        parent = await db["field_log_entries"].find_one({"entry_id": body.reply_to, "analysis_id": body.analysis_id})
        if not parent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent entry not found")

    entry = FieldEntryDoc(
        analysis_id=body.analysis_id,
        kind=body.kind,
        author_id=current_user.user_id,
        author_name=current_user.display_name or current_user.email,
        body=body.body.strip(),
        anchor_sequence_id=body.anchor_sequence_id,
        reply_to=body.reply_to,
    )
    await db["field_log_entries"].insert_one(entry.model_dump())
    return entry


@router.get("/entries", response_model=list[FieldEntryDoc])
async def list_entries(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    analysis_id: str,
    kind: Optional[FieldEntryKind] = None,
):
    """List field notes and/or comments for one analysis, oldest first."""
    db = get_db()
    await _check_analysis_access(db, analysis_id, current_user)

    query: dict = {"analysis_id": analysis_id}
    if kind:
        query["kind"] = kind

    docs = []
    async for doc in db["field_log_entries"].find(query).sort("created_at", 1):
        doc.pop("_id", None)
        docs.append(FieldEntryDoc(**doc))
    return docs
