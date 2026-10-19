"""
Custody events the API records (t-1027-2).

The API appends events at the points it controls:

  upload_created      POST /uploads, after the upload doc is stored
  analysis_completed  derived here from the analysis_results document
  review_submitted    POST /reviews
  review_triaged      POST /reviews/{id}/triage
  review_evidence_added POST /reviews/{id}/evidence
  review_decision     POST /reviews/{id}/decision
  report_exported     GET /reports/{id}/export/{json,csv,fair}

analysis_completed is derived, not reported by the worker: the worker is
being rewritten by another task and writes no custody events. The worker
inserts the analysis_results document exactly once, at completion
(services/worker/app/job_runner.py), so the document's existence is the
completion signal. The first time custody or an export sees an analysis,
ensure_analysis_events() appends analysis_completed with the sha256 of the
canonical serialization of its `results` list, keyed
"analysis_completed:<analysis_id>" so it is appended at most once. Its
recorded_at is therefore when the API first observed the analysis, and the
payload carries the worker's own created_at alongside it. The same call
backfills a derived upload_created event for uploads stored before custody
logging existed (or whose append failed), marked derived=true.

Events never carry personal names or emails: only user_id and role. Sample
metadata is recorded as a sha256 plus the list of provided field names, so
the immutable chain holds no collector name that could not later be erased.
Review free text (sequence_id, correction_type, proposed_taxon, evidence
text) is likewise recorded only as sha256: the clear text stays in the
reviews collection, reachable through review_id, where it can be erased.
Review events are appended only for an actor who may read the analysis
(its owner, or curator / admin / company_owner, the report access rule);
anyone else's review writes nothing to the owner's chain.

Failure policy: upload and review events are best-effort (the caller logs
and continues) because the upload or review is already committed when the
event is appended, and failing the request would invite a duplicate retry;
a missing upload_created is backfilled as derived. Export events are
required: nothing has left the system yet, so an export that cannot be
recorded is refused (the reports router returns 503).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from ..models.upload import OPTIONAL_METADATA_FIELDS
from ..models.user import UserRole
from .chain import (
    CUSTODY_COLLECTION,
    append_event,
    canonical_json,
    chain_id_for_analysis,
    chain_id_for_upload,
    results_sha256,
    sha256_hex,
)

logger = logging.getLogger(__name__)

# Who may read an analysis (reports/router.py _fetch_analysis_and_reviews): owner or these roles.
_ANALYSIS_READER_ROLES = frozenset(str(r) for r in (UserRole.curator, UserRole.admin, UserRole.company_owner))

SYSTEM_ACTOR_DERIVED = {"type": "system", "id": "api-derived"}
SYSTEM_ACTOR_BACKFILL = {"type": "system", "id": "api-custody-backfill"}

ANALYSIS_COMPLETED_DERIVATION = (
    "Derived by the API from the analysis_results document the first time custody or an "
    "export read this analysis; the worker writes no custody events. results_sha256 is "
    "sha256 of the canonical JSON of the stored results list."
)


def user_actor(user: Any) -> dict[str, Any]:
    """{type, user_id, role} for an authenticated UserProfile. No email or name."""
    return {"type": "user", "user_id": user.user_id, "role": str(user.role)}


def _as_stored(value: Any) -> Any:
    """
    A datetime as Mongo will return it: naive UTC, truncated to milliseconds
    (BSON dates carry no timezone and no microseconds). Without this the hash
    taken at upload time (from the in-memory doc) would never match the hash
    of the same doc read back later.
    """
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.replace(microsecond=(value.microsecond // 1000) * 1000)
    return value


def metadata_sha256(upload: dict[str, Any]) -> str:
    """sha256 of the canonical JSON of the upload's optional metadata fields, as stored."""
    return sha256_hex(canonical_json({f: _as_stored(upload.get(f)) for f in OPTIONAL_METADATA_FIELDS}))


def _provided_fields(upload: dict[str, Any]) -> list[str]:
    out = []
    for f in OPTIONAL_METADATA_FIELDS:
        v = upload.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        out.append(f)
    return out


async def record_upload_created(
    db: Any,
    upload: dict[str, Any],
    *,
    actor: dict[str, Any],
    derived: bool = False,
) -> tuple[dict[str, Any], bool]:
    upload_id = upload["upload_id"]
    payload: dict[str, Any] = {
        "upload_id": upload_id,
        "original_filename": upload.get("original_filename"),
        "file_size_bytes": upload.get("file_size_bytes"),
        "checksum_sha256": upload.get("checksum_sha256"),
        "storage_uri": upload.get("storage_uri"),
        "uploaded_at": upload.get("created_at"),
        "uploaded_by": upload.get("user_id"),
        "metadata_sha256": metadata_sha256(upload),
        "metadata_fields_provided": _provided_fields(upload),
        "derived": derived,
    }
    if derived:
        payload["derived_note"] = (
            "Backfilled from the upload document: no upload_created event was recorded when "
            "the file was uploaded (upload predates custody logging, or that append failed)."
        )
    return await append_event(
        db,
        chain_id_for_upload(upload_id),
        "upload_created",
        actor=actor,
        subject={"upload_id": upload_id},
        payload=payload,
        event_key=f"upload_created:{upload_id}",
    )


async def ensure_analysis_events(
    db: Any,
    analysis_doc: dict[str, Any],
    upload: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """
    Idempotently make sure the analysis's chain has its upload_created
    (backfilled if missing) and analysis_completed events. Returns the
    analysis_completed event (existing or new).
    """
    if upload is not None and upload.get("upload_id"):
        await record_upload_created(db, upload, actor=SYSTEM_ACTOR_BACKFILL, derived=True)

    analysis_id = analysis_doc.get("analysis_id")
    results = analysis_doc.get("results", [])
    event, _ = await append_event(
        db,
        chain_id_for_analysis(analysis_doc),
        "analysis_completed",
        actor=SYSTEM_ACTOR_DERIVED,
        subject={"upload_id": analysis_doc.get("upload_id"), "analysis_id": analysis_id},
        payload={
            "analysis_id": analysis_id,
            "job_id": analysis_doc.get("job_id"),
            "upload_id": analysis_doc.get("upload_id"),
            "analysis_created_at": analysis_doc.get("created_at"),
            "mode": analysis_doc.get("mode"),
            "model_version_set": analysis_doc.get("model_version_set"),
            "result_count": len(results),
            "results_sha256": results_sha256(results),
            "derivation": ANALYSIS_COMPLETED_DERIVATION,
        },
        event_key=f"analysis_completed:{analysis_id}",
    )
    return event


async def record_export(
    db: Any,
    analysis_doc: dict[str, Any],
    upload: Optional[dict[str, Any]],
    *,
    actor: dict[str, Any],
    export_format: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Append report_exported (after ensuring the analysis events). Raises on failure."""
    await ensure_analysis_events(db, analysis_doc, upload)
    analysis_id = analysis_doc.get("analysis_id")
    event, _ = await append_event(
        db,
        chain_id_for_analysis(analysis_doc),
        "report_exported",
        actor=actor,
        subject={"upload_id": analysis_doc.get("upload_id"), "analysis_id": analysis_id},
        payload={"analysis_id": analysis_id, "format": export_format, **details},
    )
    return event


async def record_review_event(
    db: Any,
    event_type: str,
    *,
    analysis_id: Optional[str],
    review_id: str,
    actor: dict[str, Any],
    details: dict[str, Any],
    text_fields: Optional[dict[str, Optional[str]]] = None,
) -> Optional[dict[str, Any]]:
    """
    Best-effort: append a review action to the reviewed analysis's chain.
    Logs and returns None when the analysis is unknown, the actor may not
    read it, or the append fails; the review itself is already committed
    (see the module docstring). text_fields are user free text: each is
    recorded as <name>_sha256 (None when absent), never in clear.
    """
    try:
        if not analysis_id:
            return None
        analysis_doc = await db["analysis_results"].find_one({"analysis_id": analysis_id})
        if not analysis_doc:
            logger.info("custody: review %s names unknown analysis %s; no event", review_id, analysis_id)
            return None
        if actor.get("user_id") != analysis_doc.get("user_id") and actor.get("role") not in _ANALYSIS_READER_ROLES:
            logger.info("custody: review %s by %s, who cannot read analysis %s; no event",
                        review_id, actor.get("user_id"), analysis_id)
            return None
        details = {**details, **{
            f"{name}_sha256": None if value is None else sha256_hex(value)
            for name, value in (text_fields or {}).items()
        }}
        upload = await db["uploads"].find_one({"upload_id": analysis_doc.get("upload_id", "")})
        await ensure_analysis_events(db, analysis_doc, upload)
        event, _ = await append_event(
            db,
            chain_id_for_analysis(analysis_doc),
            event_type,
            actor=actor,
            subject={
                "upload_id": analysis_doc.get("upload_id"),
                "analysis_id": analysis_id,
                "review_id": review_id,
            },
            payload={"review_id": review_id, **details},
        )
        return event
    except Exception:
        logger.warning(
            "custody: %s for review %s (analysis %s) not recorded", event_type, review_id, analysis_id,
            exc_info=True,
        )
        return None


async def record_upload_created_best_effort(db: Any, upload: dict[str, Any], user: Any) -> None:
    """POST /uploads hook: never fails the upload; a miss is backfilled later as derived."""
    try:
        await record_upload_created(db, upload, actor=user_actor(user))
    except Exception:
        logger.warning(
            "custody: upload_created for %s not recorded; it will be backfilled as derived",
            upload.get("upload_id"), exc_info=True,
        )


__all__ = [
    "CUSTODY_COLLECTION",
    "ensure_analysis_events",
    "metadata_sha256",
    "record_export",
    "record_review_event",
    "record_upload_created",
    "record_upload_created_best_effort",
    "user_actor",
]
