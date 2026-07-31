"""
Curation service — Phase 9 review workflow.

Responsibilities:
  - Triage incoming reviews (submitted → triaged, with priority)
  - Collect evidence on reviews in needs_evidence state
  - Query queue statistics for curator dashboard
  - Assemble monthly training batches from accepted reviews
  - Freeze training batches and register new model versions

Anti-poisoning rule:
  Reviews enter the queue immediately. Models are updated ONLY after a curator
  has explicitly accepted a review AND a monthly batch has been frozen by an admin.
  No live model update path exists — batch creation is the only gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..models.review import ReviewDoc, ReviewState, ReviewType, TriagePriority
from ..db.supabase_client import SupabaseClient


# ---------------------------------------------------------------------------
# Queue statistics
# ---------------------------------------------------------------------------

async def queue_stats(db: AsyncIOMotorDatabase) -> dict[str, Any]:
    """
    Return aggregate counts for the curator dashboard.

    Counts are segmented by review_type and state so the curator can
    see at a glance how many auto-queued novelty/contamination flags
    are pending vs how many manual corrections need triage.
    """
    pipeline = [
        {"$group": {
            "_id": {"state": "$state", "review_type": "$review_type"},
            "count": {"$sum": 1},
        }},
    ]
    result: dict[str, Any] = {
        "total_pending": 0,
        "by_state": {},
        "by_type": {},
        "auto_novelty_pending": 0,
        "auto_contamination_pending": 0,
    }

    pending_states = {ReviewState.submitted, ReviewState.triaged, ReviewState.needs_evidence}

    async for doc in db["reviews"].aggregate(pipeline):
        state = doc["_id"]["state"]
        rtype = doc["_id"]["review_type"]
        count = doc["count"]

        result["by_state"][state] = result["by_state"].get(state, 0) + count
        result["by_type"][rtype] = result["by_type"].get(rtype, 0) + count

        if state in pending_states:
            result["total_pending"] += count
            if rtype == ReviewType.auto_novelty:
                result["auto_novelty_pending"] += count
            elif rtype == ReviewType.auto_contamination:
                result["auto_contamination_pending"] += count

    return result


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------

async def triage_review(
    db: AsyncIOMotorDatabase,
    review_id: str,
    priority: TriagePriority,
    triaged_by: str,
    notes: str | None = None,
) -> ReviewDoc | None:
    """
    Move a review from submitted → triaged and assign priority.

    Returns the updated ReviewDoc, or None if not found.
    Silently allows re-triage (triaged → triaged) to allow priority changes.
    """
    doc = await db["reviews"].find_one({"review_id": review_id})
    if doc is None:
        return None

    now = datetime.now(timezone.utc)
    update: dict[str, Any] = {
        "state": ReviewState.triaged,
        "triage_priority": priority,
        "triaged_by": triaged_by,
        "triaged_at": now,
    }
    if notes:
        update["evidence_notes"] = notes

    await db["reviews"].update_one({"review_id": review_id}, {"$set": update})

    # Mirror to Supabase (best-effort; do not fail the request if Supabase is down)
    try:
        await SupabaseClient.update_review_state(review_id, ReviewState.triaged, triaged_by, notes)
    except Exception:
        pass

    updated = {**{k: v for k, v in doc.items() if k != "_id"}, **update}
    return ReviewDoc(**updated)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

async def add_evidence(
    db: AsyncIOMotorDatabase,
    review_id: str,
    evidence_text: str,
    evidence_attachments: list[str],
    submitted_by: str,
) -> ReviewDoc | None:
    """
    Append additional evidence to a review.

    Valid for any state except accepted/rejected/duplicate.
    The review transitions to submitted if it was in needs_evidence state,
    signalling to curators that the user has responded.
    """
    doc = await db["reviews"].find_one({"review_id": review_id})
    if doc is None:
        return None

    closed_states = {ReviewState.accepted, ReviewState.rejected, ReviewState.duplicate}
    if doc.get("state") in closed_states:
        return None  # caller should raise 409

    update: dict[str, Any] = {
        "evidence_notes": evidence_text,
    }
    if evidence_attachments:
        update["$push_attachments"] = evidence_attachments  # handled below

    # Use $push for attachments, $set for text
    mongo_update: dict[str, Any] = {"$set": {"evidence_notes": evidence_text}}
    if evidence_attachments:
        mongo_update["$push"] = {"evidence_attachments": {"$each": evidence_attachments}}

    # If curator requested evidence, transition back to submitted so it re-appears in queue
    if doc.get("state") == ReviewState.needs_evidence:
        mongo_update["$set"]["state"] = ReviewState.submitted

    await db["reviews"].update_one({"review_id": review_id}, mongo_update)

    refreshed = await db["reviews"].find_one({"review_id": review_id})
    if refreshed is None:
        return None
    return ReviewDoc(**{k: v for k, v in refreshed.items() if k != "_id"})


# ---------------------------------------------------------------------------
# Monthly training batch
# ---------------------------------------------------------------------------

async def create_monthly_training_batch(
    db: AsyncIOMotorDatabase,
    route: str,
    month_year: str,
    created_by: str,
) -> dict[str, Any]:
    """
    Collect all accepted reviews for a route into a training batch.

    Steps:
      1. Find reviews: state=accepted, correction_type includes the route,
         training_batch_id is None.
      2. Create or fetch the batch in Supabase.
      3. Insert a curated_sequence row in Supabase for each accepted review.
      4. Mark each MongoDB review as included_in_training_batch and stamp the batch_id.

    Returns a summary dict with batch_id and sequence_count.

    Anti-poisoning: this function only assembles a batch. The actual model
    retrain is a manual step (Phase 14) that runs after a human admin reviews
    the frozen batch.
    """
    import uuid

    batch_id = f"tbatch_{month_year.replace('-', '')}_{route[:8]}_{uuid.uuid4().hex[:8]}"

    # Find eligible accepted reviews for this route
    query = {
        "state": ReviewState.accepted,
        "training_batch_id": None,
        "$or": [
            {"correction_type": {"$regex": route, "$options": "i"}},
            {"review_type": {"$in": [ReviewType.auto_novelty, ReviewType.auto_contamination]}},
        ],
    }
    cursor = db["reviews"].find(query)
    review_ids: list[str] = []
    seq_data_list: list[dict] = []

    async for doc in cursor:
        review_ids.append(doc["review_id"])
        seq_data_list.append({
            "review_id": doc["review_id"],
            "analysis_id": doc["analysis_id"],
            "sequence_id": doc["sequence_id"],
            "batch_id": batch_id,
            "correction_type": doc.get("correction_type"),
            "proposed_taxon": doc.get("proposed_taxon"),
            "is_novelty": doc.get("is_novelty"),
            "novelty_score": doc.get("novelty_score"),
            "decided_by": doc.get("decided_by"),
        })

    if not review_ids:
        return {"batch_id": batch_id, "sequence_count": 0, "status": "empty"}

    # Supabase batch record (best-effort)
    batch_status = "assembling"
    try:
        await SupabaseClient.get_or_create_training_batch(batch_id, month_year, route, created_by)
        for sd in seq_data_list:
            await SupabaseClient.insert_curated_sequence(sd)
        batch_status = "assembled"
    except Exception:
        batch_status = "assembled_local_only"

    # Stamp each accepted review in MongoDB
    await db["reviews"].update_many(
        {"review_id": {"$in": review_ids}},
        {"$set": {
            "state": ReviewState.included_in_training_batch,
            "training_batch_id": batch_id,
        }},
    )

    # Audit log in MongoDB
    await db["audit_logs"].insert_one({
        "action": "training_batch_created",
        "batch_id": batch_id,
        "route": route,
        "month_year": month_year,
        "sequence_count": len(review_ids),
        "actor_id": created_by,
        "timestamp": datetime.now(timezone.utc),
    })

    return {
        "batch_id": batch_id,
        "sequence_count": len(review_ids),
        "status": batch_status,
        "month_year": month_year,
        "route": route,
    }


async def freeze_training_batch(
    db: AsyncIOMotorDatabase,
    batch_id: str,
    frozen_by: str,
) -> dict[str, Any]:
    """
    Freeze a training batch to prevent further additions.

    After freezing, the batch is ready for Phase 14 model retraining.
    Only admin/company_owner should be able to call this endpoint.
    """
    now = datetime.now(timezone.utc)

    # Freeze in Supabase (best-effort)
    try:
        await SupabaseClient.freeze_training_batch(batch_id)
    except Exception:
        pass

    # Audit log
    await db["audit_logs"].insert_one({
        "action": "training_batch_frozen",
        "batch_id": batch_id,
        "actor_id": frozen_by,
        "timestamp": now,
    })

    return {"batch_id": batch_id, "status": "frozen", "frozen_by": frozen_by, "frozen_at": now.isoformat()}


# ---------------------------------------------------------------------------
# Auto-queue helper (called from worker via MongoDB)
# ---------------------------------------------------------------------------

def build_auto_review(
    analysis_id: str,
    job_id: str,
    seq: dict,
) -> dict:
    """
    Build a review document dict for a sequence flagged by the pipeline.

    Called synchronously from the worker (which has no Supabase access);
    the returned dict is inserted directly into MongoDB.

    Triggers:
      - novelty_score >= 0.45  → auto_novelty review
      - contamination_flagged  → auto_contamination review
      Both can trigger simultaneously; one document is created per trigger type.
    """
    from datetime import datetime, timezone
    import uuid

    novelty_score: float = seq.get("novelty_score", 0.0)
    contamination_flagged: bool = seq.get("contamination_flagged", False)
    contamination_score: float = seq.get("contamination_score", 0.0)

    reviews = []

    if novelty_score >= 0.45:
        reviews.append({
            "review_id": f"rev_{uuid.uuid4().hex[:16]}",
            "analysis_id": analysis_id,
            "sequence_id": seq["sequence_id"],
            "submitted_by": "system",
            "state": ReviewState.submitted,
            "review_type": ReviewType.auto_novelty,
            "triage_priority": TriagePriority.urgent if novelty_score >= 0.70 else TriagePriority.normal,
            "novelty_score": novelty_score,
            "novelty_level": seq.get("novelty_level"),
            "contamination_score": contamination_score,
            "abyss_recommendation": seq.get("abyss_recommendation"),
            "correction_type": "auto_novelty_flag",
            "is_novelty": True,
            "is_contamination": contamination_flagged,
            "evidence_notes": None,
            "evidence_attachments": [],
            "created_at": datetime.now(timezone.utc),
        })

    if contamination_flagged:
        reviews.append({
            "review_id": f"rev_{uuid.uuid4().hex[:16]}",
            "analysis_id": analysis_id,
            "sequence_id": seq["sequence_id"],
            "submitted_by": "system",
            "state": ReviewState.submitted,
            "review_type": ReviewType.auto_contamination,
            "triage_priority": TriagePriority.urgent,
            "novelty_score": novelty_score,
            "novelty_level": seq.get("novelty_level"),
            "contamination_score": contamination_score,
            "contamination_type": seq.get("contamination_type"),
            "abyss_recommendation": seq.get("abyss_recommendation"),
            "correction_type": "auto_contamination_flag",
            "is_novelty": novelty_score >= 0.45,
            "is_contamination": True,
            "evidence_notes": None,
            "evidence_attachments": [],
            "created_at": datetime.now(timezone.utc),
        })

    return reviews
