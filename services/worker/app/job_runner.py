"""
Job runner — executes a single analysis job end-to-end.

Pipeline stages (each updates job.state in MongoDB):
  queued -> parsing -> qc -> routing -> inferencing
  -> novelty_scoring -> reporting -> completed | failed

Phase 5: parsing calls the real fastx_parser (Rust binary or Python fallback).
Phase 6: routing calls the real model_router (heuristic marker + biophysical scorer).
Phases 7–8 stubs remain until those phases are implemented.
"""
import asyncio
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from .fastx_parser import parse_and_batch_auto
from .model_router import route_batch, RouterInput
from .inference import run_inference_batch
from .novelty import score_batch, contamination_score_batch


async def run_job(db: AsyncIOMotorDatabase, job_id: str) -> None:
    """
    Main entry point called by the dispatcher for each dequeued job.
    Fetches the full job doc, runs all pipeline stages, and writes results.
    """
    job = await db["analysis_jobs"].find_one({"job_id": job_id})
    if job is None:
        print(f"[worker] job {job_id} not found in MongoDB — skipping")
        return

    upload = await db["uploads"].find_one({"upload_id": job["upload_id"]})
    if upload is None:
        await _fail_job(db, job_id, "Upload document not found")
        return

    try:
        await _set_state(db, job_id, "parsing")
        sequences = await _stage_parse(upload)

        await _set_state(db, job_id, "qc")
        sequences = await _stage_qc(sequences)

        await _set_state(db, job_id, "routing")
        routed = await _stage_route(sequences)

        await _set_state(db, job_id, "inferencing")
        predictions = await _stage_infer(routed)

        await _set_state(db, job_id, "novelty_scoring")
        scored = await _stage_novelty(predictions)

        await _set_state(db, job_id, "reporting")
        analysis_id = await _stage_report(db, job, upload, scored)

        await _complete_job(db, job_id, analysis_id)
        print(f"[worker] job {job_id} completed -> {analysis_id}")

    except Exception as exc:
        await _fail_job(db, job_id, str(exc))
        print(f"[worker] job {job_id} FAILED: {exc}")
        raise


# ---------------------------------------------------------------------------
# Pipeline stage stubs
# Phases 5-8 replace these with real implementations.
# ---------------------------------------------------------------------------

async def _stage_parse(upload: dict) -> list[dict]:
    """
    Phase 5: parse the uploaded FASTA/FASTQ file into sequence records.

    Uses the Rust `synthveda-parse` binary when available (fast path), or falls
    back to the pure-Python parser.  The file path comes from the upload doc's
    `file_path` field (set by the API when it saves the upload to disk).

    Returns a flat list of sequence dicts ready for the QC stage.
    """
    file_path: str | None = upload.get("file_path")
    if not file_path:
        # No file path — return stub so the pipeline can continue in tests.
        await asyncio.sleep(0)
        return [
            {
                "sequence_id": "seq_stub_001",
                "sequence": "ATCGATCGATCG",
                "length": 12,
                "gc_ratio": 0.5,
                "n_ratio": 0.0,
                "has_invalid_chars": False,
                "sha256": "stub",
                "source_file": upload.get("original_filename", "unknown"),
            }
        ]

    # Run the blocking parser in a thread pool so the event loop is not blocked.
    loop = asyncio.get_event_loop()
    batches, used_rust = await loop.run_in_executor(
        None,
        lambda: parse_and_batch_auto(
            file_path,
            batch_size=1000,
            min_length=10,
        ),
    )
    backend = "Rust" if used_rust else "Python"
    total = sum(len(b) for b in batches)
    print(f"[worker] parsed {total} sequences via {backend} parser ({upload.get('original_filename', '?')})")

    # Flatten batches → list of dicts for downstream stages.
    return [record.__dict__ for batch in batches for record in batch]


async def _stage_qc(sequences: list[dict]) -> list[dict]:
    """
    Phase 5: filter low-quality sequences.

    QC is already applied in parse_and_batch_auto (min_length filter).  This
    stage applies the remaining filters that depend on the full sequence context
    and can be tuned independently of the parser defaults.
    """
    await asyncio.sleep(0)
    return [
        s for s in sequences
        if s.get("n_ratio", 1.0) < 0.5
        and s.get("length", 0) >= 10
        and not s.get("has_invalid_chars", False)
    ]


async def _stage_route(sequences: list[dict]) -> list[dict]:
    """
    Phase 6: assign each sequence a taxonomic route using the heuristic router.

    The router uses marker gene detection + biophysical scoring (GC ratio, CpG
    O/E, length, habitat metadata) to assign routes with confidence scores.
    Phase 7 replaces the biophysical scorer with DNA foundation model embeddings.
    """
    if not sequences:
        return sequences

    inputs = [
        RouterInput(
            sequence_id=seq["sequence_id"],
            sequence=seq["sequence"],
            length=seq["length"],
            gc_ratio=seq.get("gc_ratio", 0.5),
            n_ratio=seq.get("n_ratio", 0.0),
            sha256=seq.get("sha256", ""),
            source_file=seq.get("source_file", ""),
            habitat=seq.get("habitat"),
            depth_meters=seq.get("depth_meters"),
        )
        for seq in sequences
    ]

    # Run the synchronous router in a thread pool to avoid blocking the event loop.
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, route_batch, inputs)

    route_dist: dict[str, int] = {}
    for seq, result in zip(sequences, results):
        seq["route"] = str(result.route)
        seq["route_confidence"] = result.route_confidence
        seq["confidence_tier"] = str(result.confidence_tier)
        seq["fallback_routes"] = result.fallback_routes
        seq["reason_codes"] = result.reason_codes
        route_dist[str(result.route)] = route_dist.get(str(result.route), 0) + 1

    low_q = route_dist.get("low_quality", 0)
    routed = len(sequences) - low_q
    print(f"[worker] routing complete: {routed} sequences routed, {low_q} low-quality")
    return sequences


async def _stage_infer(routed: list[dict]) -> list[dict]:
    """
    Phase 7: run DNA foundation model inference for each sequence.

    Uses the model registry to select the best available model per route.
    Falls back to stub predictions (unknown_needs_online_confirmation) when
    torch is not installed or no trained weights exist yet.

    The [CLS] embedding returned by each PredictionResult is stored on the
    sequence dict for use by Phase 8 novelty scoring.
    """
    if not routed:
        return routed

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, run_inference_batch, routed)

    mode_counts: dict[str, int] = {}
    for seq, result in zip(routed, results):
        seq["result_class"] = result.result_class
        seq["predicted_taxon"] = result.predicted_taxon
        seq["confidence"] = result.confidence
        seq["model_version_used"] = result.model_version_used
        seq["inference_mode"] = str(result.inference_mode)
        seq["label_scores"] = result.label_scores
        seq["embedding"] = result.embedding   # used by Phase 8
        mode_counts[str(result.inference_mode)] = mode_counts.get(str(result.inference_mode), 0) + 1

    model_seqs = mode_counts.get("model", 0)
    stub_seqs = mode_counts.get("stub", 0)
    lq_seqs = mode_counts.get("low_quality", 0)
    print(f"[worker] inference complete: {model_seqs} model, {stub_seqs} stub, {lq_seqs} low_quality")
    return routed


async def _stage_novelty(predictions: list[dict]) -> list[dict]:
    """
    Phase 8: compute novelty and contamination scores from multi-signal evidence.

    Contamination is scored first so the novelty scorer can use the result as
    a gate — a sequence flagged as contamination cannot score high on novelty.

    Scoring runs in a thread pool to avoid blocking the event loop.
    """
    if not predictions:
        return predictions

    loop = asyncio.get_event_loop()

    # Step 1: contamination scoring (attaches contamination_score to each dict
    # so the novelty scorer can read it in step 2).
    cont_results = await loop.run_in_executor(
        None, contamination_score_batch, predictions
    )
    for seq, cr in zip(predictions, cont_results):
        seq["contamination_score"] = cr.contamination_score
        seq["contamination_flagged"] = cr.is_flagged
        seq["contamination_type"] = cr.contamination_type
        seq["contamination_reason_codes"] = cr.reason_codes

    # Step 2: novelty scoring.
    novelty_results = await loop.run_in_executor(
        None, score_batch, predictions
    )
    flagged_novelty = 0
    flagged_contam = 0
    for seq, nr, cr in zip(predictions, novelty_results, cont_results):
        seq["novelty_score"] = nr.novelty_score
        seq["novelty_level"] = str(nr.novelty_level)
        seq["novelty_signals"] = nr.signals
        seq["novelty_reason_codes"] = nr.reason_codes
        seq["abyss_recommendation"] = str(nr.abyss_recommendation)
        seq["requires_cloud_confirmation"] = nr.requires_cloud_confirmation
        if nr.novelty_score >= 0.45:
            flagged_novelty += 1
        if cr.is_flagged:
            flagged_contam += 1

    print(
        f"[worker] novelty scoring: {flagged_novelty} possible_novelty, "
        f"{flagged_contam} contamination flags"
    )
    return predictions


async def _stage_report(
    db: AsyncIOMotorDatabase, job: dict, upload: dict, results: list[dict]
) -> str:
    """
    Phase 9/11: build the structured analysis result document, store it,
    and auto-queue reviews for any sequence flagged by novelty or contamination.
    """
    import uuid
    analysis_id = f"ana_{uuid.uuid4().hex[:16]}"

    total = len(results)
    route_dist: dict[str, int] = {}
    known = possible_novelty = contamination_flags = low_quality = 0
    for r in results:
        route_dist[r.get("route", "misc_unknown")] = route_dist.get(r.get("route", "misc_unknown"), 0) + 1
        rc = r.get("result_class", "")
        if rc == "known_species":
            known += 1
        elif rc == "possible_novelty" or r.get("novelty_score", 0.0) >= 0.45:
            possible_novelty += 1
        if r.get("contamination_flagged"):
            contamination_flags += 1
        if rc == "low_quality_unusable":
            low_quality += 1

    doc: dict[str, Any] = {
        "analysis_id": analysis_id,
        "job_id": job["job_id"],
        "upload_id": job["upload_id"],
        "user_id": job.get("user_id"),
        "mode": job.get("mode", "online_full"),
        "model_version_set": "stub_none",
        "summary": {
            "total_sequences": total,
            "known_species": known,
            "possible_novelty": possible_novelty,
            "contamination_flags": contamination_flags,
            "low_quality": low_quality,
            "route_distribution": route_dist,
        },
        "results": results,
        "created_at": datetime.now(timezone.utc),
    }
    await db["analysis_results"].insert_one(doc)

    # Auto-queue reviews for flagged sequences.
    # This runs directly against MongoDB (worker has no Supabase access).
    # The curation.build_auto_review helper is a pure function — import inline
    # to avoid a circular dep between the worker and API service packages.
    review_docs = _build_auto_reviews(analysis_id, job["job_id"], results)
    if review_docs:
        await db["reviews"].insert_many(review_docs)
        print(f"[worker] auto-queued {len(review_docs)} review(s) for {analysis_id}")

    return analysis_id


def _build_auto_reviews(analysis_id: str, job_id: str, results: list[dict]) -> list[dict]:
    """
    Build review documents for novelty/contamination-flagged sequences.
    Pure function — no I/O.  Avoids importing the API-side curation module.
    """
    import uuid
    from datetime import datetime, timezone

    reviews: list[dict] = []
    now = datetime.now(timezone.utc)

    for seq in results:
        novelty_score: float = seq.get("novelty_score", 0.0)
        contamination_flagged: bool = bool(seq.get("contamination_flagged"))
        contamination_score: float = seq.get("contamination_score", 0.0)
        seq_id: str = seq.get("sequence_id", "unknown")

        if novelty_score >= 0.45:
            reviews.append({
                "review_id": f"rev_{uuid.uuid4().hex[:16]}",
                "analysis_id": analysis_id,
                "sequence_id": seq_id,
                "submitted_by": "system",
                "state": "submitted",
                "review_type": "auto_novelty",
                "triage_priority": "urgent" if novelty_score >= 0.70 else "normal",
                "novelty_score": novelty_score,
                "novelty_level": seq.get("novelty_level"),
                "contamination_score": contamination_score,
                "abyss_recommendation": seq.get("abyss_recommendation"),
                "correction_type": "auto_novelty_flag",
                "is_novelty": True,
                "is_contamination": contamination_flagged,
                "evidence_notes": None,
                "evidence_attachments": [],
                "training_batch_id": None,
                "created_at": now,
            })

        if contamination_flagged:
            reviews.append({
                "review_id": f"rev_{uuid.uuid4().hex[:16]}",
                "analysis_id": analysis_id,
                "sequence_id": seq_id,
                "submitted_by": "system",
                "state": "submitted",
                "review_type": "auto_contamination",
                "triage_priority": "urgent",
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
                "training_batch_id": None,
                "created_at": now,
            })

    return reviews


# ---------------------------------------------------------------------------
# State management helpers
# ---------------------------------------------------------------------------

async def _set_state(db: AsyncIOMotorDatabase, job_id: str, state: str) -> None:
    update: dict[str, Any] = {"state": state}
    if state == "parsing":
        update["started_at"] = datetime.now(timezone.utc)
    await db["analysis_jobs"].update_one({"job_id": job_id}, {"$set": update})


async def _complete_job(db: AsyncIOMotorDatabase, job_id: str, analysis_id: str) -> None:
    await db["analysis_jobs"].update_one(
        {"job_id": job_id},
        {"$set": {
            "state": "completed",
            "analysis_id": analysis_id,
            "completed_at": datetime.now(timezone.utc),
        }},
    )


async def _fail_job(db: AsyncIOMotorDatabase, job_id: str, reason: str) -> None:
    await db["analysis_jobs"].update_one(
        {"job_id": job_id},
        {"$set": {
            "state": "failed",
            "error_message": reason,
            "completed_at": datetime.now(timezone.utc),
        }},
    )
