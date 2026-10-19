from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Create all MongoDB collection indexes.
    Called once at startup. Safe to re-run — MongoDB skips existing indexes.
    """
    await _uploads_indexes(db)
    await _jobs_indexes(db)
    await _analysis_indexes(db)
    await _sequence_batches_indexes(db)
    await _reviews_indexes(db)
    await _abyss_indexes(db)
    await _audit_indexes(db)
    await _field_log_indexes(db)
    await _environment_indexes(db)


async def _uploads_indexes(db: AsyncIOMotorDatabase) -> None:
    await db["uploads"].create_indexes([
        IndexModel([("upload_id", ASCENDING)], unique=True, name="upload_id_unique"),
        IndexModel([("user_id", ASCENDING)], name="uploads_user_id"),
        IndexModel([("created_at", DESCENDING)], name="uploads_created_at"),
        IndexModel([("status", ASCENDING)], name="uploads_status"),
    ])


async def _jobs_indexes(db: AsyncIOMotorDatabase) -> None:
    await db["analysis_jobs"].create_indexes([
        IndexModel([("job_id", ASCENDING)], unique=True, name="job_id_unique"),
        IndexModel([("upload_id", ASCENDING)], name="jobs_upload_id"),
        IndexModel([("user_id", ASCENDING)], name="jobs_user_id"),
        IndexModel([("state", ASCENDING)], name="jobs_state"),
        IndexModel([("queued_at", DESCENDING)], name="jobs_queued_at"),
        # Worker polling: find queued jobs in order
        IndexModel(
            [("state", ASCENDING), ("queued_at", ASCENDING)],
            name="jobs_worker_poll",
        ),
    ])


async def _analysis_indexes(db: AsyncIOMotorDatabase) -> None:
    await db["analysis_results"].create_indexes([
        IndexModel([("analysis_id", ASCENDING)], unique=True, name="analysis_id_unique"),
        IndexModel([("job_id", ASCENDING)], unique=True, name="analysis_job_id_unique"),
        IndexModel([("upload_id", ASCENDING)], name="analysis_upload_id"),
        IndexModel([("user_id", ASCENDING)], name="analysis_user_id"),
        IndexModel([("created_at", DESCENDING)], name="analysis_created_at"),
        # Report querying
        IndexModel(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="analysis_user_recent",
        ),
    ])
    await db["raw_model_outputs"].create_indexes([
        IndexModel([("analysis_id", ASCENDING)], name="raw_output_analysis_id"),
        IndexModel([("job_id", ASCENDING)], name="raw_output_job_id"),
    ])
    await db["reports"].create_indexes([
        IndexModel([("analysis_id", ASCENDING)], unique=True, name="report_analysis_id_unique"),
        IndexModel([("user_id", ASCENDING)], name="report_user_id"),
    ])


async def _sequence_batches_indexes(db: AsyncIOMotorDatabase) -> None:
    await db["sequence_batches"].create_indexes([
        IndexModel([("batch_id", ASCENDING)], unique=True, name="batch_id_unique"),
        IndexModel([("job_id", ASCENDING)], name="batch_job_id"),
        IndexModel([("sha256", ASCENDING)], name="batch_sha256"),
        # Deduplication: sha256 + job scope
        IndexModel(
            [("job_id", ASCENDING), ("sha256", ASCENDING)],
            name="batch_dedup",
        ),
    ])


async def _reviews_indexes(db: AsyncIOMotorDatabase) -> None:
    await db["reviews"].create_indexes([
        IndexModel([("review_id", ASCENDING)], unique=True, name="review_id_unique"),
        IndexModel([("analysis_id", ASCENDING)], name="reviews_analysis_id"),
        IndexModel([("sequence_id", ASCENDING)], name="reviews_sequence_id"),
        IndexModel([("submitted_by", ASCENDING)], name="reviews_submitted_by"),
        IndexModel([("state", ASCENDING)], name="reviews_state"),
        IndexModel([("created_at", DESCENDING)], name="reviews_created_at"),
        # Curator queue: pending states ordered by submission time
        IndexModel(
            [("state", ASCENDING), ("created_at", ASCENDING)],
            name="reviews_queue_poll",
        ),
    ])
    # B9 review records (app/reviews/records.py); supabase_mirrored finds
    # documents a Supabase backfill still has to write.
    await db["review_evidence"].create_indexes([
        IndexModel([("evidence_id", ASCENDING)], unique=True, name="evidence_id_unique"),
        IndexModel([("review_id", ASCENDING), ("evidence_type", ASCENDING)], name="evidence_review_type"),
        IndexModel([("supabase_mirrored", ASCENDING)], name="evidence_mirrored"),
    ])
    await db["curation_decisions"].create_indexes([
        IndexModel([("decision_id", ASCENDING)], unique=True, name="decision_id_unique"),
        IndexModel([("review_id", ASCENDING), ("decided_at", ASCENDING)], name="decisions_review_decided"),
        IndexModel([("curator_id", ASCENDING)], name="decisions_curator_id"),
        IndexModel([("supabase_mirrored", ASCENDING)], name="decisions_mirrored"),
    ])
    await db["training_batch_items"].create_indexes([
        IndexModel([("item_id", ASCENDING)], unique=True, name="batch_item_id_unique"),
        IndexModel([("batch_id", ASCENDING)], name="batch_items_batch_id"),
        IndexModel([("review_id", ASCENDING)], name="batch_items_review_id"),
        IndexModel([("supabase_mirrored", ASCENDING)], name="batch_items_mirrored"),
    ])


async def _field_log_indexes(db: AsyncIOMotorDatabase) -> None:
    await db["field_log_entries"].create_indexes([
        IndexModel([("entry_id", ASCENDING)], unique=True, name="field_entry_id_unique"),
        IndexModel([("analysis_id", ASCENDING), ("created_at", ASCENDING)], name="field_log_analysis_created"),
        IndexModel([("kind", ASCENDING)], name="field_log_kind"),
    ])
    await db["field_log_attachments"].create_indexes([
        IndexModel([("attachment_id", ASCENDING)], unique=True, name="field_attachment_id_unique"),
        IndexModel([("analysis_id", ASCENDING), ("created_at", ASCENDING)], name="field_attachment_analysis_created"),
    ])


async def _environment_indexes(db: AsyncIOMotorDatabase) -> None:
    # Q5 environmental context (app/environment/service.py): one doc per
    # upload, plus the coarse shared cache keyed by rounded lat/lon/date/depth.
    await db["environment_contexts"].create_indexes([
        IndexModel([("upload_id", ASCENDING)], unique=True, name="env_context_upload_id_unique"),
    ])
    await db["environment_cache"].create_indexes([
        IndexModel([("cache_key", ASCENDING)], unique=True, name="env_cache_key_unique"),
        # Recent dates expire after 24 h; old dates have expires_at=None and
        # are never removed (TTL indexes skip null).
        IndexModel([("expires_at", ASCENDING)], name="env_cache_expires_ttl", expireAfterSeconds=0),
    ])


async def _abyss_indexes(db: AsyncIOMotorDatabase) -> None:
    await db["abyss_expeditions"].create_indexes([
        IndexModel([("expedition_id", ASCENDING)], unique=True, name="expedition_id_unique"),
        IndexModel([("created_by", ASCENDING)], name="expedition_created_by"),
        IndexModel([("status", ASCENDING)], name="expedition_status"),
    ])
    await db["abyss_expedition_logs"].create_indexes([
        IndexModel([("expedition_id", ASCENDING)], name="abyss_log_expedition_id"),
        IndexModel([("synced_at", DESCENDING)], name="abyss_log_synced_at"),
    ])


async def _audit_indexes(db: AsyncIOMotorDatabase) -> None:
    await db["audit_logs"].create_indexes([
        IndexModel([("timestamp", DESCENDING)], name="audit_timestamp"),
        IndexModel([("actor_id", ASCENDING)], name="audit_actor_id"),
        IndexModel([("action", ASCENDING)], name="audit_action"),
        IndexModel([("review_id", ASCENDING)], name="audit_review_id", sparse=True),
    ])
