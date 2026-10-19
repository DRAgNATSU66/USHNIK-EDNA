"""
Review records (B9): review_evidence, curation_decisions, training_batch_items.

MongoDB is the source of truth, as for reviews themselves: every record is a
document in the MongoDB collection of the same name. The Supabase tables of
the same names (migration 20260526000001, amended by 20261019000001) are a
best-effort mirror, like the expert_reviews / training_batches / model_versions
mirrors: a Supabase failure is logged with its traceback and never fails the
request. Each MongoDB document is inserted before the mirror runs, with
`supabase_mirrored` false, and flipped to true only for rows Supabase
accepted, so a slow or failing Supabase can never cost the MongoDB record and
a backfill can find the rows Supabase is missing.

The Supabase rows reference expert_reviews(id), a uuid, so every mirror first
upserts the review's expert_reviews row (keyed by the MongoDB review_id); that
upsert is the only place an expert_reviews row is created (triage still
updates an existing row via SupabaseClient.update_review_state).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..db.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

# Per-sequence result keys left out of the evidence snapshot: the [CLS]
# embedding (hundreds of floats, only used by novelty scoring) and the raw
# sequence (kept in analysis_results; the snapshot keeps its sha256/length).
# Everything else is kept as-is, including the orchestrator's `decision` and
# `decision_trace` when the worker wrote them.
_SNAPSHOT_EXCLUDE = frozenset({"embedding", "sequence"})

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _profile_id(user_id: str | None) -> str | None:
    """user_profiles(id) for a MongoDB user id; auto-queued reviews say "system"."""
    return None if not user_id or user_id == "system" else user_id


async def _mirror(what: str, write: Callable[[], Awaitable[None]]) -> str:
    """
    Run a Supabase mirror write. Returns "written", "not_configured" or
    "failed"; a failure is logged with its traceback, never raised.
    """
    try:
        SupabaseClient._get()
    except RuntimeError:
        return "not_configured"
    try:
        await write()
    except Exception:
        logger.warning("Supabase mirror of %s failed; MongoDB record written, Supabase not",
                       what, exc_info=True)
        return "failed"
    return "written"


def expert_review_row(review: dict) -> dict:
    """A MongoDB review doc as an expert_reviews row (migration 20260526000001)."""
    row = {
        "review_id": review["review_id"],
        "analysis_id": review["analysis_id"],
        "sequence_id": review["sequence_id"],
        "submitted_by": _profile_id(review.get("submitted_by")),
        "correction_type": review.get("correction_type"),
        "proposed_taxon": review.get("proposed_taxon"),
        "is_novelty": review.get("is_novelty"),
        "is_contamination": review.get("is_contamination"),
        "is_low_quality": review.get("is_low_quality"),
        "evidence_notes": review.get("evidence_notes"),
        "state": str(review.get("state") or "submitted"),
        "decided_by": _profile_id(review.get("decided_by")),
        "decision_notes": review.get("decision_notes"),
        "decided_at": _iso(review.get("decided_at")),
    }
    if review.get("created_at") is not None:
        row["created_at"] = _iso(review["created_at"])
    return row


async def _expert_review_uuid(review: dict) -> str:
    row = await SupabaseClient.upsert_review(expert_review_row(review))
    if not row.get("id"):
        raise LookupError(f"expert_reviews upsert for {review['review_id']} returned no id")
    return row["id"]


# ---------------------------------------------------------------------------
# review_evidence
# ---------------------------------------------------------------------------

async def load_result_snapshot(
    db: AsyncIOMotorDatabase, analysis_id: str, sequence_id: str
) -> dict | None:
    """
    The analysis result the review is about, as stored by the worker, or None
    if the analysis or the sequence is not in analysis_results.
    """
    doc = await db["analysis_results"].find_one(
        {"analysis_id": analysis_id},
        {"analysis_id": 1, "results": {"$elemMatch": {"sequence_id": sequence_id}}},
    )
    results = (doc or {}).get("results") or []
    if not results:
        return None
    return {
        "analysis_id": analysis_id,
        "sequence_id": sequence_id,
        "captured_at": _now(),
        "result": {k: v for k, v in results[0].items() if k not in _SNAPSHOT_EXCLUDE},
    }


def evidence_docs(
    review: dict,
    submitted_by: str,
    *,
    text: str | None = None,
    attachments: list[str] | tuple[str, ...] = (),
    snapshot: dict | None = None,
) -> list[dict]:
    """
    One review_evidence document per piece of evidence: the notes ("text"),
    each attachment ("url" for http(s) links, otherwise "reference": there is
    no file upload for review evidence, so nothing is "file"), and the result
    snapshot ("result_snapshot", with the snapshot in `payload`).
    """
    now = _now()
    items: list[tuple[str, str | None, dict | None]] = []
    if snapshot is not None:
        items.append(("result_snapshot", None, snapshot))
    if text:
        items.append(("text", text, None))
    for a in attachments:
        items.append(("url" if _URL_RE.match(a) else "reference", a, None))
    return [
        {
            "evidence_id": f"evd_{uuid.uuid4().hex[:16]}",
            "review_id": review["review_id"],
            "analysis_id": review["analysis_id"],
            "sequence_id": review["sequence_id"],
            "submitted_by": submitted_by,
            "evidence_type": etype,
            "content": content,
            "storage_key": None,
            "payload": payload,
            "created_at": now,
            "supabase_mirrored": False,
        }
        for etype, content, payload in items
    ]


async def record_evidence(db: AsyncIOMotorDatabase, review: dict, docs: list[dict]) -> str:
    """
    Write review_evidence documents and mirror them. The review's
    expert_reviews row is upserted even when `docs` is empty, so a submitted
    review always has its row. Returns the mirror outcome.
    """
    async def write() -> None:
        review_uuid = await _expert_review_uuid(review)
        if docs:
            await SupabaseClient.insert_review_evidence([
                {
                    "review_id": review_uuid,
                    "submitted_by": _profile_id(d["submitted_by"]),
                    "evidence_type": d["evidence_type"],
                    "content": d["content"],
                    "storage_key": d["storage_key"],
                    "payload": _jsonable(d["payload"]),
                    "created_at": _iso(d["created_at"]),
                }
                for d in docs
            ])

    if docs:
        await db["review_evidence"].insert_many(docs)
    status = await _mirror(f"review_evidence for {review['review_id']}", write)
    if docs and status == "written":
        await db["review_evidence"].update_many(
            {"evidence_id": {"$in": [d["evidence_id"] for d in docs]}},
            {"$set": {"supabase_mirrored": True}},
        )
        for d in docs:
            d["supabase_mirrored"] = True
    return status


async def record_submission(
    db: AsyncIOMotorDatabase, review: dict, submitted_by: str, notes: str | None
) -> str:
    """Evidence for a newly submitted review: the result snapshot and its notes."""
    snapshot = await load_result_snapshot(db, review["analysis_id"], review["sequence_id"])
    return await record_evidence(db, review, evidence_docs(review, submitted_by, text=notes, snapshot=snapshot))


async def ensure_snapshot(db: AsyncIOMotorDatabase, review: dict, captured_by: str) -> str:
    """
    Snapshot evidence for a review that has none yet: auto-queued reviews are
    inserted by the worker straight into MongoDB, so the first API-side event
    for them is the curator's decision. Returns "exists", "unavailable"
    (analysis/sequence not found) or the mirror outcome.
    """
    if await db["review_evidence"].find_one(
        {"review_id": review["review_id"], "evidence_type": "result_snapshot"}
    ):
        return "exists"
    snapshot = await load_result_snapshot(db, review["analysis_id"], review["sequence_id"])
    if snapshot is None:
        return "unavailable"
    return await record_evidence(db, review, evidence_docs(review, captured_by, snapshot=snapshot))


def _jsonable(value: Any) -> Any:
    """datetimes to ISO strings, recursively, for a jsonb column."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return _iso(value)


# ---------------------------------------------------------------------------
# curation_decisions
# ---------------------------------------------------------------------------

async def record_decision(
    db: AsyncIOMotorDatabase,
    review: dict,
    *,
    decision: str,
    curator_id: str,
    curator_role: str,
    notes: str | None,
    previous_state: str | None,
    decided_at: datetime,
) -> str:
    """
    One curation_decisions document per curator decision. `review` is the
    review after the decision, so the expert_reviews upsert also mirrors its
    new state. Returns the mirror outcome.
    """
    doc = {
        "decision_id": f"cdec_{uuid.uuid4().hex[:16]}",
        "review_id": review["review_id"],
        "analysis_id": review["analysis_id"],
        "sequence_id": review["sequence_id"],
        "curator_id": curator_id,
        "curator_role": str(curator_role),
        "decision": str(decision),
        "notes": notes,
        "previous_state": str(previous_state) if previous_state else None,
        "new_state": str(review.get("state")),
        "decided_at": decided_at,
        "supabase_mirrored": False,
    }

    async def write() -> None:
        review_uuid = await _expert_review_uuid(review)
        await SupabaseClient.insert_curation_decision({
            "review_id": review_uuid,
            "curator_id": curator_id,
            "decision": doc["decision"],
            "notes": notes,
            "decided_at": _iso(decided_at),
        })

    await db["curation_decisions"].insert_one(doc)
    status = await _mirror(f"curation decision on {review['review_id']}", write)
    if status == "written":
        await db["curation_decisions"].update_one(
            {"decision_id": doc["decision_id"]}, {"$set": {"supabase_mirrored": True}}
        )
    return status


# ---------------------------------------------------------------------------
# training_batch_items
# ---------------------------------------------------------------------------

async def _batch_sequences(db: AsyncIOMotorDatabase, reviews: list[dict]) -> dict[tuple[str, str], str]:
    """(analysis_id, sequence_id) -> raw sequence, from analysis_results."""
    wanted = {(r["analysis_id"], r["sequence_id"]) for r in reviews}
    found: dict[tuple[str, str], str] = {}
    cursor = db["analysis_results"].find(
        {"analysis_id": {"$in": sorted({a for a, _ in wanted})}},
        {"analysis_id": 1, "results.sequence_id": 1, "results.sequence": 1},
    )
    async for doc in cursor:
        for res in doc.get("results") or []:
            key = (doc.get("analysis_id"), res.get("sequence_id"))
            if key in wanted and res.get("sequence"):
                found.setdefault(key, res["sequence"])
    return found


async def record_batch_items(
    db: AsyncIOMotorDatabase,
    *,
    batch_id: str,
    month_year: str,
    route: str,
    created_by: str,
    reviews: list[dict],
) -> dict[str, Any]:
    """
    One training_batch_items document per review assembled into a batch, and
    the Supabase training_batches / curated_sequences / training_batch_items
    rows behind it.

    `split` stays null: scripts/training/train.py draws its train/val split
    when it trains, so assembly has none to record (migration 20261019000001
    makes the column nullable). A curated_sequences row needs the raw sequence
    and a taxon (both not null); a review without either is recorded in
    MongoDB with `supabase_skip_reason` instead of being given a made-up one.
    """
    now = _now()
    sequences = await _batch_sequences(db, reviews)
    items = [
        {
            "item_id": f"tbi_{uuid.uuid4().hex[:16]}",
            "batch_id": batch_id,
            "review_id": r["review_id"],
            "analysis_id": r["analysis_id"],
            "sequence_id": r["sequence_id"],
            "route": route,
            "taxon": r.get("proposed_taxon"),
            "split": None,
            "curated_by": r.get("decided_by"),
            "added_at": now,
            "supabase_mirrored": False,
            "supabase_skip_reason": None,
        }
        for r in reviews
    ]
    by_review = {r["review_id"]: r for r in reviews}
    # Why a row cannot be mirrored does not depend on Supabase, so it is
    # decided before the MongoDB insert and recorded even when Supabase is
    # not configured.
    for item in items:
        if not sequences.get((item["analysis_id"], item["sequence_id"])):
            item["supabase_skip_reason"] = "sequence not found in analysis_results"
        elif not item["taxon"]:
            item["supabase_skip_reason"] = "review has no proposed_taxon"
        elif not _profile_id(item["curated_by"]):
            item["supabase_skip_reason"] = "review has no deciding curator"
    if items:
        await db["training_batch_items"].insert_many(items)

    async def write() -> None:
        batch_row = await SupabaseClient.get_or_create_training_batch(batch_id, month_year, route, created_by)
        batch_uuid = batch_row.get("id")
        if not batch_uuid:
            raise LookupError(f"training_batches row for {batch_id} returned no id")
        mirrored = 0
        for item in items:
            if item["supabase_skip_reason"]:
                continue
            sequence = sequences[(item["analysis_id"], item["sequence_id"])]
            curated_by = _profile_id(item["curated_by"])
            review_type = str(by_review[item["review_id"]].get("review_type") or "")
            cs = await SupabaseClient.insert_curated_sequence({
                "sequence_id": item["sequence_id"],
                "sequence": sequence,
                "taxon": item["taxon"],
                "route": route,
                "source": "expert_correction" if review_type.startswith("manual") else "manual_curation",
                "curated_by": curated_by,
                "training_batch_id": batch_uuid,
            })
            await SupabaseClient.insert_training_batch_item({
                "batch_id": batch_uuid,
                "curated_sequence_id": cs["id"],
                "split": None,
            })
            item["supabase_mirrored"] = True
            mirrored += 1
        await SupabaseClient.set_training_batch_sequence_count(batch_id, mirrored)

    status = await _mirror(f"training batch {batch_id}", write)
    # A failure part-way leaves the items written before it mirrored, so the
    # flags follow each item, not the overall status.
    mirrored_ids = [i["item_id"] for i in items if i["supabase_mirrored"]]
    if mirrored_ids:
        await db["training_batch_items"].update_many(
            {"item_id": {"$in": mirrored_ids}}, {"$set": {"supabase_mirrored": True}}
        )
    return {
        "supabase_mirror": status,
        "items": len(items),
        "items_mirrored": sum(1 for i in items if i["supabase_mirrored"]),
        "items_skipped": sum(1 for i in items if i["supabase_skip_reason"]),
    }
