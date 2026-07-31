"""
Export a frozen training batch from MongoDB to a labeled CSV dataset.

Usage:
    python scripts/training/export_batch.py \\
        --batch-id tbatch_202606_fish_abc12345 \\
        --out-dir data/batches/

Output (in --out-dir):
    sequences.csv   — sequence_id, dna_sequence, label, route, proposed_taxon, review_id
    batch_meta.json — batch metadata and sequence count

The exported CSV is the input to train.py.

Environment variables:
    MONGODB_URI   — MongoDB connection string (required)
    MONGODB_DB    — database name (default: synthveda)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017")
MONGODB_DB = os.environ.get("MONGODB_DB", "synthveda")

# Maps review signals → training label for the classification head.
# If proposed_taxon is set, we use the label set class derived from correction_type.
_CORRECTION_TO_LABEL = {
    "species_correction": "known_species",
    "auto_novelty_flag": "possible_novelty",
    "manual_novelty": "possible_novelty",
    "auto_contamination_flag": "possible_contamination",
    "manual_contamination": "possible_contamination",
    "low_quality": "low_quality_unusable",
}


def _derive_label(review: dict) -> str:
    """Derive the training label for a review document."""
    correction_type: str = review.get("correction_type", "")
    if correction_type in _CORRECTION_TO_LABEL:
        return _CORRECTION_TO_LABEL[correction_type]
    if review.get("is_contamination"):
        return "possible_contamination"
    if review.get("is_novelty"):
        return "possible_novelty"
    if review.get("is_low_quality"):
        return "low_quality_unusable"
    # Fallback: curator accepted the result as-is → known_species
    return "known_species"


async def _export(batch_id: str, out_dir: Path) -> None:
    client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=10_000)
    db = client[MONGODB_DB]

    # 1. Load all reviews in this batch
    reviews = []
    async for doc in db["reviews"].find({"training_batch_id": batch_id}):
        doc.pop("_id", None)
        reviews.append(doc)

    if not reviews:
        print(f"[export] No reviews found for batch {batch_id!r}. "
              f"Has it been created and frozen?", file=sys.stderr)
        sys.exit(1)

    print(f"[export] Found {len(reviews)} accepted reviews in batch {batch_id!r}")

    # 2. Fetch original DNA sequences from analyses collection
    # Group review lookups by analysis_id to minimise round trips.
    by_analysis: dict[str, list[dict]] = {}
    for rev in reviews:
        by_analysis.setdefault(rev["analysis_id"], []).append(rev)

    rows: list[dict] = []
    missing = 0

    for analysis_id, batch_reviews in by_analysis.items():
        ana_doc = await db["analyses"].find_one({"analysis_id": analysis_id})
        if ana_doc is None:
            print(f"[export] WARNING: analysis {analysis_id!r} not found — "
                  f"skipping {len(batch_reviews)} review(s)")
            missing += len(batch_reviews)
            continue

        seq_index: dict[str, dict] = {
            s["sequence_id"]: s for s in ana_doc.get("results", [])
        }

        for rev in batch_reviews:
            seq_id = rev["sequence_id"]
            seq_doc = seq_index.get(seq_id)
            if seq_doc is None:
                print(f"[export] WARNING: sequence {seq_id!r} not found in "
                      f"analysis {analysis_id!r} — skipping")
                missing += 1
                continue

            dna = seq_doc.get("sequence", "")
            if not dna:
                print(f"[export] WARNING: empty sequence for {seq_id!r} — skipping")
                missing += 1
                continue

            rows.append({
                "sequence_id": seq_id,
                "dna_sequence": dna,
                "label": _derive_label(rev),
                "route": seq_doc.get("route", ""),
                "proposed_taxon": rev.get("proposed_taxon") or seq_doc.get("predicted_taxon") or "",
                "review_id": rev["review_id"],
                "analysis_id": analysis_id,
                "novelty_score": rev.get("novelty_score"),
                "contamination_score": rev.get("contamination_score"),
            })

    client.close()

    if not rows:
        print("[export] ERROR: no exportable sequences after filtering.", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(rows)
    csv_path = out_dir / "sequences.csv"
    df.to_csv(csv_path, index=False)
    print(f"[export] Wrote {len(df)} sequences to {csv_path}")
    if missing:
        print(f"[export] WARNING: {missing} sequence(s) skipped due to missing data")

    # Label distribution
    print("[export] Label distribution:")
    for label, count in df["label"].value_counts().items():
        print(f"         {label}: {count}")

    meta = {
        "batch_id": batch_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "sequence_count": len(df),
        "missing_count": missing,
        "label_distribution": df["label"].value_counts().to_dict(),
        "routes": df["route"].value_counts().to_dict(),
        "csv_path": str(csv_path),
    }
    meta_path = out_dir / "batch_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"[export] Metadata written to {meta_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export frozen training batch to CSV")
    parser.add_argument("--batch-id", required=True, help="Training batch ID (tbatch_...)")
    parser.add_argument("--out-dir", required=True, type=Path, help="Output directory")
    args = parser.parse_args()

    asyncio.run(_export(args.batch_id, args.out_dir))


if __name__ == "__main__":
    main()
