#!/usr/bin/env python3
"""
Local development seed script.

Seeds MongoDB with representative fixtures for:
  - uploads
  - analysis_jobs
  - analysis_results (mock output)
  - reviews

Run from repo root:
  python scripts/seed_dev.py

Requires MONGODB_URI set in .env or environment (defaults to localhost).
"""
import asyncio
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "api"))

from dotenv import load_dotenv
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGO_DB  = os.getenv("MONGODB_DB", "synthveda")

DEV_USER_ID     = "usr_dev_researcher_001"
DEV_ADMIN_ID    = "usr_dev_admin_001"
DEV_CURATOR_ID  = "usr_dev_curator_001"


async def seed() -> None:
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[MONGO_DB]

    print(f"Seeding MongoDB: {MONGO_URI}/{MONGO_DB}")

    # ------------------------------------------------------------------
    # Uploads
    # ------------------------------------------------------------------
    uploads = [
        {
            "upload_id": "upl_dev_001",
            "user_id": DEV_USER_ID,
            "original_filename": "coral_reef_sample_a.fasta",
            "file_size_bytes": 48210,
            "storage_key": None,
            "status": "stored",
            "depth_meters": 35.0,
            "location_label": "Great Barrier Reef – Station 7",
            "latitude": -18.2871,
            "longitude": 147.6992,
            "source_type": "seawater",
            "habitat": "coral_reef",
            "salinity_ppt": 35.2,
            "temperature_celsius": 26.1,
            "created_at": datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc),
        },
        {
            "upload_id": "upl_dev_002",
            "user_id": DEV_USER_ID,
            "original_filename": "deep_sea_vent_b.fasta",
            "file_size_bytes": 92340,
            "storage_key": None,
            "status": "stored",
            "depth_meters": 2100.0,
            "location_label": "Mid-Atlantic Ridge – Vent Field 3",
            "latitude": 37.2833,
            "longitude": -33.1167,
            "source_type": "sediment",
            "habitat": "hydrothermal_vent",
            "salinity_ppt": 34.8,
            "temperature_celsius": 4.0,
            "created_at": datetime(2026, 5, 3, 14, 30, tzinfo=timezone.utc),
        },
    ]
    for u in uploads:
        await db["uploads"].update_one(
            {"upload_id": u["upload_id"]}, {"$setOnInsert": u}, upsert=True
        )
    print(f"  uploads: {len(uploads)} upserted")

    # ------------------------------------------------------------------
    # Analysis jobs
    # ------------------------------------------------------------------
    jobs = [
        {
            "job_id": "job_dev_001",
            "upload_id": "upl_dev_001",
            "user_id": DEV_USER_ID,
            "state": "completed",
            "analysis_id": "ana_dev_001",
            "mode": "online_full",
            "queued_at": datetime(2026, 5, 1, 8, 1, tzinfo=timezone.utc),
            "started_at": datetime(2026, 5, 1, 8, 1, 5, tzinfo=timezone.utc),
            "completed_at": datetime(2026, 5, 1, 8, 2, 12, tzinfo=timezone.utc),
        },
        {
            "job_id": "job_dev_002",
            "upload_id": "upl_dev_002",
            "user_id": DEV_USER_ID,
            "state": "queued",
            "analysis_id": None,
            "mode": "online_full",
            "queued_at": datetime(2026, 5, 3, 14, 31, tzinfo=timezone.utc),
            "started_at": None,
            "completed_at": None,
        },
    ]
    for j in jobs:
        await db["analysis_jobs"].update_one(
            {"job_id": j["job_id"]}, {"$setOnInsert": j}, upsert=True
        )
    print(f"  analysis_jobs: {len(jobs)} upserted")

    # ------------------------------------------------------------------
    # Analysis results (mock — no real model output yet)
    # ------------------------------------------------------------------
    result = {
        "analysis_id": "ana_dev_001",
        "job_id": "job_dev_001",
        "upload_id": "upl_dev_001",
        "user_id": DEV_USER_ID,
        "mode": "online_full",
        "model_version_set": "smoke_test_v0",
        "summary": {
            "total_sequences": 5,
            "known_species": 3,
            "possible_novelty": 1,
            "contamination_flags": 1,
            "low_quality": 0,
            "route_distribution": {
                "fish": 2,
                "bacteria_pathogen": 2,
                "human_domestic_contamination": 1,
            },
        },
        "results": [
            {
                "sequence_id": "seq_001",
                "sequence": "ATCGATCGATCGATCG",
                "length": 16,
                "gc_ratio": 0.5,
                "n_ratio": 0.0,
                "route": "fish",
                "route_confidence": 0.84,
                "result_class": "known_species",
                "predicted_taxon": "Acanthurus nigrofuscus",
                "confidence": 0.82,
                "novelty_score": 0.05,
                "contamination_score": 0.01,
                "reason_codes": ["kmer_fish_like", "length_marker_compatible"],
                "model_version_used": "smoke_test_v0",
            },
            {
                "sequence_id": "seq_002",
                "sequence": "GCTAGCTAGCTAGCTA",
                "length": 16,
                "gc_ratio": 0.5,
                "n_ratio": 0.0,
                "route": "fish",
                "route_confidence": 0.61,
                "result_class": "possible_novelty",
                "predicted_taxon": None,
                "confidence": 0.31,
                "novelty_score": 0.78,
                "contamination_score": 0.04,
                "reason_codes": ["low_reference_similarity", "stable_unknown_cluster"],
                "model_version_used": "smoke_test_v0",
            },
            {
                "sequence_id": "seq_003",
                "sequence": "TTTTAAAACCCCGGGG",
                "length": 16,
                "gc_ratio": 0.5,
                "n_ratio": 0.0,
                "route": "human_domestic_contamination",
                "route_confidence": 0.91,
                "result_class": "possible_contamination",
                "predicted_taxon": "Homo sapiens",
                "confidence": 0.89,
                "novelty_score": 0.02,
                "contamination_score": 0.93,
                "reason_codes": ["human_kmer_match", "low_abundance"],
                "model_version_used": "smoke_test_v0",
            },
        ],
        "created_at": datetime(2026, 5, 1, 8, 2, 12, tzinfo=timezone.utc),
    }
    await db["analysis_results"].update_one(
        {"analysis_id": result["analysis_id"]}, {"$setOnInsert": result}, upsert=True
    )
    print("  analysis_results: 1 upserted")

    # ------------------------------------------------------------------
    # Expert reviews
    # ------------------------------------------------------------------
    reviews = [
        {
            "review_id": "rev_dev_001",
            "analysis_id": "ana_dev_001",
            "sequence_id": "seq_002",
            "submitted_by": DEV_USER_ID,
            "state": "submitted",
            "correction_type": "novelty_flag",
            "proposed_taxon": None,
            "is_novelty": True,
            "is_contamination": False,
            "is_low_quality": False,
            "evidence_notes": "Consistent unknown cluster across 3 samples from same transect.",
            "decided_by": None,
            "decision_notes": None,
            "decided_at": None,
            "created_at": datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
        },
        {
            "review_id": "rev_dev_002",
            "analysis_id": "ana_dev_001",
            "sequence_id": "seq_003",
            "submitted_by": DEV_USER_ID,
            "state": "accepted",
            "correction_type": "contamination_flag",
            "proposed_taxon": "Homo sapiens",
            "is_novelty": False,
            "is_contamination": True,
            "is_low_quality": False,
            "evidence_notes": "Confirmed human mitochondrial match.",
            "decided_by": DEV_CURATOR_ID,
            "decision_notes": "Confirmed. Low-abundance human contamination from researcher handling.",
            "decided_at": datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc),
            "created_at": datetime(2026, 5, 1, 9, 5, tzinfo=timezone.utc),
        },
    ]
    for r in reviews:
        await db["reviews"].update_one(
            {"review_id": r["review_id"]}, {"$setOnInsert": r}, upsert=True
        )
    print(f"  reviews: {len(reviews)} upserted")

    print("\nDev seed complete.")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
