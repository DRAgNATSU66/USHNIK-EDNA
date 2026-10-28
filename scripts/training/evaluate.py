"""
Run a detailed evaluation of a trained model on the val split.

Usage:
    python scripts/training/evaluate.py \\
        --run-id dnabert2_fish_v2 \\
        --batch-dir data/batches/tbatch_202606_fish_abc12345/

Reads:
    models/runs/<run-id>/adapter_model.safetensors + adapter_config.json
    models/runs/<run-id>/label_map.json
    models/runs/<run-id>/training_config.json

Writes:
    models/runs/<run-id>/eval_report.json  — per-class metrics + confusion matrix
    (updates metrics.json with eval_report path)

Prints a human-readable classification report.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score, f1_score, classification_report, confusion_matrix
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def evaluate(run_id: str, batch_dir: Path) -> None:
    run_dir = Path("models/runs") / run_id
    if not run_dir.exists():
        logger.error("Run directory not found: %s — run train.py first", run_dir)
        sys.exit(1)

    # --- Load config ---
    cfg_path = run_dir / "training_config.json"
    label_map_path = run_dir / "label_map.json"
    if not cfg_path.exists() or not label_map_path.exists():
        logger.error("Missing training_config.json or label_map.json in %s", run_dir)
        sys.exit(1)

    cfg = json.loads(cfg_path.read_text())
    label_map = json.loads(label_map_path.read_text())
    id2label: dict[str, str] = {str(k): v for k, v in label_map["id2label"].items()}
    label2id: dict[str, int] = label_map["label2id"]
    route_labels = [id2label[str(i)] for i in range(len(id2label))]

    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        from peft import PeftModel
        import torch
    except ImportError as e:
        logger.error("Missing ML dependency: %s. Run: pip install -r scripts/training/requirements.txt", e)
        sys.exit(1)

    # --- Load model ---
    base_model_id = cfg.get("base_model", "zhihan1996/DNABERT-2-117M")
    max_length = cfg.get("max_length", 512)
    val_fraction = 0.2
    seed = 42

    logger.info("Loading tokenizer from %s", base_model_id)
    tokenizer = AutoTokenizer.from_pretrained(
        str(run_dir),
        trust_remote_code=False,
        use_fast=True,
    )

    logger.info("Loading base model %s", base_model_id)
    base = AutoModelForSequenceClassification.from_pretrained(
        base_model_id,
        num_labels=len(route_labels),
        id2label={int(k): v for k, v in id2label.items()},
        label2id=label2id,
        trust_remote_code=False,
    )
    model = PeftModel.from_pretrained(base, str(run_dir))
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    logger.info("Model loaded on %s", device)

    # --- Load val data ---
    csv_path = batch_dir / "sequences.csv"
    if not csv_path.exists():
        logger.error("sequences.csv not found in %s", batch_dir)
        sys.exit(1)

    df = pd.read_csv(csv_path)
    route = cfg.get("route", "")
    if "route" in df.columns and route:
        df = df[df["route"] == route]

    valid_labels = set(route_labels)
    df["label"] = df["label"].apply(lambda l: l if l in valid_labels else route_labels[-1])

    sequences = df["dna_sequence"].tolist()
    labels = df["label"].tolist()

    _, val_seqs, _, val_labels = train_test_split(
        sequences, labels, test_size=val_fraction, random_state=seed,
        stratify=labels if len(set(labels)) > 1 else None
    )
    logger.info("Evaluating on %d validation sequences", len(val_seqs))

    # --- Inference ---
    all_preds: list[int] = []
    all_true: list[int] = []

    batch_size = cfg.get("batch_size", 8)
    for i in range(0, len(val_seqs), batch_size):
        batch_seqs = val_seqs[i: i + batch_size]
        batch_labels = val_labels[i: i + batch_size]

        enc = tokenizer(
            batch_seqs,
            padding="max_length",
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        enc = {k: v.to(device) for k, v in enc.items()}

        with torch.no_grad():
            logits = model(**enc).logits

        preds = torch.argmax(logits, dim=-1).cpu().numpy().tolist()
        all_preds.extend(preds)
        all_true.extend([label2id[l] for l in batch_labels])

    # --- Metrics ---
    acc = accuracy_score(all_true, all_preds)
    f1 = f1_score(all_true, all_preds, average="macro", zero_division=0)
    report = classification_report(
        all_true, all_preds,
        target_names=route_labels,
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(all_true, all_preds).tolist()

    print("\n" + "=" * 60)
    print(f"Evaluation: {run_id}")
    print(f"  Accuracy : {acc:.4f}")
    print(f"  F1 macro : {f1:.4f}")
    print("=" * 60)
    print(classification_report(
        all_true, all_preds,
        target_names=route_labels,
        zero_division=0,
    ))

    eval_report = {
        "run_id": run_id,
        "accuracy": acc,
        "f1_macro": f1,
        "per_class": report,
        "confusion_matrix": cm,
        "label_order": route_labels,
        "val_samples": len(val_seqs),
    }
    report_path = run_dir / "eval_report.json"
    report_path.write_text(json.dumps(eval_report, indent=2))
    logger.info("Eval report written to %s", report_path)

    # Update metrics.json
    metrics_path = run_dir / "metrics.json"
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text())
        metrics["accuracy"] = acc
        metrics["f1_macro"] = f1
        metrics["eval_report_path"] = str(report_path)
        metrics_path.write_text(json.dumps(metrics, indent=2))

    print(f"\nNext step — if metrics are acceptable, run:")
    print(f"  python scripts/training/promote.py --run-id {run_id} --approve")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a trained model against the validation split")
    parser.add_argument("--run-id", required=True, help="Run ID used during train.py")
    parser.add_argument("--batch-dir", required=True, type=Path,
                        help="Directory containing sequences.csv")
    args = parser.parse_args()
    evaluate(args.run_id, args.batch_dir)


if __name__ == "__main__":
    main()
