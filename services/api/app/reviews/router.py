from datetime import datetime, timezone
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth.deps import get_current_user, require_role
from ..models.user import UserProfile, UserRole
from ..models.review import ReviewDoc, ReviewState, ReviewDecision, ReviewType, TriagePriority
from ..db import get_db
from .curation import (
    queue_stats,
    triage_review,
    add_evidence,
    create_monthly_training_batch,
    freeze_training_batch,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])

_CURATOR_ROLES = (UserRole.curator, UserRole.admin, UserRole.company_owner)
_ADMIN_ROLES = (UserRole.admin, UserRole.company_owner)


# ---------------------------------------------------------------------------
# Request / response bodies
# ---------------------------------------------------------------------------

class CreateReviewRequest(BaseModel):
    analysis_id: str
    sequence_id: str
    correction_type: str
    review_type: ReviewType = ReviewType.manual_correction
    proposed_taxon: Optional[str] = None
    is_novelty: Optional[bool] = None
    is_contamination: Optional[bool] = None
    is_low_quality: Optional[bool] = None
    evidence_notes: Optional[str] = None


class ReviewDecisionRequest(BaseModel):
    decision: ReviewDecision
    notes: Optional[str] = None


class TriageRequest(BaseModel):
    priority: TriagePriority = TriagePriority.normal
    notes: Optional[str] = None


class AddEvidenceRequest(BaseModel):
    evidence_text: str
    evidence_attachments: list[str] = []


class CreateBatchRequest(BaseModel):
    route: str
    month_year: str  # e.g. "2026-05"


# ---------------------------------------------------------------------------
# Submit a review (any authenticated user)
# ---------------------------------------------------------------------------

@router.get("/by-sequence", response_model=list[ReviewDoc])
async def list_reviews_for_sequence(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    analysis_id: str,
    sequence_id: str,
):
    """
    List the correction history for one sequence within one analysis,
    oldest first. Powers Species Correction's conflict detection (competing
    proposals on the same sequence) and version history -- unlike
    /reviews/queue, this is available to the analysis owner, not just
    curators, since a researcher needs to see prior corrections on their
    own data before submitting a new one.
    """
    db = get_db()
    analysis_doc = await db["analysis_results"].find_one({"analysis_id": analysis_id})
    if not analysis_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis_doc.get("user_id") != current_user.user_id and current_user.role not in _CURATOR_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    docs = []
    async for doc in db["reviews"].find(
        {"analysis_id": analysis_id, "sequence_id": sequence_id}
    ).sort("created_at", 1):
        doc.pop("_id", None)
        docs.append(ReviewDoc(**doc))
    return docs


@router.post("", response_model=ReviewDoc, status_code=status.HTTP_201_CREATED)
async def submit_review(
    body: CreateReviewRequest,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """Submit an expert correction/review for a sequence result."""
    db = get_db()
    review = ReviewDoc(
        analysis_id=body.analysis_id,
        sequence_id=body.sequence_id,
        submitted_by=current_user.user_id,
        correction_type=body.correction_type,
        review_type=body.review_type,
        proposed_taxon=body.proposed_taxon,
        is_novelty=body.is_novelty,
        is_contamination=body.is_contamination,
        is_low_quality=body.is_low_quality,
        evidence_notes=body.evidence_notes,
    )
    await db["reviews"].insert_one(review.model_dump())
    return review


# ---------------------------------------------------------------------------
# Queue (curator+)
# ---------------------------------------------------------------------------

@router.get("/queue", response_model=list[ReviewDoc])
async def get_review_queue(
    current_user: Annotated[UserProfile, Depends(require_role(*_CURATOR_ROLES))],
    state: Optional[str] = None,
    review_type: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
):
    """Return the pending review queue. Curator/admin only."""
    db = get_db()
    query: dict = {}

    if state:
        query["state"] = state
    else:
        query["state"] = {"$in": [ReviewState.submitted, ReviewState.triaged, ReviewState.needs_evidence]}

    if review_type:
        query["review_type"] = review_type
    if priority:
        query["triage_priority"] = priority

    sort = [("triage_priority", 1), ("created_at", 1)]  # urgent first (lex ascending a→z: low<normal<urgent... use custom)
    # Urgent first: map priority to sort key
    pipeline = [
        {"$match": query},
        {"$addFields": {"_priority_order": {
            "$switch": {
                "branches": [
                    {"case": {"$eq": ["$triage_priority", "urgent"]}, "then": 0},
                    {"case": {"$eq": ["$triage_priority", "normal"]}, "then": 1},
                ],
                "default": 2,
            },
        }}},
        {"$sort": {"_priority_order": 1, "created_at": 1}},
        {"$skip": skip},
        {"$limit": limit},
    ]
    docs = []
    async for doc in db["reviews"].aggregate(pipeline):
        doc.pop("_id", None)
        doc.pop("_priority_order", None)
        docs.append(ReviewDoc(**doc))
    return docs


@router.get("/stats")
async def get_queue_stats(
    current_user: Annotated[UserProfile, Depends(require_role(*_CURATOR_ROLES))],
):
    """Return aggregate counts for the curator dashboard."""
    db = get_db()
    return await queue_stats(db)


# ---------------------------------------------------------------------------
# Single review operations
# ---------------------------------------------------------------------------

@router.get("/{review_id}", response_model=ReviewDoc)
async def get_review(
    review_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    db = get_db()
    doc = await db["reviews"].find_one({"review_id": review_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    # Submitter or curator can view
    if doc.get("submitted_by") != current_user.user_id and current_user.role not in _CURATOR_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return ReviewDoc(**{k: v for k, v in doc.items() if k != "_id"})


@router.post("/{review_id}/triage")
async def post_triage(
    review_id: str,
    body: TriageRequest,
    current_user: Annotated[UserProfile, Depends(require_role(*_CURATOR_ROLES))],
):
    """Assign triage priority and move review to triaged state."""
    db = get_db()
    updated = await triage_review(db, review_id, body.priority, current_user.user_id, body.notes)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    await db["audit_logs"].insert_one({
        "action": "review_triaged",
        "review_id": review_id,
        "priority": body.priority,
        "actor_id": current_user.user_id,
        "actor_role": current_user.role,
        "timestamp": datetime.now(timezone.utc),
    })

    return {"ok": True, "review_id": review_id, "priority": body.priority, "state": ReviewState.triaged}


@router.post("/{review_id}/evidence")
async def post_evidence(
    review_id: str,
    body: AddEvidenceRequest,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """Add supporting evidence to a review (submitter or curator)."""
    db = get_db()
    doc = await db["reviews"].find_one({"review_id": review_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    # Only submitter or curators can add evidence
    if doc.get("submitted_by") != current_user.user_id and current_user.role not in _CURATOR_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    closed_states = {ReviewState.accepted, ReviewState.rejected, ReviewState.duplicate}
    if doc.get("state") in closed_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Review is {doc['state']} and cannot be updated",
        )

    updated = await add_evidence(
        db, review_id, body.evidence_text, body.evidence_attachments, current_user.user_id
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return updated


@router.post("/{review_id}/decision")
async def post_review_decision(
    review_id: str,
    body: ReviewDecisionRequest,
    current_user: Annotated[UserProfile, Depends(require_role(*_CURATOR_ROLES))],
):
    """Record a curator/admin decision on a review. All decisions are audit-logged."""
    db = get_db()
    doc = await db["reviews"].find_one({"review_id": review_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    new_state_map = {
        ReviewDecision.accept: ReviewState.accepted,
        ReviewDecision.reject: ReviewState.rejected,
        ReviewDecision.needs_evidence: ReviewState.needs_evidence,
        ReviewDecision.mark_duplicate: ReviewState.duplicate,
        ReviewDecision.company_verify: ReviewState.company_verified,
    }
    new_state = new_state_map[body.decision]
    now = datetime.now(timezone.utc)

    await db["reviews"].update_one(
        {"review_id": review_id},
        {"$set": {
            "state": new_state,
            "decided_by": current_user.user_id,
            "decision_notes": body.notes,
            "decided_at": now,
        }},
    )

    # Mirror accepted/rejected decisions to Supabase (best-effort)
    try:
        from ..db.supabase_client import SupabaseClient
        await SupabaseClient.update_review_state(review_id, new_state, current_user.user_id, body.notes)
    except Exception:
        pass

    await db["audit_logs"].insert_one({
        "action": "review_decision",
        "review_id": review_id,
        "decision": body.decision,
        "new_state": new_state,
        "actor_id": current_user.user_id,
        "actor_role": current_user.role,
        "notes": body.notes,
        "timestamp": now,
    })

    return {"ok": True, "review_id": review_id, "new_state": new_state}


# ---------------------------------------------------------------------------
# Training batch endpoints (admin+)
# ---------------------------------------------------------------------------

@router.post("/batch/create")
async def post_create_batch(
    body: CreateBatchRequest,
    current_user: Annotated[UserProfile, Depends(require_role(*_ADMIN_ROLES))],
):
    """
    Assemble accepted reviews into a monthly training batch.

    Anti-poisoning: creates a batch record only. Actual model retraining
    is a separate manual step (Phase 14) after a human admin reviews the
    frozen batch contents.
    """
    db = get_db()
    result = await create_monthly_training_batch(
        db,
        route=body.route,
        month_year=body.month_year,
        created_by=current_user.user_id,
    )
    return result


@router.post("/batch/{batch_id}/freeze")
async def post_freeze_batch(
    batch_id: str,
    current_user: Annotated[UserProfile, Depends(require_role(*_ADMIN_ROLES))],
):
    """
    Freeze a training batch — no further reviews can be added.
    After freezing the batch is ready for Phase 14 model retraining.
    """
    db = get_db()
    result = await freeze_training_batch(db, batch_id, current_user.user_id)
    return result
