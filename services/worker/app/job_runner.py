"""
Job runner — executes a single analysis job end-to-end.

Pipeline stages (each updates job.state in MongoDB):
  queued -> parsing -> qc -> routing -> inferencing
  -> novelty_scoring -> reporting -> completed | failed

Phase 5: parsing calls the real fastx_parser (Rust binary or Python fallback).
Phase 6: routing calls the real model_router (learned k-mer router, heuristic fallback).
Day 9: inference and novelty scoring are one orchestrator stage
(app/orchestrator/, decision Q7): per sequence a plan of candidate routes,
the heads and reference lookup of each, contamination and novelty on the
final route, one combined "decision" and a "decision_trace". job.state is
"inferencing" while evidence is collected and "novelty_scoring" while it is
scored and combined -- the same states the API already knows.
"""
import asyncio
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from .config import NOVELTY_THRESHOLD, get_worker_settings
from .fastx_parser import parse_and_batch_auto
from .model_router import route_batch, RouterInput
from .orchestrator import ORCHESTRATOR_VERSION, run_orchestrator
from .storage import local_copy_for_upload


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
        scored = await _stage_orchestrate(db, job_id, routed)

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
    back to the pure-Python parser. The bytes are read through app/storage.py
    from the upload doc's `storage_uri` (local:// under UPLOAD_STORAGE_DIR, or
    s3:// streamed to a temp file); pre-B7 docs that carry only an absolute
    `file_path` are read from that path.

    An upload with no file at all, a missing object, or bytes that fail the
    doc's checksum raise -- run_job() marks the job failed rather than
    analysing a made-up sequence (a stub here once produced a "completed"
    analysis of ATCGATCGATCG that looked like a real result).

    Returns a flat list of sequence dicts ready for the QC stage.
    """
    settings = get_worker_settings()

    def parse() -> tuple[list, bool]:
        with local_copy_for_upload(upload, settings) as path:
            return parse_and_batch_auto(str(path), batch_size=1000, min_length=10)

    # Fetching and parsing block, so they run in a thread pool.
    loop = asyncio.get_event_loop()
    batches, used_rust = await loop.run_in_executor(None, parse)
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
    Assign each sequence a taxonomic route.

    B19: the learned k-mer router runs first and returns calibrated
    probabilities for every route; the heuristic (marker + biophysical) router
    is the fallback, and each result records which one ran (router_method,
    router_version, router_fallback_reason).
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
    method_dist: dict[str, int] = {}
    fallback_reasons: dict[str, int] = {}
    for seq, result in zip(sequences, results):
        seq["route"] = str(result.route)
        seq["route_confidence"] = result.route_confidence
        seq["confidence_tier"] = str(result.confidence_tier)
        seq["fallback_routes"] = result.fallback_routes
        seq["reason_codes"] = result.reason_codes
        # B19: which router decided, its version, and all route probabilities.
        seq["router_method"] = result.router_method
        seq["router_version"] = result.router_version
        seq["route_probabilities"] = result.route_probabilities
        seq["route_probabilities_calibrated"] = result.probabilities_calibrated
        seq["router_fallback_reason"] = result.router_fallback_reason
        route_dist[str(result.route)] = route_dist.get(str(result.route), 0) + 1
        method_dist[result.router_method] = method_dist.get(result.router_method, 0) + 1
        if result.router_fallback_reason:
            fallback_reasons[result.router_fallback_reason] = fallback_reasons.get(result.router_fallback_reason, 0) + 1

    low_q = route_dist.get("low_quality", 0)
    routed = len(sequences) - low_q
    print(f"[worker] routing complete: {routed} sequences routed, {low_q} low-quality, methods {method_dist}")
    if method_dist.get("heuristic_fallback"):
        print(f"[worker] WARNING: learned router not used for {method_dist['heuristic_fallback']} "
              f"sequence(s), heuristic fallback; reasons {fallback_reasons}")
    return sequences


# Orchestrator phase -> job.state (both states predate the orchestrator).
_PHASE_STATES = {"evidence": "inferencing", "scoring": "novelty_scoring"}


async def _stage_orchestrate(db: AsyncIOMotorDatabase, job_id: str, routed: list[dict],
                             orchestrate: Any = None) -> list[dict]:
    """
    Day 9 (decision Q7): plan, collect evidence, combine (app/orchestrator/).

    Replaces the separate inference and novelty stages. The orchestrator is
    synchronous (model forward passes, BLAST subprocesses) and runs in the
    thread pool; it reports its phase back so job.state moves from
    "inferencing" to "novelty_scoring" when evidence collection ends.
    `orchestrate` is injectable for tests (default: run_orchestrator).
    """
    if not routed:
        return routed
    loop = asyncio.get_event_loop()
    orchestrate = orchestrate or run_orchestrator

    def on_phase(phase: str) -> None:
        state = _PHASE_STATES.get(phase)
        if state is None or state == "inferencing":   # already set before the stage
            return
        fut = asyncio.run_coroutine_threadsafe(_set_state(db, job_id, state), loop)
        try:
            fut.result(timeout=30)
        except Exception as exc:   # a state write must not fail the analysis
            print(f"[worker] could not set job state {state}: {exc!r}")

    stats = await loop.run_in_executor(None, lambda: orchestrate(routed, on_phase=on_phase))

    modes: dict[str, int] = {}
    wide = changed = flagged_novelty = flagged_contam = 0
    for seq in routed:
        modes[str(seq.get("inference_mode"))] = modes.get(str(seq.get("inference_mode")), 0) + 1
        trace = seq.get("decision_trace") or {}
        wide += len((trace.get("plan") or {}).get("routes") or []) > 1
        changed += seq.get("route") != seq.get("router_route")
        flagged_novelty += seq.get("novelty_score", 0.0) >= NOVELTY_THRESHOLD
        flagged_contam += bool(seq.get("contamination_flagged"))
    print(
        f"[worker] orchestrator {ORCHESTRATOR_VERSION}: {len(routed)} sequences, {wide} planned on >1 route, "
        f"{changed} final route != router route, head modes {modes}, {flagged_novelty} possible_novelty, "
        f"{flagged_contam} contamination flags ({(stats or {}).get('per_sequence_ms')} ms/sequence)"
    )
    return routed


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
        elif rc == "possible_novelty" or r.get("novelty_score", 0.0) >= NOVELTY_THRESHOLD:
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
        "orchestrator_version": ORCHESTRATOR_VERSION,
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


# Contamination that is the expected finding on its route: flagged and traced,
# but not auto-queued for review (owner decision 2026-10-19, docs/decisions.md).
# Human DNA on the human/domestic route is what that route is for.
EXPECTED_CONTAMINATION_BY_ROUTE: dict[str, frozenset[str]] = {
    "human_domestic_contamination": frozenset({"human_dna"}),
}


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

        if novelty_score >= NOVELTY_THRESHOLD:
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

        expected = seq.get("contamination_type") in EXPECTED_CONTAMINATION_BY_ROUTE.get(seq.get("route"), ())
        if contamination_flagged and not expected:
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
                "is_novelty": novelty_score >= NOVELTY_THRESHOLD,
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
