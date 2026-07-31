"""
Promote a trained model run to the model registry.

Usage (dry-run — prints what would be written):
    python scripts/training/promote.py --run-id dnabert2_fish_v2

Usage (write to registry — requires explicit human sign-off):
    python scripts/training/promote.py --run-id dnabert2_fish_v2 --approve

Options:
    --status    Initial registry status: experimental (default), staging
                Promotion to 'production' is a separate manual step — edit
                the registry JSON and set "status": "production" after QA.
    --promoted-by  Your user_id or name (recorded in the registry entry)

Anti-poisoning rule (enforced here):
    Without --approve this script prints the registry entry that WOULD be
    written and exits with code 0.  No file is touched.
    With --approve a new JSON is written to models/registry/<run_id>.json.
    Status 'production' is never set automatically — it requires a human
    to edit the JSON file directly after sufficient validation.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_REGISTRY_DIR = Path("models/registry")
_ALLOWED_STATUSES = {"experimental", "staging"}  # production is set manually


def build_registry_entry(run_id: str, run_dir: Path, status: str, promoted_by: str | None) -> dict:
    cfg = json.loads((run_dir / "training_config.json").read_text())
    metrics = json.loads((run_dir / "metrics.json").read_text()) if (run_dir / "metrics.json").exists() else {}

    route = cfg.get("route", "unknown")
    base_model = cfg.get("base_model", "zhihan1996/DNABERT-2-117M")
    labels = cfg.get("labels", [])
    num_labels = cfg.get("num_labels", len(labels))

    # Thresholds: standard defaults used by the inference engine
    thresholds = {
        "high_confidence": 0.75,
        "low_confidence": 0.40,
    }

    return {
        "model_id": run_id,
        "route": route,
        "base_model": base_model,
        "head_type": "sequence_classification",
        "embedding_dim": 768,
        "label_set_version": "v1",
        "label_set": labels,
        "num_labels": num_labels,
        "training_dataset_version": cfg.get("batch_id") or run_id,
        "metrics": {
            "accuracy": round(metrics.get("accuracy", 0.0), 4),
            "f1_macro": round(metrics.get("f1_macro", 0.0), 4),
            "train_samples": metrics.get("train_samples", 0),
            "val_samples": metrics.get("val_samples", 0),
        },
        "thresholds": thresholds,
        # artifact_uri points to the run directory; update to HF Hub URI if uploading
        "artifact_uri": str(run_dir.resolve()),
        "checksum": None,  # populate with sha256 of adapter_model.safetensors if needed
        "created_at": date.today().isoformat(),
        "promoted_by": promoted_by,
        "status": status,
        "notes": (
            f"Fine-tuned from {base_model} on curated batch {run_id}. "
            f"Accuracy={metrics.get('accuracy', 0):.3f}, F1={metrics.get('f1_macro', 0):.3f}. "
            f"Set status=production only after full QA and A/B test against current production model."
        ),
    }


def promote(run_id: str, status: str, promoted_by: str | None, approve: bool) -> None:
    run_dir = Path("models/runs") / run_id
    if not run_dir.exists():
        logger.error("Run directory not found: %s — run train.py first", run_dir)
        sys.exit(1)

    required = ["training_config.json", "adapter_config.json"]
    for f in required:
        if not (run_dir / f).exists():
            logger.error("Missing %s in %s — training may not have completed", f, run_dir)
            sys.exit(1)

    if status not in _ALLOWED_STATUSES:
        logger.error(
            "Status %r is not allowed via promote.py. "
            "Allowed: %s. Set 'production' by hand-editing the registry JSON after QA.",
            status, _ALLOWED_STATUSES,
        )
        sys.exit(1)

    entry = build_registry_entry(run_id, run_dir, status, promoted_by)

    print("\n" + "=" * 60)
    print(f"Registry entry for {run_id}")
    print("=" * 60)
    print(json.dumps(entry, indent=2))
    print("=" * 60)

    target = _REGISTRY_DIR / f"{run_id}.json"

    if not approve:
        print(f"\n[DRY RUN] Would write to: {target}")
        print("Re-run with --approve to actually write the registry entry.\n")
        return

    _REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(entry, indent=2))
    print(f"\n[PROMOTED] Registry entry written to {target}")
    print(
        "\nReminder: status is currently 'experimental' or 'staging'.\n"
        "To make this model serve production traffic, edit the JSON and set:\n"
        '  "status": "production"\n'
        "Only do this after sufficient A/B validation against the current production model.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote a trained model run to the model registry"
    )
    parser.add_argument("--run-id", required=True,
                        help="Run ID matching the models/runs/<run-id> directory")
    parser.add_argument("--status", default="experimental", choices=list(_ALLOWED_STATUSES),
                        help="Initial registry status (default: experimental)")
    parser.add_argument("--promoted-by",
                        help="Your user_id or name — recorded in the registry entry")
    parser.add_argument("--approve", action="store_true",
                        help="Actually write the registry entry (without this, dry-run only)")
    args = parser.parse_args()

    promote(
        run_id=args.run_id,
        status=args.status,
        promoted_by=args.promoted_by,
        approve=args.approve,
    )


if __name__ == "__main__":
    main()
