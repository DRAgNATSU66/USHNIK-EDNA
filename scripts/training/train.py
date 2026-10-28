"""
Fine-tune a DNABERT-2 classification head on an exported training batch.

Usage:
    python scripts/training/train.py \\
        --route fish \\
        --batch-dir data/batches/tbatch_202606_fish_abc12345/ \\
        --run-id dnabert2_fish_v2 \\
        [--base-model zhihan1996/DNABERT-2-117M] \\
        [--epochs 3] [--batch-size 8] [--lr 2e-4] [--max-length 512]

Outputs (in models/runs/<run-id>/):
    adapter_model.safetensors — LoRA adapter weights
    adapter_config.json       — PEFT config
    tokenizer_config.json / tokenizer.json — tokenizer snapshot
    label_map.json            — id2label / label2id
    training_config.json      — full hyperparameter record
    metrics.json              — validation accuracy, F1 (written by evaluate.py)

Anti-poisoning:
    This script NEVER writes to models/registry/.
    Use promote.py --approve after reviewing metrics.json to register the new model.

Security:
    trust_remote_code is always False. Only zhihan1996/DNABERT-2-117M or a
    local path may be used as base_model (controlled by --base-model).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Allowed base models — never accept arbitrary paths from users.
_ALLOWED_BASE_MODELS = {
    "zhihan1996/DNABERT-2-117M",
    "InstaDeepAI/nucleotide-transformer-50m-multi-species",
}

# Label sets per route (must match ROUTE_LABEL_SETS in worker inference/models.py)
_ROUTE_LABELS: dict[str, list[str]] = {
    "fish": ["known_species", "possible_novelty", "low_quality_unusable"],
    "plant": ["known_species", "possible_novelty", "possible_contamination", "low_quality_unusable"],
    "bacteria_pathogen": ["known_species", "likely_taxonomic_group", "possible_novelty", "possible_contamination"],
    "animal_general": ["known_species", "likely_taxonomic_group", "possible_novelty"],
    "human_domestic_contamination": ["possible_contamination", "known_species"],
    "misc_unknown": ["unknown_needs_online_confirmation", "possible_novelty", "low_quality_unusable"],
}


def _load_data(batch_dir: Path, route: str, route_labels: list[str]) -> tuple:
    csv_path = batch_dir / "sequences.csv"
    if not csv_path.exists():
        logger.error("sequences.csv not found in %s — run export_batch.py first", batch_dir)
        sys.exit(1)

    df = pd.read_csv(csv_path)
    # Filter to this route if route column is present
    if "route" in df.columns:
        route_df = df[df["route"] == route].copy()
        if route_df.empty:
            logger.warning("No sequences for route %r; using all sequences", route)
            route_df = df.copy()
    else:
        route_df = df.copy()

    # Map labels to route label set; sequences with unmapped labels fall to the last class
    valid_labels = set(route_labels)
    route_df["label"] = route_df["label"].apply(
        lambda l: l if l in valid_labels else route_labels[-1]
    )

    sequences = route_df["dna_sequence"].tolist()
    labels = route_df["label"].tolist()
    return sequences, labels


def _build_dataset(sequences: list[str], labels: list[str], tokenizer, max_length: int, label2id: dict):
    from datasets import Dataset as HFDataset

    int_labels = [label2id[l] for l in labels]
    ds = HFDataset.from_dict({
        "sequence": sequences,
        "label": int_labels,
    })

    def tokenize(batch):
        return tokenizer(
            batch["sequence"],
            padding="max_length",
            truncation=True,
            max_length=max_length,
        )

    ds = ds.map(tokenize, batched=True, remove_columns=["sequence"])
    ds.set_format("torch")
    return ds


def _compute_metrics(eval_pred):
    from sklearn.metrics import accuracy_score, f1_score
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {
        "accuracy": float(accuracy_score(labels, preds)),
        "f1_macro": float(f1_score(labels, preds, average="macro", zero_division=0)),
    }


def train(
    route: str,
    batch_dir: Path,
    run_id: str,
    base_model: str,
    epochs: int,
    batch_size: int,
    lr: float,
    max_length: int,
    val_fraction: float,
    seed: int,
) -> None:
    if base_model not in _ALLOWED_BASE_MODELS:
        logger.error(
            "Base model %r is not in the allowed list. "
            "Allowed: %s", base_model, _ALLOWED_BASE_MODELS
        )
        sys.exit(1)

    route_labels = _ROUTE_LABELS.get(route)
    if route_labels is None:
        logger.error("Unknown route %r. Allowed: %s", route, list(_ROUTE_LABELS))
        sys.exit(1)

    label2id = {l: i for i, l in enumerate(route_labels)}
    id2label = {i: l for l, i in label2id.items()}

    run_dir = Path("models/runs") / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Run directory: %s", run_dir)

    # --- Import heavy deps late so the CLI prints help without torch ---
    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification, TrainingArguments, Trainer
        from peft import LoraConfig, get_peft_model, TaskType
    except ImportError as e:
        logger.error("Missing ML dependency: %s. Run: pip install -r scripts/training/requirements.txt", e)
        sys.exit(1)

    logger.info("Loading tokenizer from %s", base_model)
    tokenizer = AutoTokenizer.from_pretrained(
        base_model,
        trust_remote_code=False,  # security: never trust arbitrary remote code
        use_fast=True,
    )

    logger.info("Loading base model from %s", base_model)
    model = AutoModelForSequenceClassification.from_pretrained(
        base_model,
        num_labels=len(route_labels),
        id2label=id2label,
        label2id=label2id,
        trust_remote_code=False,
    )

    # LoRA adapter — only fine-tune attention projections
    lora_cfg = LoraConfig(
        task_type=TaskType.SEQ_CLS,
        r=16,
        lora_alpha=32,
        lora_dropout=0.1,
        target_modules=["query", "key", "value"],
        bias="none",
    )
    model = get_peft_model(model, lora_cfg)
    model.print_trainable_parameters()

    # --- Data ---
    sequences, labels = _load_data(batch_dir, route, route_labels)
    if len(sequences) < 4:
        logger.error("Not enough sequences for training (found %d, need ≥ 4)", len(sequences))
        sys.exit(1)

    train_seqs, val_seqs, train_labels, val_labels = train_test_split(
        sequences, labels, test_size=val_fraction, random_state=seed, stratify=labels
        if len(set(labels)) > 1 else None
    )
    logger.info("Train: %d  |  Val: %d", len(train_seqs), len(val_seqs))

    train_ds = _build_dataset(train_seqs, train_labels, tokenizer, max_length, label2id)
    val_ds = _build_dataset(val_seqs, val_labels, tokenizer, max_length, label2id)

    # --- Training ---
    training_args = TrainingArguments(
        output_dir=str(run_dir / "checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        gradient_accumulation_steps=2,
        learning_rate=lr,
        weight_decay=0.01,
        warmup_ratio=0.1,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1_macro",
        greater_is_better=True,
        logging_steps=20,
        save_total_limit=2,
        seed=seed,
        report_to="none",  # no wandb/tensorboard required
        fp16=False,        # set to True if GPU with CUDA ≥ 7.5
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        compute_metrics=_compute_metrics,
    )

    logger.info("Starting training — route=%s  epochs=%d  lr=%g", route, epochs, lr)
    trainer.train()

    # --- Save adapter only (not the full base model) ---
    model.save_pretrained(run_dir)
    tokenizer.save_pretrained(run_dir)
    logger.info("Adapter saved to %s", run_dir)

    # --- Write label map ---
    label_map = {"id2label": id2label, "label2id": label2id}
    (run_dir / "label_map.json").write_text(json.dumps(label_map, indent=2))

    # --- Final evaluation ---
    eval_result = trainer.evaluate()
    metrics = {
        "accuracy": eval_result.get("eval_accuracy", 0.0),
        "f1_macro": eval_result.get("eval_f1_macro", 0.0),
        "eval_loss": eval_result.get("eval_loss", 0.0),
        "train_samples": len(train_seqs),
        "val_samples": len(val_seqs),
        "route": route,
        "base_model": base_model,
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": lr,
        "max_length": max_length,
        "run_id": run_id,
    }
    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))
    logger.info("Metrics: accuracy=%.4f  f1_macro=%.4f", metrics["accuracy"], metrics["f1_macro"])

    # --- Write training config record ---
    training_config = {
        "run_id": run_id,
        "route": route,
        "base_model": base_model,
        "num_labels": len(route_labels),
        "labels": route_labels,
        "lora_r": 16,
        "lora_alpha": 32,
        "epochs": epochs,
        "batch_size": batch_size,
        "accumulation_steps": 2,
        "learning_rate": lr,
        "max_length": max_length,
        "train_samples": len(train_seqs),
        "val_samples": len(val_seqs),
        "final_accuracy": metrics["accuracy"],
        "final_f1": metrics["f1_macro"],
    }
    (run_dir / "training_config.json").write_text(json.dumps(training_config, indent=2))

    print("\n" + "=" * 60)
    print(f"Training complete: {run_id}")
    print(f"  Accuracy : {metrics['accuracy']:.4f}")
    print(f"  F1 macro : {metrics['f1_macro']:.4f}")
    print(f"  Run dir  : {run_dir.resolve()}")
    print("=" * 60)
    print("\nNext step — review metrics then run:")
    print(f"  python scripts/training/promote.py --run-id {run_id} --approve")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune DNABERT-2 on a curated training batch")
    parser.add_argument("--route", required=True, choices=list(_ROUTE_LABELS),
                        help="Taxonomic route to train")
    parser.add_argument("--batch-dir", required=True, type=Path,
                        help="Directory containing sequences.csv (output of export_batch.py)")
    parser.add_argument("--run-id", required=True,
                        help="Run identifier, e.g. dnabert2_fish_v2 (used as output dir name)")
    parser.add_argument("--base-model", default="zhihan1996/DNABERT-2-117M",
                        choices=list(_ALLOWED_BASE_MODELS),
                        help="HuggingFace model ID for the base model")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--val-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    train(
        route=args.route,
        batch_dir=args.batch_dir,
        run_id=args.run_id,
        base_model=args.base_model,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        max_length=args.max_length,
        val_fraction=args.val_fraction,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
