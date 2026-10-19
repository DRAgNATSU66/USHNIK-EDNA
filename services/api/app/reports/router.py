"""
Reports API — Phase 11.

Endpoints:
  GET /reports                              List current user's recent analyses
  GET /reports/{analysis_id}                Full structured report (JSON)
  GET /reports/{analysis_id}/summary        Summary section only
  GET /reports/{analysis_id}/novelty        Possible novelty table
  GET /reports/{analysis_id}/contamination  Contamination warnings table
  GET /reports/{analysis_id}/export/json    Downloadable JSON file
  GET /reports/{analysis_id}/export/csv     Downloadable CSV file (per-sequence)
  GET /reports/{analysis_id}/export/fair    FAIR ZIP: results, mapped metadata,
                                            provenance, custody, manifest (fair.py)
  GET /reports/{analysis_id}/custody        Hash-chained chain of custody + verification

Every export is recorded on the sample's custody chain (app/custody/) before
any bytes are returned; an export that cannot be recorded is refused (503).
"""
from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from datetime import datetime, timezone
from typing import Annotated, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse

from ..auth.deps import get_current_user
from ..config import NOVELTY_THRESHOLD, get_settings
from ..models.user import UserProfile, UserRole
from ..db import get_db
from ..custody import (
    chain_id_for_analysis,
    ensure_analysis_events,
    load_chain,
    metadata_sha256,
    record_export,
    results_sha256,
    user_actor,
    verify_chain,
)
from ..custody.files import check_stored_file
from . import fair
from .builder import build_report, build_report_csv
from .models import AnalysisReport, REPORT_DISCLAIMER
from ..uploads.context import build_metadata_context
from ..uploads.access import can_view_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

_CURATOR_ROLES = (UserRole.curator, UserRole.admin, UserRole.company_owner)


async def _fetch_analysis_and_reviews(
    analysis_id: str,
    current_user: UserProfile,
):
    """
    Shared fetch logic: load analysis doc + its reviews + its upload doc.
    Enforces access control: owner or curator/admin can view.
    Raises 404/403 as appropriate.

    Returns (doc, reviews, upload). `upload` is None if the upload record no
    longer exists; build_report then states that no metadata is available.
    """
    db = get_db()

    doc = await db["analysis_results"].find_one({"analysis_id": analysis_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    if doc.get("user_id") != current_user.user_id and current_user.role not in _CURATOR_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    upload = await db["uploads"].find_one({"upload_id": doc.get("upload_id", "")})
    if upload:
        upload.pop("_id", None)

    # Fetch all reviews for this analysis
    reviews: list[dict] = []
    async for rev in db["reviews"].find({"analysis_id": analysis_id}):
        rev.pop("_id", None)
        reviews.append(rev)

    doc.pop("_id", None)
    return doc, reviews, upload


async def _load_report(analysis_id: str, current_user: UserProfile) -> AnalysisReport:
    doc, reviews, upload = await _fetch_analysis_and_reviews(analysis_id, current_user)
    return build_report(doc, reviews, upload=upload)


def _report_summary(doc: dict, upload: dict | None) -> dict:
    """
    Pure summarization of one analysis_results doc (+ its upload doc) into
    the minimal shape list_reports returns. Kept separate from the Mongo
    I/O in list_reports so it's directly unit-testable -- the test DB mock
    fixture returns a fresh empty collection per access, so real
    sort/filter behavior can't be exercised through the endpoint itself.
    """
    results = doc.get("results", [])
    novelty_count = sum(1 for r in results if float(r.get("novelty_score", 0.0)) >= NOVELTY_THRESHOLD)
    return {
        "analysis_id": doc.get("analysis_id"),
        "source_file": upload.get("original_filename") if upload else None,
        "created_at": doc.get("created_at"),
        "total_sequences": len(results),
        "possible_novelty_count": novelty_count,
        # Q2: a partner report needs collection date + coordinates.
        "partner_report_available": build_metadata_context(upload).partner_report.available,
    }


@router.get("")
async def list_reports(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    limit: int = 20,
):
    """
    List the current user's own analyses, most recent first. Minimal
    summary fields only -- fetch /reports/{analysis_id} for the full report.
    Curators/admins do NOT get other users' analyses here; this endpoint is
    scoped to "my analyses" specifically (unlike the per-analysis GET routes,
    which do allow curator access to a known analysis_id).
    """
    db = get_db()
    cursor = (
        db["analysis_results"]
        .find({"user_id": current_user.user_id})
        .sort("created_at", -1)
        .limit(max(1, min(limit, 100)))
    )

    out = []
    async for doc in cursor:
        upload = await db["uploads"].find_one({"upload_id": doc.get("upload_id", "")})
        out.append(_report_summary(doc, upload))
    return out


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
    return await _load_report(analysis_id, current_user)


@router.get("/{analysis_id}/summary")
async def get_report_summary(
    analysis_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """Return the metadata + QC summary + biodiversity section only."""
    report = await _load_report(analysis_id, current_user)
    return {
        "analysis_id": analysis_id,
        "metadata": report.metadata.model_dump(),
        "qc_summary": report.qc_summary.model_dump(),
        "biodiversity": report.biodiversity.model_dump(),
        "review_status": report.review_status.model_dump(),
        "context": report.context.model_dump() if report.context else None,
        "disclaimer": REPORT_DISCLAIMER,
        "generated_at": report.generated_at,
    }


@router.get("/{analysis_id}/novelty")
async def get_novelty_table(
    analysis_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    min_score: float = NOVELTY_THRESHOLD,
):
    """
    Return the possible novelty table, optionally filtered by minimum score.
    Results are sorted highest novelty first.
    """
    report = await _load_report(analysis_id, current_user)
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
    report = await _load_report(analysis_id, current_user)
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
    doc, reviews, upload = await _fetch_analysis_and_reviews(analysis_id, current_user)
    report = build_report(doc, reviews, upload=upload)

    # Serialize with datetime support
    payload = report.model_dump()
    json_bytes = json.dumps(payload, indent=2, default=_json_default).encode("utf-8")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"synthveda_report_{analysis_id}_{timestamp}.json"
    await _record_export(doc, upload, current_user, "json", {
        "filename": filename, "sha256": hashlib.sha256(json_bytes).hexdigest(), "bytes": len(json_bytes),
    })

    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{analysis_id}/export/csv")
async def export_report_csv(
    analysis_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """
    Download the per-sequence results (known species + possible novelty +
    contamination warnings, merged one row per sequence) as a CSV file.
    """
    doc, reviews, upload = await _fetch_analysis_and_reviews(analysis_id, current_user)
    report = build_report(doc, reviews, upload=upload)
    csv_text = build_report_csv(report)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"synthveda_report_{analysis_id}_{timestamp}.csv"
    csv_bytes = csv_text.encode("utf-8")
    await _record_export(doc, upload, current_user, "csv", {
        "filename": filename, "sha256": hashlib.sha256(csv_bytes).hexdigest(), "bytes": len(csv_bytes),
    })

    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ---------------------------------------------------------------------------
# Chain of custody (app/custody/)
# ---------------------------------------------------------------------------

_CUSTODY_UNAVAILABLE = "Chain of custody could not be recorded; nothing was exported. Retry shortly."


async def _record_export(
    doc: dict, upload: Optional[dict], user: UserProfile, export_format: str, details: dict,
) -> dict:
    """Record an export on the custody chain, or refuse the export (503)."""
    try:
        return await record_export(
            get_db(), doc, upload, actor=user_actor(user), export_format=export_format, details=details,
        )
    except Exception as exc:
        logger.exception("custody: %s export of %s not recorded", export_format, doc.get("analysis_id"))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_CUSTODY_UNAVAILABLE) from exc


def _find_event(events: list[dict], event_key: str) -> Optional[dict]:
    return next((e for e in events if e.get("event_key") == event_key), None)


async def _custody_snapshot(doc: dict, upload: Optional[dict], verify_file: bool) -> dict[str, Any]:
    """
    Make sure the analysis's derived events exist (idempotent), then load the
    chain, verify every link, and compare the stored results / metadata /
    file against the hashes recorded on the chain.
    """
    db = get_db()
    try:
        await ensure_analysis_events(db, doc, upload)
    except Exception as exc:
        logger.exception("custody: derived events for %s not recorded", doc.get("analysis_id"))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chain of custody is temporarily unavailable. Retry shortly.",
        ) from exc

    chain_id = chain_id_for_analysis(doc)
    events = await load_chain(db, chain_id)
    verification = verify_chain(events, chain_id)
    verification["checked_at"] = datetime.now(timezone.utc).isoformat()

    analysis_id = doc.get("analysis_id")
    completed = _find_event(events, f"analysis_completed:{analysis_id}")
    recorded_results = (completed or {}).get("payload", {}).get("results_sha256")
    current_results = results_sha256(doc.get("results", []))
    results_integrity = {
        "status": "not_recorded" if not recorded_results else (
            "match" if recorded_results == current_results else "mismatch"),
        "recorded_sha256": recorded_results,
        "current_sha256": current_results,
        "recorded_at": (completed or {}).get("recorded_at"),
    }

    upload_event = _find_event(events, f"upload_created:{doc.get('upload_id')}") if doc.get("upload_id") else None
    metadata_integrity: dict[str, Any] = {"status": "not_recorded"}
    if upload is None:
        metadata_integrity = {"status": "upload_not_found"}
    elif upload_event:
        recorded_md = upload_event.get("payload", {}).get("metadata_sha256")
        current_md = metadata_sha256(upload)
        metadata_integrity = {
            # A change can be a legitimate later correction; it is reported, not judged.
            "status": "unchanged" if recorded_md == current_md else "changed_since_recorded",
            "recorded_sha256": recorded_md,
            "current_sha256": current_md,
            "baseline": "backfill" if upload_event.get("payload", {}).get("derived") else "upload",
        }

    file_integrity: dict[str, Any] = {"status": "not_checked"}
    if verify_file:
        if upload is None:
            file_integrity = {"status": "unavailable", "reason": "upload record not found"}
        else:
            file_integrity = await run_in_threadpool(check_stored_file, upload, get_settings())

    return {
        "analysis_id": analysis_id,
        "chain_id": chain_id,
        "upload": None if upload is None else {
            "upload_id": upload.get("upload_id"),
            "original_filename": upload.get("original_filename"),
            "uploaded_by": upload.get("user_id"),
            "uploaded_at": upload.get("created_at"),
            "checksum_sha256": upload.get("checksum_sha256"),
        },
        "events": events,
        "verification": verification,
        "results_integrity": results_integrity,
        "metadata_integrity": metadata_integrity,
        "file_integrity": file_integrity,
        "notes": [
            "analysis_completed is derived by the API from the stored analysis_results document "
            "the first time custody or an export reads the analysis; its recorded_at is that first "
            "read, and analysis_created_at in its payload is when the worker stored the results.",
            "Deleting the newest event(s) is not detectable from the chain alone; compare head_hash "
            "with the custody head recorded in any earlier export.",
        ],
    }


@router.get("/{analysis_id}/custody")
async def get_custody(
    analysis_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    verify_file: bool = True,
):
    """
    The sample's hash-chained custody log with a full verification: every
    hash recomputed, the first broken link (if any) reported, plus whether the
    stored results, sample metadata and uploaded file still match the hashes
    recorded on the chain. verify_file=false skips re-reading the file.
    """
    doc, _reviews, upload = await _fetch_analysis_and_reviews(analysis_id, current_user)
    return await _custody_snapshot(doc, upload, verify_file)


@router.get("/{analysis_id}/export/fair")
async def export_report_fair(
    analysis_id: str,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
    include_raw: bool = True,
):
    """
    Download a FAIR ZIP (contents in app/reports/fair.py). The uploaded file
    is included only when include_raw is true, the caller may read the upload
    itself (app/uploads/access.py) and its bytes re-hash to the checksum
    recorded at upload. Recorded on the custody chain before the
    response starts; refused (503) if it cannot be.
    """
    doc, _reviews, upload = await _fetch_analysis_and_reviews(analysis_id, current_user)
    settings = get_settings()
    snapshot = await _custody_snapshot(doc, upload, verify_file=False)
    results = doc.get("results", [])
    generated_at = datetime.now(timezone.utc).isoformat()

    # Spooled: small exports stay in memory, a 100 MB raw upload goes to disk.
    raw_tmp = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    zip_tmp = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    try:
        raw_info: dict[str, Any] = {"included": False}
        if not include_raw:
            raw_info["reason"] = "include_raw=false was requested"
        elif upload is None:
            raw_info["reason"] = "the upload record no longer exists"
        elif not can_view_upload(upload.get("user_id"), current_user):
            # Report access (owner or curator+) is wider than upload access
            # (owner, admin, company_owner): the raw bytes follow the upload's rule.
            raw_info["reason"] = (
                "the requester may read this report but not the uploaded file "
                "(upload access policy: owner, admin or company_owner)"
            )
        else:
            check = await run_in_threadpool(check_stored_file, upload, settings, raw_tmp)
            raw_info["check"] = check
            if check["status"] == "verified":
                raw_info.update(included=True, path=f"raw/{fair.safe_filename(upload.get('original_filename'))}")
            else:
                raw_info["reason"] = f"its integrity could not be confirmed ({check['status']}: {check.get('reason')})"

        from ..models.router import _resolve_data_root  # data-root convention shared with /models
        versions = [r["reference_db_version"] for r in fair.reference_versions_used(results) if r["reference_db_version"]]
        manifests = await run_in_threadpool(fair.load_reference_manifests, versions, _resolve_data_root())

        verification = snapshot["verification"]
        sample_metadata = fair.build_sample_metadata(doc, upload)
        provenance = fair.build_provenance(
            doc,
            reference_manifests=manifests,
            custody={
                "chain_id": snapshot["chain_id"],
                "events_at_export": verification["length"],
                "head_hash_at_export": verification["head_hash"],
                "verification_valid": verification["valid"],
                "first_break": verification["first_break"],
                "results_integrity": snapshot["results_integrity"]["status"],
            },
            generator={"service": settings.app_name, "version": settings.app_version},
        )
        custody_doc = {k: snapshot[k] for k in (
            "chain_id", "events", "verification", "results_integrity", "metadata_integrity", "notes")}
        custody_doc["snapshot_note"] = (
            "Chain as of export time. This export is recorded as the next event (report_exported) "
            "with the sha256 of this ZIP's manifest.json."
        )

        entries: list[tuple[str, Any]] = [
            ("results.csv", fair.build_results_csv(results).encode("utf-8")),
            ("sample_metadata.json", fair.json_bytes(sample_metadata)),
            ("provenance.json", fair.json_bytes(provenance)),
        ]
        traces = fair.build_decision_traces(results)
        if traces is not None:
            entries.append(("decision_traces.json", fair.json_bytes(traces)))
        entries.append(("custody.json", fair.json_bytes(custody_doc)))
        if raw_info["included"]:
            entries.append((raw_info["path"], raw_tmp))

        readme = fair.build_readme(
            analysis_id=analysis_id,
            generated_at=generated_at,
            files=["README.md"] + [p for p, _ in entries],
            sample_metadata=sample_metadata,
            provenance=provenance,
            raw_file=raw_info,
            custody=custody_doc,
        )
        entries.insert(0, ("README.md", readme.encode("utf-8")))

        manifest = await run_in_threadpool(
            fair.write_fair_zip, zip_tmp, f"synthveda_fair_{analysis_id}", entries,
            analysis_id=analysis_id, generated_at=generated_at,
        )
        zip_sha = await run_in_threadpool(_sha256_of, zip_tmp)
        zip_size = zip_tmp.tell()
    except BaseException:
        zip_tmp.close()
        raise
    finally:
        raw_tmp.close()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"synthveda_fair_{analysis_id}_{timestamp}.zip"
    try:
        await _record_export(doc, upload, current_user, "fair_zip", {
            "filename": filename,
            "sha256": zip_sha,
            "bytes": zip_size,
            "manifest_sha256": manifest["manifest_sha256"],
            "files": [f["path"] for f in manifest["files"]],
            "raw_file_included": raw_info["included"],
            "custody_head_hash_in_zip": verification["head_hash"],
        })
    except BaseException:
        zip_tmp.close()
        raise

    def _stream():
        try:
            zip_tmp.seek(0)
            for chunk in iter(lambda: zip_tmp.read(1024 * 1024), b""):
                yield chunk
        finally:
            zip_tmp.close()

    return StreamingResponse(
        _stream(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(zip_size),
            "X-Manifest-SHA256": manifest["manifest_sha256"],
        },
    )


def _sha256_of(fobj) -> str:
    """sha256 of a file object's whole content; leaves the position at the end."""
    h = hashlib.sha256()
    fobj.seek(0)
    for chunk in iter(lambda: fobj.read(1024 * 1024), b""):
        h.update(chunk)
    return h.hexdigest()
