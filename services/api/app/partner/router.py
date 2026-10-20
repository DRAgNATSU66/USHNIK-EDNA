"""
Partner API (Academia / Legislative / Industrial pages).

GET  /partner/summary   aggregation over uploads, analyses, reviews,
                        environmental context, field-log tasks and audits
                        (t-1026-2, B16)
POST /partner/audits    record an audit (t-1028-1, M1)
GET  /partner/audits    list audits, newest first, filtered
GET  /partner/incidents analyses with contamination/novelty flags or open
                        urgent reviews, plus those reviews (t-1028-2)
GET  /partner/tasks     field-log tasks on the analyses in scope (t-1028-2)

Scope: by default the caller's own uploads and analyses (scope=mine). The
whole deployment (scope=all) or another user's data (user_id=...) needs
admin or company_owner -- the same roles that may read any upload
(app/uploads/access.py). There is no project entity in the data model, so
owner + date range is the only scoping.

Audits: anyone but a viewer may record one; created_by is the caller. A
target of kind upload/analysis must exist and be visible to the caller.
Listing returns the caller's own audits, or everyone's for admin /
company_owner. Records are written once; there is no edit route yet.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.deps import get_current_user
from ..db import get_db
from ..models.user import UserProfile, UserRole
from ..uploads.access import can_view_upload
from ..models.field_log import TaskStatus
from .incidents import build_incidents, build_tasks
from .models import (
    AuditDoc, AuditStatus, AuditTargetKind, CreateAuditRequest, ListScopeInfo, PartnerIncidents, PartnerSummary,
    PartnerTasks, SummaryInterval, SummaryScope, SummaryScopeInfo,
)
from .summary import AUDITS, TOP_TAXA_DEFAULT, TOP_TAXA_MAX, build_summary, date_window

router = APIRouter(prefix="/partner", tags=["partner"])

# May aggregate over every user's data.
_ALL_DATA_ROLES = (UserRole.admin, UserRole.company_owner)
# May open any analysis (same set as app/field_log/router.py).
_CURATOR_ROLES = (UserRole.curator, UserRole.admin, UserRole.company_owner)

AUDIT_LIST_DEFAULT = 50
AUDIT_LIST_MAX = 200


def _resolve_scope(
    current_user: UserProfile,
    scope: SummaryScope,
    user_id: Optional[str],
    date_from: Optional[date],
    date_to: Optional[date],
) -> tuple[str, Optional[str]]:
    """(mode, owner user_id or None for everyone) for the summary, incidents
    and tasks routes; 403 when the caller may not read that scope."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="date_from must be on or before date_to")

    privileged = current_user.role in _ALL_DATA_ROLES
    if user_id is not None and user_id != current_user.user_id:
        if not privileged:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Only admin or company_owner can summarise another user's data")
        return "user", user_id
    if user_id is not None:
        return "mine", user_id
    if scope == "all":
        if not privileged:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Only admin or company_owner can summarise all users' data")
        return "all", None
    return "mine", current_user.user_id


@router.get("/summary", response_model=PartnerSummary)
async def get_partner_summary(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    scope: SummaryScope = "mine",
    user_id: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    interval: SummaryInterval = "day",
    top_taxa: Annotated[int, Query(ge=1, le=TOP_TAXA_MAX)] = TOP_TAXA_DEFAULT,
):
    """
    Counts and time series of uploads/analyses, route and result-class
    distribution, novelty/contamination flags, review states, top taxa
    (when results carry a predicted taxon), environmental-context coverage
    with sources and retrieval times, and per-site markers. Every number is
    counted from the database on this request; `definitions` says how and
    `notes` says what is empty or truncated.
    """
    mode, owner = _resolve_scope(current_user, scope, user_id, date_from, date_to)
    info = SummaryScopeInfo(mode=mode, user_id=owner, date_from=date_from, date_to=date_to, interval=interval)
    return await build_summary(
        get_db(),
        scope=info,
        owner_filter={} if owner is None else {"user_id": owner},
        top_taxa=top_taxa,
    )


# ---------------------------------------------------------------------------
# Audits (t-1028-1, M1)
# ---------------------------------------------------------------------------

async def _check_target(db, kind: AuditTargetKind, ref: Optional[str], user: UserProfile) -> None:
    """upload/analysis targets must exist and be visible to the caller."""
    if kind == AuditTargetKind.upload:
        doc = await db["uploads"].find_one({"upload_id": ref})
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target upload not found")
        if not can_view_upload(doc.get("user_id"), user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to target upload")
    elif kind == AuditTargetKind.analysis:
        doc = await db["analysis_results"].find_one({"analysis_id": ref})
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target analysis not found")
        if doc.get("user_id") != user.user_id and user.role not in _CURATOR_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to target analysis")


def _naive_utc(ts: datetime) -> datetime:
    # Stored like every other created_at in this API: naive UTC.
    return ts.astimezone(timezone.utc).replace(tzinfo=None) if ts.tzinfo else ts


@router.post("/audits", response_model=AuditDoc, status_code=status.HTTP_201_CREATED)
async def create_audit(
    body: CreateAuditRequest,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """Record an audit: what was audited (target), its scope, findings and
    status. created_by / created_by_name come from the caller's token."""
    if current_user.role == UserRole.viewer:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewers cannot record audits")

    db = get_db()
    await _check_target(db, body.target.kind, body.target.ref, current_user)

    now = datetime.utcnow()
    completed_at = None
    if body.status == AuditStatus.completed:
        completed_at = _naive_utc(body.completed_at) if body.completed_at else now
    audit = AuditDoc(
        target=body.target,
        scope=body.scope,
        findings=body.findings,
        status=body.status,
        due_date=body.due_date.isoformat() if body.due_date else None,
        completed_at=completed_at,
        created_by=current_user.user_id,
        created_by_name=current_user.display_name or current_user.email,
        created_at=now,
    )
    await db[AUDITS].insert_one(audit.model_dump())
    return audit


@router.get("/audits", response_model=list[AuditDoc])
async def list_audits(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    status_: Annotated[Optional[AuditStatus], Query(alias="status")] = None,
    target_kind: Optional[AuditTargetKind] = None,
    target_ref: Optional[str] = None,
    created_by: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: Annotated[int, Query(ge=1, le=AUDIT_LIST_MAX)] = AUDIT_LIST_DEFAULT,
):
    """Audits, newest first. Your own, or everyone's for admin /
    company_owner (narrow with created_by). date_from/date_to filter
    created_at, UTC, both days inclusive."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="date_from must be on or before date_to")

    query: dict = {}
    if current_user.role in _ALL_DATA_ROLES:
        if created_by:
            query["created_by"] = created_by
    elif created_by and created_by != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only admin or company_owner can list other users' audits")
    else:
        query["created_by"] = current_user.user_id
    if status_:
        query["status"] = status_.value
    if target_kind:
        query["target.kind"] = target_kind.value
    if target_ref:
        query["target.ref"] = target_ref
    window = date_window(date_from, date_to)
    if window:
        query["created_at"] = window

    docs = []
    async for doc in get_db()[AUDITS].find(query).sort("created_at", -1).limit(limit):
        doc.pop("_id", None)
        docs.append(AuditDoc(**doc))
    return docs


# ---------------------------------------------------------------------------
# Incidents + field-log tasks (t-1028-2, Industrial page)
# ---------------------------------------------------------------------------

INCIDENT_LIST_DEFAULT = 50
INCIDENT_LIST_MAX = 200


@router.get("/incidents", response_model=PartnerIncidents)
async def list_incidents(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    scope: SummaryScope = "mine",
    user_id: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: Annotated[int, Query(ge=1, le=INCIDENT_LIST_MAX)] = INCIDENT_LIST_DEFAULT,
):
    """
    Analyses in scope that carry a contamination flag, a novelty flag or an
    open urgent review (newest first), with the flag counts, contamination
    types, open/urgent review counts and the first flagged sequences; plus
    the open urgent reviews themselves (oldest first). Same scope and flag
    rules as GET /partner/summary; `definitions` states them.
    """
    mode, owner = _resolve_scope(current_user, scope, user_id, date_from, date_to)
    return await build_incidents(
        get_db(),
        scope=ListScopeInfo(mode=mode, user_id=owner, date_from=date_from, date_to=date_to),
        owner_filter={} if owner is None else {"user_id": owner},
        limit=limit,
    )


@router.get("/tasks", response_model=PartnerTasks)
async def list_partner_tasks(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    scope: SummaryScope = "mine",
    user_id: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status_: Annotated[Optional[TaskStatus], Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=INCIDENT_LIST_MAX)] = INCIDENT_LIST_DEFAULT,
):
    """
    Field-log tasks (kind=task) on the analyses in scope, without edit
    history: not-done first, then by due date, then newest. Tasks are
    created and edited through /field-log/entries; this is read-only.
    """
    mode, owner = _resolve_scope(current_user, scope, user_id, date_from, date_to)
    return await build_tasks(
        get_db(),
        scope=ListScopeInfo(mode=mode, user_id=owner, date_from=date_from, date_to=date_to),
        owner_filter={} if owner is None else {"user_id": owner},
        status=status_,
        limit=limit,
    )
