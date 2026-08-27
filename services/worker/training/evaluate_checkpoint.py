"""
Re-evaluates an already-trained checkpoint's test set to backfill per-class
precision/recall/F1 + a confusion matrix, without retraining.

Only finetune.py's *new* runs write eval_report.json automatically (see
build_eval_report there). Checkpoints trained before that change only have
aggregate accuracy/macro-F1 in metrics.json. This script loads the saved
backbone + head, re-runs one no-grad forward pass over the route's test.csv,
and writes the same eval_report.json a fresh training run would have
produced — reusing finetune.py's SequenceDataset/collate/extract_cls/
build_eval_report so the two never drift into different schemas.

Run from services/worker/:
    python -m training.evaluate_checkpoint --route bacteria_pathogen
    python -m training.evaluate_checkpoint --route bacteria_pathogen \
        --checkpoint-dir E:/synthveda-data/checkpoints/bacteria_pathogen_nt500m_clean
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# DNABERT-2's custom modeling code falls back to plain PyTorch attention when
# Triton is unavailable (see bert_layers.py's `except ImportError`) -- but a
# community `triton-windows` package makes `import triton` succeed while its
# JIT compiler still isn't available (no C compiler on PATH), so it takes the
# Triton path and crashes instead of falling back. Force the ImportError so
# it degrades the way the architecture actually intends on this machine.
sys.modules["triton"] = None  # type: ignore[assignment]

import torch
from torch.utils.data import DataLoader

from app.inference.heads import DNAClassifierHead
from app.inference.models import ROUTE_LABEL_SETS
from training.finetune import SequenceDataset, build_eval_report, collate, extract_cls


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", required=True, choices=list(ROUTE_LABEL_SETS.keys()))
    parser.add_argument("--data-dir", default="E:/synthveda-data")
    parser.add_argument("--checkpoint-dir", default=None, help="Defaults to <data-dir>/checkpoints/<route>")
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()

    from transformers import AutoModel, AutoModelForMaskedLM, AutoTokenizer, AutoConfig

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device}")

    labels = ROUTE_LABEL_SETS[args.route]
    label_names = [str(l) for l in labels]
    label_to_idx = {name: i for i, name in enumerate(label_names)}

    checkpoint_dir = Path(args.checkpoint_dir) if args.checkpoint_dir else Path(args.data_dir) / "checkpoints" / args.route
    backbone_dir = checkpoint_dir / "backbone"
    head_path = checkpoint_dir / "head.pt"
    if not head_path.exists():
        raise SystemExit(f"no head.pt at {head_path}")

    metrics_path = checkpoint_dir / "metrics.json"
    saved_metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    embedding_dim = saved_metrics.get("embedding_dim")

    print(f"loading backbone: {backbone_dir}")
    tokenizer = AutoTokenizer.from_pretrained(backbone_dir, trust_remote_code=True)
    config = AutoConfig.from_pretrained(backbone_dir, trust_remote_code=True)
    if "AutoModel" not in getattr(config, "auto_map", {}) and getattr(config, "model_type", None) == "esm":
        # Mirrors finetune.py/loader.py: some ESM-family repos only map
        # AutoModelForMaskedLM to their custom gated-FFN encoder.
        backbone = AutoModelForMaskedLM.from_pretrained(backbone_dir, trust_remote_code=True).esm
    else:
        backbone = AutoModel.from_pretrained(backbone_dir, trust_remote_code=True)
    backbone = backbone.to(device)
    backbone.eval()
    if embedding_dim is None:
        embedding_dim = backbone.config.hidden_size

    head = DNAClassifierHead(embedding_dim=embedding_dim, num_classes=len(labels)).to(device)
    head.load_state_dict(torch.load(head_path, map_location=device))
    head.eval()

    data_dir = Path(args.data_dir) / "processed" / args.route
    test_ds = SequenceDataset(data_dir / "test.csv", label_to_idx, tokenizer, args.max_length)
    print(f"test={len(test_ds)}")

    loader_kwargs = {"collate_fn": collate}
    if device == "cuda":
        loader_kwargs["pin_memory"] = True
    test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False, **loader_kwargs)

    all_preds, all_labels = [], []
    with torch.no_grad():
        for batch, batch_labels in test_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            out = backbone(**batch)
            logits = head(extract_cls(out))
            all_preds.extend(logits.argmax(dim=-1).cpu().tolist())
            all_labels.extend(batch_labels.tolist())

    report = build_eval_report(all_labels, all_preds, label_names)
    print(f"\nTEST  acc={report['accuracy']:.4f}  macro_f1={report['f1_macro']:.4f}")
    from sklearn.metrics import classification_report
    print(classification_report(
        all_labels, all_preds, target_names=label_names,
        labels=list(range(len(labels))), zero_division=0,
    ))

    report_path = checkpoint_dir / "eval_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"saved: {report_path}")

    if saved_metrics:
        saved_metrics["test_accuracy"] = round(report["accuracy"], 4)
        saved_metrics["test_macro_f1"] = round(report["f1_macro"], 4)
        metrics_path.write_text(json.dumps(saved_metrics, indent=2))
        print(f"updated: {metrics_path}")


if __name__ == "__main__":
    main()
