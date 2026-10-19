"""
Partner API (Academia / Legislative / Industrial pages).

GET /partner/summary   aggregation over uploads, analyses, reviews and
                       environmental context (t-1026-2, B16)

Scope: by default the caller's own uploads and analyses (scope=mine). The
whole deployment (scope=all) or another user's data (user_id=...) needs
admin or company_owner -- the same roles that may read any upload
(app/uploads/access.py). There is no project entity in the data model, so
owner + date range is the only scoping.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.deps import get_current_user
from ..db import get_db
from ..models.user import UserProfile, UserRole
from .models import PartnerSummary, SummaryInterval, SummaryScope, SummaryScopeInfo
from .summary import TOP_TAXA_DEFAULT, TOP_TAXA_MAX, build_summary

router = APIRouter(prefix="/partner", tags=["partner"])

# May aggregate over every user's data.
_ALL_DATA_ROLES = (UserRole.admin, UserRole.company_owner)


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
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="date_from must be on or before date_to")

    privileged = current_user.role in _ALL_DATA_ROLES
    if user_id is not None and user_id != current_user.user_id:
        if not privileged:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Only admin or company_owner can summarise another user's data")
        mode, owner = "user", user_id
    elif user_id is not None:
        mode, owner = "mine", user_id
    elif scope == "all":
        if not privileged:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Only admin or company_owner can summarise all users' data")
        mode, owner = "all", None
    else:
        mode, owner = "mine", current_user.user_id

    info = SummaryScopeInfo(mode=mode, user_id=owner, date_from=date_from, date_to=date_to, interval=interval)
    return await build_summary(
        get_db(),
        scope=info,
        owner_filter={} if owner is None else {"user_id": owner},
        top_taxa=top_taxa,
    )
