"""
Reports API — Phase 11.

Endpoints:
  GET /reports/{analysis_id}                Full structured report (JSON)
  GET /reports/{analysis_id}/summary        Summary section only
  GET /reports/{analysis_id}/novelty        Possible novelty table
  GET /reports/{analysis_id}/contamination  Contamination warnings table
  GET /reports/{analysis_id}/export/json    Downloadable JSON file
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from ..auth.deps import get_current_user
from ..models.user import UserProfile, UserRole
from ..db import get_db
from .builder import build_report
from .models import AnalysisReport, REPORT_DISCLAIMER

router = APIRouter(prefix="/reports", tags=["reports"])

_CURATOR_ROLES = (UserRole.curator, UserRole.admin, UserRole.company_owner)


async def _fetch_analysis_and_reviews(
    analysis_id: str,
    current_user: UserProfile,
):
    """
    Shared fetch logic: load analysis doc + its reviews.
    Enforces access control: owner or curator/admin can view.
    Raises 404/403 as appropriate.
    """
    db = get_db()

    doc = await db["analysis_results"].find_one({"analysis_id": analysis_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    if doc.get("user_id") != current_user.user_id and current_user.role not in _CURATOR_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Fetch upload doc for source_file name (best-effort)
    source_file: str | None = None
    upload = await db["uploads"].find_one({"upload_id": doc.get("upload_id", "")})
    if upload:
        source_file = upload.get("original_filename")

    # Fetch all reviews for this analysis
    reviews: list[dict] = []
    async for rev in db["reviews"].find({"analysis_id": analysis_id}):
        rev.pop("_id", None)
        reviews.append(rev)

    doc.pop("_id", None)
    return doc, reviews, source_file


@router.get("/{analysis_id}", response_model=AnalysisReport)
async def get_report(
    analysis_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """
    Return the full structured analysis report.

    Includes: sample metadata, QC summary, route distribution, known species,
    possible novelty table, contamination warnings, biodiversity metrics,
    model versions used, review status, and disclaimer.
    """
    doc, reviews, source_file = await _fetch_analysis_and_reviews(analysis_id, current_user)
    return build_report(doc, reviews, source_file)


@router.get("/{analysis_id}/summary")
async def get_report_summary(
    analysis_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """Return the metadata + QC summary + biodiversity section only."""
    doc, reviews, source_file = await _fetch_analysis_and_reviews(analysis_id, current_user)
    report = build_report(doc, reviews, source_file)
    return {
        "analysis_id": analysis_id,
        "metadata": report.metadata.model_dump(),
        "qc_summary": report.qc_summary.model_dump(),
        "biodiversity": report.biodiversity.model_dump(),
        "review_status": report.review_status.model_dump(),
        "disclaimer": REPORT_DISCLAIMER,
        "generated_at": report.generated_at,
    }


@router.get("/{analysis_id}/novelty")
async def get_novelty_table(
    analysis_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    min_score: float = 0.45,
):
    """
    Return the possible novelty table, optionally filtered by minimum score.
    Results are sorted highest novelty first.
    """
    doc, reviews, source_file = await _fetch_analysis_and_reviews(analysis_id, current_user)
    report = build_report(doc, reviews, source_file)
    entries = [e for e in report.possible_novelty if e.novelty_score >= min_score]
    return {
        "analysis_id": analysis_id,
        "total_flagged": len(entries),
        "entries": [e.model_dump() for e in entries],
        "disclaimer": REPORT_DISCLAIMER,
    }


@router.get("/{analysis_id}/contamination")
async def get_contamination_warnings(
    analysis_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """Return all contamination warnings for the analysis, sorted by score."""
    doc, reviews, source_file = await _fetch_analysis_and_reviews(analysis_id, current_user)
    report = build_report(doc, reviews, source_file)
    return {
        "analysis_id": analysis_id,
        "total_warnings": len(report.contamination_warnings),
        "warnings": [w.model_dump() for w in report.contamination_warnings],
    }


@router.get("/{analysis_id}/export/json")
async def export_report_json(
    analysis_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """
    Download the full report as a JSON file.

    Returns a JSON response with Content-Disposition: attachment so browsers
    prompt a file download. The filename includes the analysis_id and timestamp.
    """
    doc, reviews, source_file = await _fetch_analysis_and_reviews(analysis_id, current_user)
    report = build_report(doc, reviews, source_file)

    # Serialize with datetime support
    payload = report.model_dump()
    json_bytes = json.dumps(payload, indent=2, default=_json_default).encode("utf-8")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"synthveda_report_{analysis_id}_{timestamp}.json"

    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
